from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/pane-displays"
sys.path.insert(0, str(SKILL / "scripts"))
sys.path.insert(0, str(ROOT / "tools"))
from export_compact import SOURCE, compact_skill, export
from check_application import differences
from export_package import export as export_package, package_files
from pane_common import SafeError, retry_after_seconds
from validate_payload import validate
from wait_for_display import poll


def example(name: str = "main-summary.json") -> dict:
    return json.loads((SKILL / "examples" / name).read_text())


class CurrentContractTests(unittest.TestCase):
    def test_examples_against_public_api_and_mcp_contract(self):
        snapshot = json.loads((ROOT / "tests/fixtures/public-contract.json").read_text())["contract"]
        tools = {"render-mcp": "render_display_content", "preview-mcp": "preview_display_content",
                 "notify-mcp": "send_temporary_notification"}
        cases = json.loads((ROOT / "tests/example-cases.json").read_text())
        self.assertEqual(set(cases), {p.name for p in (SKILL / "examples").glob("*.json")})
        for name, kind in cases.items():
            with self.subTest(name=name):
                payload = example(name)
                if kind == "multi-display":
                    for render in payload["renders"]:
                        Draft202012Validator(snapshot["mcp"]["render_display_content"]).validate(render)
                elif kind in tools:
                    Draft202012Validator(snapshot["mcp"][tools[kind]]).validate(payload)
                else:
                    model = "NotifyRequest" if kind == "notify-rest" else "RenderRequest"
                    schema = {"$ref": f"#/components/schemas/{model}", "components": snapshot["components"]}
                    Draft202012Validator(schema).validate(payload)

    def test_write_options_supported_for_all_write_kinds(self):
        for name, kind in [("main-summary.json", "render-mcp"), ("main-rest.json", "render-rest"),
                           ("notification.json", "notify-mcp"), ("notification-rest.json", "notify-rest")]:
            for version in (0, 12, 2**63 - 1):
                with self.subTest(kind=kind, version=version):
                    data = example(name)
                    data.update(idempotency_key="a.B_9:-", expected_publication_version=version)
                    self.assertTrue(validate(data, kind, SKILL / "schemas")["ok"])

    def test_invalid_key_and_strict_version_rejected(self):
        invalid = {"idempotency_key": ["", "x" * 129, "a b", "lietuviškas", "key\n", 1, None],
                   "expected_publication_version": [-1, True, 1.0, "1", 2**63, None]}
        for field, values in invalid.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    data = example()
                    data[field] = value
                    self.assertFalse(validate(data, "render-mcp", SKILL / "schemas")["ok"])

    def test_preview_rejects_publication_options(self):
        data = example("preview.json")
        for field, value in [("idempotency_key", "new-key"), ("expected_publication_version", 12)]:
            self.assertFalse(validate({**data, field: value}, "preview-mcp", SKILL / "schemas")["ok"])

    def test_nested_agenda_typo_is_an_error_without_strict_mode(self):
        data = example()
        data["cards"][0]["data"]["entries"][0]["PRIVATE_TYPO"] = "PRIVATE_VALUE"
        result = validate(data, "render-mcp", SKILL / "schemas")
        self.assertFalse(result["ok"])
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_revision_preserves_unrelated_cards_and_changes_only_note(self):
        before, after = example(), example("revision-main.json")
        self.assertEqual(before["cards"][0], after["cards"][0])
        old_note, new_note = copy.deepcopy(before["cards"][1]), copy.deepcopy(after["cards"][1])
        self.assertNotEqual(old_note["data"].pop("body"), new_note["data"].pop("body"))
        self.assertEqual(old_note, new_note)
        self.assertIn("expected_publication_version", after)
        self.assertNotEqual(before["idempotency_key"], after["idempotency_key"])

    def test_recovery_and_content_read_tools_require_their_identifiers(self):
        contract = json.loads((ROOT / "tests/fixtures/public-contract.json").read_text())["contract"]
        for name, field in [("get_publication_operation", "operation_id"), ("get_frame_content", "frame_id")]:
            validator = Draft202012Validator(contract["mcp"][name])
            validator.validate({"display_id": "EXAMPLE", field: "example_id"})
            self.assertTrue(list(validator.iter_errors({"display_id": "EXAMPLE"})))


class CompactExportTests(unittest.TestCase):
    def test_shared_instructions_and_standalone_links(self):
        original = SOURCE.read_text()
        compact = compact_skill(original)
        self.assertIn("\nname: pane\n", compact)
        self.assertNotIn("references/", compact)
        common = original.split("\n<!-- package-references -->\n")[0].rstrip()
        self.assertTrue(compact.startswith(common.replace("\nname: pane-displays\n", "\nname: pane\n")))

    def test_export_is_deterministic_and_check_never_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "SKILL.md"
            self.assertFalse(export(out, check=True))
            self.assertFalse(out.exists())
            export(out, check=False)
            first = out.read_bytes()
            export(out, check=False)
            self.assertEqual(first, out.read_bytes())
            self.assertTrue(export(out, check=True))
            out.write_text("different")
            self.assertFalse(export(out, check=True))
            self.assertEqual(out.read_text(), "different")

    def test_full_export_is_self_contained_and_check_does_not_write(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "pane-displays"
            self.assertFalse(export_package(target, check=True))
            self.assertFalse(target.exists())
            export_package(target, check=False)
            self.assertEqual(package_files(target), package_files())
            self.assertTrue(export_package(target, check=True))
            (target / "SKILL.md").write_text("drift")
            self.assertFalse(export_package(target, check=True))
            self.assertEqual((target / "SKILL.md").read_text(), "drift")

    def test_broken_local_link_or_missing_boundary_rejected(self):
        original = SOURCE.read_text()
        for text in [original.replace("<!-- package-references -->", ""),
                     original.replace("# Pane displays", "# Pane displays\n[private](references/private.md)")]:
            with self.assertRaises(ValueError):
                compact_skill(text)

    def test_application_drift_check_detects_each_boundary(self):
        contract = json.loads((ROOT / "tests/fixtures/public-contract.json").read_text())["contract"]
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory)
            public = app / "admin_dashboard/public/pane/docs"
            schema_dir = app / "api_server/app/schemas-json/card-data"
            compact = app / "docs/agent-skill/pane/SKILL.md"
            for folder in (public, schema_dir, compact.parent):
                folder.mkdir(parents=True)
            compact.write_text(compact_skill(SOURCE.read_text()))
            full = app / "docs/agent-skill/pane-displays"
            export_package(full, check=False)
            for path in (SKILL / "schemas").glob("*.schema.json"):
                (schema_dir / path.name).write_bytes(path.read_bytes())
            mcp = {"tools": [{"name": name, "inputSchema": schema} for name, schema in contract["mcp"].items()]}
            (public / "mcp-tools.json").write_text(json.dumps(mcp))
            (public / "openapi.json").write_text(json.dumps({"components": contract["components"]}))
            self.assertEqual(differences(app), [])
            (full / "scripts/webhook_receiver.py").write_text("drift")
            self.assertIn("full skill package", differences(app))
            compact.write_text("drift")
            self.assertIn("compact skill", differences(app))
            (schema_dir / "text.block.schema.json").write_text("{}")
            self.assertIn("text.block.schema.json", differences(app))
            mcp["tools"][0]["inputSchema"]["properties"]["unexpected_argument"] = {"type": "string"}
            (public / "mcp-tools.json").write_text(json.dumps(mcp))
            self.assertIn("public API/MCP contract snapshot", differences(app))


class RetryAfterTests(unittest.TestCase):
    def test_seconds_dates_and_invalid_headers(self):
        self.assertEqual(retry_after_seconds("45"), 45)
        self.assertEqual(retry_after_seconds("Thu, 01 Jan 1970 00:01:00 GMT", now=10), 50)
        for value in [None, "", "-1", "1.5", "malformed", "x" * 129]:
            self.assertIsNone(retry_after_seconds(value))

    def test_server_delay_exhausts_budget_without_an_early_retry(self):
        now = [0.0]
        calls = []

        def fetch(*args, **kwargs):
            calls.append(1)
            raise SafeError("http_429", retry_after=45)

        result = poll("https://example.invalid", "fake", "frm_example", 1,
                      timeout=20, interval=5, max_requests=10, fetch=fetch,
                      clock=lambda: now[0], sleep=lambda delay: now.__setitem__(0, now[0] + delay))
        self.assertEqual(len(calls), 1)
        self.assertEqual(now[0], 20)
        self.assertEqual(result["state"], "unconfirmed_budget_exhausted")


class PublicGuidanceTests(unittest.TestCase):
    def test_agent_references_exclude_owner_and_firmware_protocols(self):
        skill = ROOT / "skills/pane-displays"
        for path in skill.rglob("*.md"):
            text = path.read_text()
            for private in ["https://api.pane.ink/openapi.json", "/device/register", "/devices/{",
                            "/projects/{project_id}/webhooks", "/auth/login"]:
                self.assertNotIn(private, text, str(path))
        connection = (skill / "references/connection.md").read_text()
        self.assertIn("https://pane.ink/pane/docs/openapi.json", connection)
        self.assertIn("GET /registry/cards/{card_type}/schema", connection)
