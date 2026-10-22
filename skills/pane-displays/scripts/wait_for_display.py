"""Bounded, read-only check for a device ACK of one exact current publication."""
from __future__ import annotations

import argparse
import os
import time
from datetime import datetime
from typing import Any

from pane_common import DEFAULT_API, SafeError, api_origin, decode_json, emit, get_bytes, identifier, run_cli


def timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result if result.tzinfo is not None else None
    except ValueError:
        return None


def classify(status: Any, frame_id: str, version: int) -> str:
    if not isinstance(status, dict):
        raise SafeError("invalid_status_response")
    current = status.get("current_frame")
    if not isinstance(current, dict):
        return "not_current"
    current_version = current.get("publication_version")
    if type(current_version) is not int or current_version < 1:
        return "unsupported_evidence"
    if current.get("frame_id") != frame_id or current_version != version:
        return "not_current"
    ack = status.get("current_frame_ack")
    if not isinstance(ack, dict):
        return "pending"
    published_at, ack_at = timestamp(current.get("published_at")), timestamp(ack.get("ack_at"))
    if not (ack.get("frame_id") == frame_id and ack.get("validated") is True
            and type(ack.get("publication_version")) is int and ack["publication_version"] == version
            and published_at and ack_at and ack_at >= published_at):
        return "pending"
    if ack.get("status") == "displayed":
        return "device_reported_displayed"
    if ack.get("status") in ("failed", "unsupported_frame", "render_failed"):
        return "device_reported_failure"
    return "pending"


def poll(url: str, token: str, frame_id: str, version: int, *, timeout: float,
         interval: float, max_requests: int, fetch: Any = get_bytes,
         clock: Any = time.monotonic, sleep: Any = time.sleep) -> dict[str, Any]:
    deadline = clock() + timeout
    state = "pending"
    requests = 0
    for attempt in range(1, max_requests + 1):
        remaining = deadline - clock()
        if remaining <= 0:
            break
        requests += 1
        retry_after = None
        try:
            status = decode_json(fetch(url, token=token, timeout=min(10, remaining)))
            state = classify(status, frame_id, version)
        except SafeError as exc:
            if str(exc) not in ("http_429", "http_502", "http_503", "http_504", "request_timeout", "network_error"):
                raise
            state = "read_unavailable"
            retry_after = exc.retry_after
        if state not in ("pending", "read_unavailable"):
            return {"ok": state == "device_reported_displayed", "state": state, "requests": requests}
        if attempt == max_requests:
            break
        remaining = deadline - clock()
        if remaining <= 0:
            break
        # Transient read failures back off; publication is never retried here.
        delay = min(30, interval * (2 ** min(attempt, 3))) if state == "read_unavailable" else interval
        if retry_after is not None:
            delay = max(delay, retry_after)
        sleep(min(delay, remaining))
    return {"ok": False, "state": "unconfirmed_budget_exhausted", "last_observation": state,
            "requests": requests}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--display-id", required=True)
    parser.add_argument("--frame-id", required=True)
    parser.add_argument("--publication-version", required=True, type=int)
    parser.add_argument("--timeout", type=float, default=120, help="Polling budget, 1–600 seconds.")
    parser.add_argument("--interval", type=float, default=5, help="2–60 seconds between successful reads.")
    parser.add_argument("--max-requests", type=int, default=24)
    parser.add_argument("--api-base", default=DEFAULT_API, help="Trusted API origin; keys are sent here.")
    parser.add_argument("--allow-http-localhost", action="store_true", help="Local tests only.")
    args = parser.parse_args()
    if not (1 <= args.timeout <= 600 and 2 <= args.interval <= 60
            and 1 <= args.max_requests <= 120 and args.publication_version >= 1):
        raise SafeError("invalid_poll_limits")
    origin = api_origin(args.api_base, args.allow_http_localhost)
    display_id, frame_id = identifier(args.display_id), identifier(args.frame_id)
    token = os.environ.get("PANE_API_KEY")
    if not token:
        raise SafeError("PANE_API_KEY_required")
    result = poll(f"{origin}/mcp/displays/{display_id}/status", token, frame_id,
                  args.publication_version, timeout=args.timeout, interval=args.interval,
                  max_requests=args.max_requests)
    emit(result)
    return 0 if result["ok"] else 3


if __name__ == "__main__":
    run_cli(main)
