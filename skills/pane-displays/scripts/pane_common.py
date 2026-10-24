"""Small, read-only HTTP/JSON primitives shared by the optional CLI helpers."""
from __future__ import annotations

import ipaddress
import json
import math
import re
import socket
import time
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

DEFAULT_API = "https://api.pane.ink"
JSON_LIMIT = 2 * 1024 * 1024


class SafeError(Exception):
    """Only predefined, non-sensitive messages may cross the CLI boundary."""

    def __init__(self, message: str, *, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


def retry_after_seconds(value: str | None, *, now: float | None = None) -> float | None:
    """Parse only the standard delay/date; never return raw response headers."""
    if not value or len(value) > 128:
        return None
    try:
        if re.fullmatch(r"[0-9]+", value):
            return float(value)
        date = parsedate_to_datetime(value)
        if date.tzinfo is None:
            return None
        return max(0, date.timestamp() - (time.time() if now is None else now))
    except (ValueError, TypeError, OverflowError):
        return None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> None:
        return None


def emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=True, allow_nan=False))


def decode_json(raw: bytes) -> Any:
    def reject_constant(value: str) -> None:
        raise ValueError("non-finite JSON number")

    def finite_float(value: str) -> float:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("non-finite JSON number")
        return number

    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    try:
        return json.loads(raw, parse_constant=reject_constant, parse_float=finite_float,
                          object_pairs_hook=unique_pairs)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise SafeError("invalid_json") from exc


def read_json(path: Path) -> Any:
    try:
        with path.open("rb") as handle:
            raw = handle.read(JSON_LIMIT + 1)
    except OSError as exc:
        raise SafeError("input_unreadable") from exc
    if len(raw) > JSON_LIMIT:
        raise SafeError("input_too_large")
    return decode_json(raw)


def identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise SafeError("invalid_identifier")
    return value


def api_origin(value: str, allow_http_localhost: bool = False) -> str:
    try:
        parsed = urlsplit(value)
        _ = parsed.port
        host = parsed.hostname
        loopback = host == "localhost"
        if host and not loopback:
            try:
                loopback = ipaddress.ip_address(host).is_loopback
            except ValueError:
                pass
        valid_scheme = parsed.scheme == "https" or (
            allow_http_localhost and parsed.scheme == "http" and loopback
        )
        if (not valid_scheme or not host or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path not in ("", "/")
                or any(c.isspace() for c in value)):
            raise ValueError("invalid origin")
        return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    except ValueError as exc:
        raise SafeError("invalid_api_origin") from exc


def get_bytes(url: str, *, token: str | None = None, timeout: float = 10,
              limit: int = JSON_LIMIT) -> bytes:
    headers = {"Accept": "application/json" if token else "image/png",
               "User-Agent": "pane-agent-skills/0.3.1"}
    if token is not None:
        if not token or any(c.isspace() for c in token):
            raise SafeError("invalid_api_key")
        headers["Authorization"] = "Bearer " + token
    # Do not forward keys or signed URLs to redirects or environment proxies.
    opener = build_opener(ProxyHandler({}), NoRedirect())
    deadline = time.monotonic() + timeout
    try:
        with opener.open(Request(url, headers=headers), timeout=timeout) as response:
            chunks: list[bytes] = []
            size = 0
            while True:
                if time.monotonic() >= deadline:
                    raise SafeError("request_timeout")
                chunk = response.read1(min(65536, limit + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > limit:
                    raise SafeError("response_too_large")
            return b"".join(chunks)
    except HTTPError as exc:
        # Never expose response bodies, headers, URLs or credentials.
        delay = retry_after_seconds(exc.headers.get("Retry-After")) if exc.headers else None
        exc.close()
        raise SafeError(f"http_{exc.code}", retry_after=delay) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise SafeError("request_timeout") from exc
    except (URLError, OSError, ValueError) as exc:
        raise SafeError("network_error") from exc


def run_cli(main: Any) -> None:
    try:
        raise SystemExit(main())
    except SafeError as exc:
        emit({"ok": False, "error": str(exc)})
        raise SystemExit(2) from None
    except KeyboardInterrupt:
        emit({"ok": False, "error": "cancelled"})
        raise SystemExit(130) from None
    except Exception:
        # Private JSON and signed URLs must not enter tracebacks in agent logs.
        emit({"ok": False, "error": "unexpected_error"})
        raise SystemExit(2) from None
