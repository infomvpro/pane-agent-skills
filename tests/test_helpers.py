from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/pane-displays"
sys.path.insert(0, str(SKILL / "scripts"))

from pane_common import SafeError, api_origin, decode_json, get_bytes, read_json
from preview_bundle import bundle, png_image, preview_url
from validate_payload import validate
from wait_for_display import classify, poll


def example(name="main-summary.json"):
    return read_json(SKILL / "examples" / name)


def status():
    return {
        "current_frame": {"frame_id": "frm_example", "publication_version": 9,
                          "published_at": "2026-10-20T10:00:00Z"},
        "current_frame_ack": {"frame_id": "frm_example", "publication_version": 9,
                              "ack_at": "2026-10-20T10:00:02+00:00", "validated": True, "status": "displayed"},
    }


def png():
    out = io.BytesIO()
    Image.new("RGB", (800, 480), "white").save(out, format="PNG")
    return out.getvalue()


class PayloadTests(unittest.TestCase):
    def validate(self, data, kind="render-mcp", schemas=None):
        return validate(data, kind, schemas or SKILL / "schemas")

    def test_all_examples(self):
        for name, kind in read_json(ROOT / "tests/example-cases.json").items():
            with self.subTest(name=name):
                result = self.validate(example(name), kind)
                self.assertTrue(result["ok"], result)
                self.assertFalse(result["warnings"])

    def test_missing_required_card_data(self):
        data = example()
        del data["cards"][1]["data"]["body"]
        self.assertFalse(self.validate(data)["ok"])

    def test_numeric_types_and_boolean_priority(self):
        data = example("multi-display.json")["renders"][1]
        data["cards"][0]["data"]["temp_c"] = "12"
        self.assertFalse(self.validate(data)["ok"])
        data["cards"][0]["data"]["temp_c"] = 12
        data["cards"][0]["priority"] = True
        self.assertFalse(self.validate(data)["ok"])

    def test_duplicate_ids(self):
        data = example()
        data["cards"][1]["id"] = data["cards"][0]["id"]
        self.assertFalse(self.validate(data)["ok"])

    def test_deprecated_layout_and_unknown_envelope_rejected(self):
        for key in ("layout_hint", "theme", "made_up"):
            data = example()
            data[key] = "value"
            self.assertFalse(self.validate(data)["ok"])
        data = example()
        data["cards"][0]["preferred_span"] = "2x2"
        self.assertFalse(self.validate(data)["ok"])

    def test_ttl_and_queue(self):
        for ttl in (0, 4, 3601, "60", True):
            data = example("temporary-notice.json")
            data["ttl_sec"] = ttl
            self.assertFalse(self.validate(data)["ok"])
        data = example("temporary-notice.json")
        data["conflict_policy"] = "queue"
        self.assertFalse(self.validate(data)["ok"])

    def test_rest_and_mcp_are_not_interchangeable(self):
        self.assertFalse(self.validate(example("temporary-notice.json"), "render-rest")["ok"])
        self.assertFalse(self.validate(example("temporary-rest.json"), "render-mcp")["ok"])
        data = example("temporary-rest.json")
        del data["temporary_view"]
        self.assertFalse(self.validate(data, "render-rest")["ok"])

    def test_main_ignores_no_temporary_options_locally(self):
        data = example()
        data["ttl_sec"] = 120
        self.assertFalse(self.validate(data)["ok"])

    def test_unknown_data_fields_are_rejected_not_echoed(self):
        data = example()
        data["cards"][1]["data"]["PRIVATE_FIELD"] = "PRIVATE_CONTENT"
        result = self.validate(data)
        self.assertFalse(result["ok"])
        self.assertTrue(result["errors"])
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_missing_schema_not_skipped(self):
        data = example()
        data["cards"][0]["type"] = "unknown.card"
        self.assertFalse(self.validate(data)["ok"])

    def test_schema_path_traversal_rejected(self):
        data = example()
        data["cards"][0]["type"] = "../../secrets"
        self.assertFalse(self.validate(data)["ok"])

    def test_single_segment_type_and_exported_wrapper(self):
        with tempfile.TemporaryDirectory() as directory:
            schemas = Path(directory)
            doc = {"card_type": "presence", "schema_available": True,
                   "schema": {"type": "object", "properties": {"text": {"type": "string"}}}}
            (schemas / "presence.schema.json").write_text(json.dumps(doc))
            data = {"display_id": "example", "cards": [{"type": "presence", "data": {"text": "Here"}}]}
            self.assertTrue(self.validate(data, schemas=schemas)["ok"])
            doc["card_type"] = "wrong.card"
            (schemas / "presence.schema.json").write_text(json.dumps(doc))
            with self.assertRaises(SafeError):
                self.validate(data, schemas=schemas)

    def test_external_schema_references_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            (p / "text.block.schema.json").write_text(json.dumps({"$ref": "https://example.invalid/private"}))
            data = {"display_id": "example", "cards": [example()["cards"][1]]}
            with self.assertRaisesRegex(SafeError, "external_schema_reference"):
                self.validate(data, schemas=p)

    def test_raw_frame_only(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            (p / "raw.frame.schema.json").write_text('{"type":"object"}')
            card = {"type": "raw.frame", "data": {}}
            data = {"display_id": "example", "cards": [card, copy.deepcopy(card)]}
            self.assertFalse(self.validate(data, schemas=p)["ok"])

    def test_card_limit(self):
        data = {"display_id": "example", "cards": [{"type": "text.block", "data": {"title": "x", "body": "y"}}] * 25}
        self.assertFalse(self.validate(data)["ok"])

    def test_nonfinite_duplicate_json_rejected(self):
        for raw in (b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e1000}', b'{"x":1,"x":2}'):
            with self.assertRaises(SafeError):
                decode_json(raw)


class AckTests(unittest.TestCase):
    def test_validated_displayed(self):
        self.assertEqual(classify(status(), "frm_example", 9), "device_reported_displayed")

    def test_old_version_unvalidated_fetched_old_time(self):
        for field, value in (("publication_version", 8), ("publication_version", True),
                             ("validated", False), ("status", "fetched"),
                             ("ack_at", "2026-10-20T09:00:00Z"), ("ack_at", "2026-10-20T10:01:00"),
                             ("frame_id", "frm_another")):
            data = status()
            data["current_frame_ack"][field] = value
            self.assertEqual(classify(data, "frm_example", 9), "pending")

    def test_changed_publication_stops(self):
        self.assertEqual(classify(status(), "frm_example", 8), "not_current")
        self.assertEqual(classify(status(), "frm_another", 9), "not_current")
        self.assertEqual(classify({"current_frame": None}, "frm_example", 9), "not_current")

    def test_missing_version_not_success(self):
        data = status()
        del data["current_frame"]["publication_version"]
        self.assertEqual(classify(data, "frm_example", 9), "unsupported_evidence")

    def test_failure_requires_current_valid_ack(self):
        data = status()
        data["current_frame_ack"]["status"] = "render_failed"
        self.assertEqual(classify(data, "frm_example", 9), "device_reported_failure")
        data["current_frame_ack"]["publication_version"] = 8
        self.assertEqual(classify(data, "frm_example", 9), "pending")

    def test_poll_pending_then_success(self):
        pending = status()
        pending["current_frame_ack"] = None
        responses = iter([pending, status()])
        clock = [0.0]
        result = poll("unused", "not-real", "frm_example", 9, timeout=20, interval=5, max_requests=4,
                      fetch=lambda *a, **k: json.dumps(next(responses)).encode(), clock=lambda: clock[0],
                      sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds))
        self.assertTrue(result["ok"])
        self.assertEqual(result["requests"], 2)

    def test_poll_request_and_time_budgets(self):
        pending = status()
        pending["current_frame_ack"] = None
        for timeout, count, expected in ((100, 2, 2), (6, 20, 2)):
            clock = [0.0]
            result = poll("unused", "not-real", "frm_example", 9, timeout=timeout, interval=5, max_requests=count,
                          fetch=lambda *a, **k: json.dumps(pending).encode(), clock=lambda: clock[0],
                          sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds))
            self.assertFalse(result["ok"])
            self.assertEqual(result["requests"], expected)

    def test_auth_error_no_retry(self):
        calls = []
        def fetch(*a, **k):
            calls.append(1)
            raise SafeError("http_401")
        with self.assertRaisesRegex(SafeError, "http_401"):
            poll("unused", "not-real", "frm_example", 9, timeout=20, interval=5, max_requests=4, fetch=fetch)
        self.assertEqual(len(calls), 1)

    def test_transient_read_backoff_is_bounded(self):
        clock = [0.0]
        sleeps = []
        def fetch(*a, **k):
            raise SafeError("http_503")
        def sleep(seconds):
            sleeps.append(seconds)
            clock[0] += seconds
        result = poll("unused", "not-real", "frm_example", 9, timeout=100, interval=2, max_requests=3,
                      fetch=fetch, clock=lambda: clock[0], sleep=sleep)
        self.assertEqual(result["requests"], 3)
        self.assertEqual(sleeps, [4, 8])


class PreviewTests(unittest.TestCase):
    origin = "https://api.pane.ink"
    url = "https://api.pane.ink/render-jobs/job_example/preview.png?access=TEST_PRIVATE_LINK"

    def test_url_origin_path_query_checks(self):
        self.assertEqual(preview_url(self.url, self.origin), self.url)
        for value in (
            self.url.replace("api.pane.ink", "evil.invalid"),
            self.url.replace("https", "http"),
            self.url.replace("api.pane.ink", "api.pane.ink@evil.invalid"),
            self.url.replace("job_example", "..%2Fprivate"), self.url + "&other=1", self.url + "#fragment",
            self.url.replace("?access=", "?token="), self.url.split("?")[0], self.url + "&access=another",
        ):
            with self.subTest(value=value), self.assertRaises(SafeError):
                preview_url(value, self.origin)

    def test_reject_non_png(self):
        with self.assertRaises(SafeError):
            png_image(b"not an image")
        data = io.BytesIO()
        Image.new("RGB", (5, 5)).save(data, "JPEG")
        with self.assertRaises(SafeError):
            png_image(data.getvalue())

    def test_reject_oversized_decoded_image(self):
        data = io.BytesIO()
        Image.new("1", (3000, 3000)).save(data, "PNG")
        with self.assertRaises(SafeError):
            png_image(data.getvalue())

    def test_bundle_originals_manifest_permissions(self):
        data = png()
        requests = []
        def fetch(url, **kwargs):
            requests.append(kwargs)
            return data
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "bundle"
            result = bundle([{"preview_png_url": self.url}] * 2, out, self.origin, fetch)
            self.assertEqual(result["saved"], 2)
            self.assertEqual((out / "preview-01.png").read_bytes(), data)
            manifest = (out / "manifest.json").read_text()
            self.assertNotIn("TEST_PRIVATE_LINK", manifest)
            self.assertNotIn("preview_png_url", manifest)
            self.assertTrue(json.loads(manifest)["complete"])
            self.assertFalse(any("token" in r for r in requests))
            if os.name == "posix":
                self.assertEqual(out.stat().st_mode & 0o777, 0o700)
                self.assertEqual((out / "preview-01.png").stat().st_mode & 0o777, 0o600)
            with Image.open(out / "contact-sheet.png") as im:
                self.assertEqual(im.size, (960, 260))

    def test_no_overwrite_or_large_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            with self.assertRaises(SafeError):
                bundle({"preview_png_url": self.url}, out, self.origin, lambda *a, **k: png())
            with self.assertRaises(SafeError):
                bundle([{}] * 13, out / "unused", self.origin)
            self.assertFalse((out / "unused").exists())


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                cls.requests.append((self.path, self.headers.get("Authorization")))
                if self.path.startswith("/redirect"):
                    self.send_response(302)
                    self.send_header("Location", "/leak")
                    self.end_headers()
                    return
                if self.path.startswith("/denied"):
                    self.send_response(401)
                    self.end_headers()
                    self.wfile.write(b"PRIVATE_SERVER_RESPONSE")
                    return
                if self.path.startswith("/limited"):
                    self.send_response(429)
                    self.send_header("Retry-After", "45")
                    self.end_headers()
                    self.wfile.write(b"PRIVATE_SERVER_RESPONSE")
                    return
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps(status()).encode() if self.path.endswith("/status") else png())
            def log_message(self, *args):
                pass
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.origin = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_http_localhost_opt_in(self):
        with self.assertRaises(SafeError):
            api_origin(self.origin)
        self.assertEqual(api_origin(self.origin, True), self.origin)
        for value in ("http://example.com", "https://user:pass@example.com", "https://example.com/a", "https://example.com?x=1"):
            with self.assertRaises(SafeError):
                api_origin(value, True)

    def test_redirect_no_key_forwarding(self):
        self.requests.clear()
        with self.assertRaisesRegex(SafeError, "http_302"):
            get_bytes(self.origin + "/redirect?access=PRIVATE_LINK", token="TEST_ONLY_KEY")
        self.assertEqual(len(self.requests), 1)
        self.assertFalse(any(p == "/leak" for p, _ in self.requests))

    def test_response_byte_limit(self):
        with self.assertRaisesRegex(SafeError, "response_too_large"):
            get_bytes(self.origin + "/image", limit=10)

    def test_wait_cli_real_http_and_no_secret_stdout(self):
        env = {**os.environ, "PANE_API_KEY": "TEST_ONLY_KEY"}
        result = subprocess.run([sys.executable, str(SKILL / "scripts/wait_for_display.py"),
                                 "--api-base", self.origin, "--allow-http-localhost", "--display-id", "example",
                                 "--frame-id", "frm_example", "--publication-version", "9"],
                                env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["state"], "device_reported_displayed")
        self.assertNotIn("TEST_ONLY_KEY", result.stdout + result.stderr)

    def test_preview_cli_real_http_no_auth_header(self):
        self.requests.clear()
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            (p / "response.json").write_text(json.dumps({"preview_png_url": self.origin + "/frames/frm_example/preview.png?access=TEST_LINK"}))
            result = subprocess.run([sys.executable, str(SKILL / "scripts/preview_bundle.py"), str(p / "response.json"),
                                     "--api-base", self.origin, "--allow-http-localhost", "--out", str(p / "out")],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(all(auth is None for _, auth in self.requests))
            self.assertNotIn("TEST_LINK", result.stdout + result.stderr)

    def test_error_message_has_no_body_or_secret_url(self):
        with self.assertRaises(SafeError) as caught:
            get_bytes(self.origin + "/denied?access=PRIVATE_LINK", token="TEST_ONLY_KEY")
        self.assertEqual(str(caught.exception), "http_401")

    def test_retry_after_parsed_without_exposing_response(self):
        with self.assertRaises(SafeError) as caught:
            get_bytes(self.origin + "/limited?access=PRIVATE_LINK", token="TEST_ONLY_KEY")
        self.assertEqual(str(caught.exception), "http_429")
        self.assertEqual(caught.exception.retry_after, 45)


class PackageTests(unittest.TestCase):
    def test_installed_skill_carries_license(self):
        self.assertEqual((ROOT / "LICENSE").read_bytes(), (SKILL / "LICENSE").read_bytes())

    def test_frontmatter_ui_metadata(self):
        text = (SKILL / "SKILL.md").read_text()
        meta = yaml.safe_load(text.split("---", 2)[1])
        self.assertEqual(meta["name"], SKILL.name)
        self.assertTrue(1 <= len(meta["description"]) <= 1024)
        self.assertLess(len(text.splitlines()), 150)
        ui = yaml.safe_load((SKILL / "agents/openai.yaml").read_text())
        self.assertIn("$pane-displays", ui["interface"]["default_prompt"])
        self.assertTrue(25 <= len(ui["interface"]["short_description"]) <= 64)

    def test_internal_markdown_links_resolve(self):
        for path in ROOT.rglob("*.md"):
            if ".venv" in path.parts:
                continue
            for target in re.findall(r"\]\(([^)]+)\)", path.read_text()):
                if target.startswith(("https://", "http://", "#")):
                    continue
                resolved = (path.parent / target.split("#", 1)[0]).resolve()
                self.assertTrue(resolved.is_relative_to(ROOT), (path, target))
                self.assertTrue(resolved.exists(), (path, target))

    def test_schema_provenance_hashes(self):
        meta = read_json(SKILL / "schemas/provenance.json")
        for item in meta["files"]:
            raw = (SKILL / "schemas" / item["file"]).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), item["sha256"])

    def test_script_help(self):
        for name in ("validate_payload.py", "wait_for_display.py", "preview_bundle.py", "webhook_receiver.py"):
            result = subprocess.run([sys.executable, str(SKILL / "scripts" / name), "--help"],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("usage:", result.stdout)

    def test_installed_skill_is_self_contained(self):
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / "pane-displays"
            shutil.copytree(SKILL, dest, ignore=shutil.ignore_patterns("__pycache__"))
            result = subprocess.run([sys.executable, str(dest / "scripts/validate_payload.py"),
                                     str(dest / "examples/main-summary.json"), "--strict"],
                                    cwd=directory, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_validation_error_redaction_cli(self):
        data = example()
        data["cards"][1]["data"]["body"] = {"PRIVATE_CONTENT": "PRIVATE_CONTENT"}
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "payload.json"
            p.write_text(json.dumps(data))
            result = subprocess.run([sys.executable, str(SKILL / "scripts/validate_payload.py"), str(p)],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn("PRIVATE_CONTENT", result.stdout + result.stderr)
            self.assertFalse(json.loads(result.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
