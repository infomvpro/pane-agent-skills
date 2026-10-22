"""Opt-in Pane v2 receiver and durable, bounded worker (Unix, local SQLite).

Serve behind a trusted HTTPS reverse proxy. No public bind, OAuth, registration,
model invocation or publication is implicit. See references/audio-webhooks.md.
"""
from __future__ import annotations

import argparse
import contextlib
from datetime import datetime
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import signal
import sqlite3
import stat
import subprocess
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Iterator

from jsonschema import Draft202012Validator
from pane_common import SafeError, decode_json

MAX_BODY = 256 * 1024
ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z", re.ASCII)
SCHEMA = Path(__file__).resolve().parents[1] / "schemas/events/audio-transcribed.schema.json"
VALIDATOR = Draft202012Validator(json.loads(SCHEMA.read_text()))


class Rejected(Exception):
    def __init__(self, status: int, code: str):
        self.status, self.code = status, code


def signature(secret: str, timestamp: str, delivery: str, raw: bytes) -> str:
    message = b"v2." + timestamp.encode("ascii") + b"." + delivery.encode("ascii") + b"." + raw
    return "v2=" + hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def one_header(headers, name: str) -> str:
    values = headers.get_all(name, [])
    if len(values) != 1:
        raise Rejected(400, "invalid_headers")
    return values[0]


def verified_event(headers, raw: bytes, secret: str, group: str,
                   displays: frozenset[str], *, now: int) -> tuple[str, dict]:
    version = one_header(headers, "X-Tablo-Signature-Version")
    timestamp = one_header(headers, "X-Tablo-Timestamp")
    delivery = one_header(headers, "X-Tablo-Delivery")
    supplied = one_header(headers, "X-Tablo-Signature-V2")
    event_name = one_header(headers, "X-Tablo-Event")
    if (version != "2" or not re.fullmatch(r"[0-9]{1,12}", timestamp)
            or not ID.fullmatch(delivery) or not re.fullmatch(r"v2=[0-9a-f]{64}", supplied)):
        raise Rejected(401, "invalid_signature")
    if not now - 300 <= int(timestamp) <= now + 30:
        raise Rejected(401, "expired_signature")
    if not hmac.compare_digest(signature(secret, timestamp, delivery, raw), supplied):
        raise Rejected(401, "invalid_signature")
    try:
        event = decode_json(raw)
    except (SafeError, RecursionError):
        raise Rejected(400, "invalid_json") from None
    if not isinstance(event, dict) or event.get("event") != event_name:
        raise Rejected(400, "invalid_event")
    if event.get("project_id") != group:
        raise Rejected(403, "wrong_group")
    if event_name == "webhook.test":
        if event.get("test") is not True or not isinstance(event.get("event_id"), str) or not ID.fullmatch(event["event_id"]):
            raise Rejected(400, "invalid_test")
        return delivery, event  # Deliberately no queue or agent work.
    if event_name != "audio.transcribed":
        raise Rejected(400, "unsupported_event")
    try:
        valid = VALIDATOR.is_valid(event)
        if valid:
            valid = all(ID.fullmatch(event[key]) for key in ("audio_event_id", "audio_session_id", "project_id", "group_id", "screen_id", "display_id"))
        if valid:
            created = datetime.fromisoformat(event["created_at"].replace("Z", "+00:00"))
            valid = created.tzinfo is not None
    except (RecursionError, ValueError):
        valid = False
    if (not valid or event["group_id"] != group or event["screen_id"] != event["display_id"]
            or not event["transcript"].strip()):
        raise Rejected(400, "invalid_event")
    if event["display_id"] not in displays:
        raise Rejected(403, "wrong_display")
    if event.get("legacy_auto_render_requested"):
        raise Rejected(409, "legacy_publisher_enabled")
    return delivery, event


def private_path(path: Path) -> Path:
    """Require an owner-only directory; never chmod an existing shared folder."""
    path = path.absolute()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    parent = path.parent.stat()
    if path.parent.is_symlink() or parent.st_uid != os.getuid() or stat.S_IMODE(parent.st_mode) & 0o077:
        raise SafeError("use_owner_only_data_directory")
    flags = os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise SafeError("use_owner_only_regular_file")
    finally:
        os.close(fd)
    return path


class Inbox:
    def __init__(self, path: Path):
        self.path = private_path(path)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS binding (id INTEGER PRIMARY KEY CHECK(id=1), scope TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY, digest TEXT NOT NULL, body BLOB,
                    state TEXT NOT NULL CHECK(state IN ('pending','processing','done','needs_review')),
                    received REAL NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS deliveries (
                    id TEXT PRIMARY KEY, event_id TEXT NOT NULL, digest TEXT NOT NULL);
            ''')

    @contextlib.contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=3)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def bind(self, group: str, displays: frozenset[str]) -> None:
        scope = json.dumps([group, sorted(displays)])
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT scope FROM binding WHERE id=1").fetchone()
            if row and row[0] != scope:
                raise SafeError("inbox_scope_changed_use_separate_inbox")
            db.execute("INSERT OR IGNORE INTO binding VALUES (1, ?)", (scope,))

    def accept(self, delivery: str, event: dict, raw: bytes) -> bool:
        digest = hashlib.sha256(raw).hexdigest()
        event_id, now = event["audio_event_id"], time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT event_id,digest FROM deliveries WHERE id=?", (delivery,)).fetchone()
            previous = db.execute("SELECT digest FROM events WHERE id=?", (event_id,)).fetchone()
            if ((prior and (prior[0] != event_id or prior[1] != digest))
                    or (previous and previous[0] != digest)):
                raise Rejected(409, "identity_conflict")
            db.execute("INSERT OR IGNORE INTO events VALUES (?,?,?,'pending',?,?)",
                       (event_id, digest, raw, now, now))
            db.execute("INSERT OR IGNORE INTO deliveries VALUES (?,?,?)", (delivery, event_id, digest))
        return previous is not None  # Commit has completed before HTTP 202.

    def counts(self) -> dict[str, int]:
        with self.connect() as db:
            return {row[0]: row[1] for row in db.execute("SELECT state,count(*) FROM events GROUP BY state")}

    @contextlib.contextmanager
    def worker_lock(self) -> Iterator[None]:
        path = private_path(self.path.with_suffix(".worker.lock"))
        with path.open("r+") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SafeError("worker_already_running") from None
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def recover(self) -> None:
        # Only under worker_lock. Ambiguous external effects are never auto-replayed.
        with self.connect() as db:
            db.execute("UPDATE events SET state='needs_review',updated=? WHERE state='processing'", (time.time(),))

    def retry(self, event_id: str) -> None:
        with self.worker_lock():
            self.recover()
            with self.connect() as db:
                result = db.execute("UPDATE events SET state='pending',updated=? WHERE id=? AND state='needs_review' AND body IS NOT NULL",
                                    (time.time(), event_id))
                if result.rowcount != 1:
                    raise SafeError("event_not_retryable")

    def purge_completed(self) -> int:
        # Retain IDs and hashes for late retries; remove transcripts from completed jobs.
        with self.connect() as db:
            db.execute("PRAGMA secure_delete=ON")
            result = db.execute("UPDATE events SET body=NULL WHERE state='done' AND body IS NOT NULL")
            return result.rowcount


def run_worker(inbox: Inbox, handler: Path, *, limit: int, timeout: float) -> dict[str, int]:
    if not handler.is_absolute() or not handler.is_file() or not os.access(handler, os.X_OK):
        raise SafeError("handler_must_be_absolute_executable")
    if not 1 <= limit <= 100 or not 0 < timeout <= 300:
        raise SafeError("invalid_worker_limits")
    result = {"done": 0, "needs_review": 0}
    with inbox.worker_lock():
        inbox.recover()
        for _ in range(limit):
            with inbox.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT id,body FROM events WHERE state='pending' ORDER BY received,id LIMIT 1").fetchone()
                if not row:
                    break
                db.execute("UPDATE events SET state='processing',updated=? WHERE id=?", (time.time(), row[0]))
            state = "needs_review"
            # Fixed executable, JSON on stdin; no event-derived commands or inherited secrets.
            child_env = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "TZ", "HOME") if key in os.environ}
            process = None
            try:
                process = subprocess.Popen([str(handler)], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL, env=child_env, start_new_session=True)
                process.communicate(row[1], timeout=timeout)
                if process.returncode == 0:
                    state = "done"
            except (OSError, subprocess.TimeoutExpired):
                pass
            finally:
                if process is not None:
                    # A handler must finish or durably enqueue, never leave unmanaged children.
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
            with inbox.connect() as db:
                db.execute("UPDATE events SET state=?,updated=? WHERE id=?", (state, time.time(), row[0]))
            result[state] += 1
    return result


def make_server(inbox: Inbox, *, secret: str, group: str, displays: frozenset[str], port: int = 8765) -> HTTPServer:
    if not 16 <= len(secret) <= 512 or not ID.fullmatch(group) or not displays or any(not ID.fullmatch(d) for d in displays):
        raise SafeError("invalid_receiver_configuration")
    inbox.bind(group, displays)

    class Handler(BaseHTTPRequestHandler):
        server_version = "PaneReceiver"
        sys_version = ""

        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, *args):
            pass  # Request paths, bodies and signature headers never enter logs.

        def reply(self, status: int, code: str):
            body = json.dumps({"status": code}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            if status == 503:
                self.send_header("Retry-After", "5")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            try:
                if self.path != "/webhooks/pane":
                    raise Rejected(404, "not_found")
                if self.headers.get_all("Transfer-Encoding") or self.headers.get_all("Content-Encoding"):
                    raise Rejected(400, "unsupported_encoding")
                length = one_header(self.headers, "Content-Length")
                if not re.fullmatch(r"[0-9]{1,7}", length) or not 0 < int(length) <= MAX_BODY:
                    raise Rejected(413, "body_limit")
                if one_header(self.headers, "Content-Type").split(";")[0].strip().lower() != "application/json":
                    raise Rejected(415, "json_required")
                raw = self.rfile.read(int(length))
                if len(raw) != int(length):
                    raise Rejected(400, "incomplete_body")
                delivery, event = verified_event(self.headers, raw, secret, group, displays, now=int(time.time()))
                if event["event"] == "webhook.test":
                    self.reply(200, "test_verified")
                else:
                    duplicate = inbox.accept(delivery, event, raw)
                    self.reply(202, "duplicate" if duplicate else "accepted")
            except Rejected as error:
                self.reply(error.status, error.code)
            except (TimeoutError, ConnectionError):
                self.close_connection = True
            except (OSError, sqlite3.Error):
                self.reply(503, "storage_unavailable")

    return HTTPServer(("127.0.0.1", port), Handler)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path, help="SQLite file in an owner-only local directory")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--group-id", required=True)
    serve.add_argument("--display-id", action="append", required=True)
    serve.add_argument("--port", type=int, default=8765)
    work = commands.add_parser("work")
    work.add_argument("--handler", required=True, type=Path)
    work.add_argument("--limit", type=int, default=10)
    work.add_argument("--timeout", type=float, default=120)
    commands.add_parser("status")
    commands.add_parser("purge-completed")
    retry = commands.add_parser("retry")
    retry.add_argument("--event-id", required=True)
    args = parser.parse_args()
    try:
        inbox = Inbox(args.db)
        if args.command == "serve":
            with make_server(inbox, secret=os.environ.get("PANE_WEBHOOK_SECRET", ""), group=args.group_id,
                             displays=frozenset(args.display_id), port=args.port) as server:
                print("Listening on loopback; HTTPS reverse proxy required", flush=True)
                server.serve_forever()
        elif args.command == "work":
            print(json.dumps(run_worker(inbox, args.handler, limit=args.limit, timeout=args.timeout)))
        elif args.command == "status":
            print(json.dumps(inbox.counts()))
        elif args.command == "retry":
            inbox.retry(args.event_id)
            print("Event queued after operator review")
        else:
            print(json.dumps({"purged_bodies": inbox.purge_completed()}))
        return 0
    except (SafeError, OSError, sqlite3.Error) as error:
        print(str(error) if isinstance(error, SafeError) else "Receiver operation failed; inspect local configuration/storage")
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
