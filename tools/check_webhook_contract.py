"""Compare synthetic voice fixtures with selected real Pane payload/signing functions.

Uses an explicit trusted application checkout. Extracts only pure function ASTs;
no application imports, production database/credentials, external network or production writes.
The HTTP boundary check uses only an ephemeral loopback receiver with synthetic data.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import asyncio
import http.client
import tempfile
import threading
import time
from types import SimpleNamespace
import ast
import hashlib
import hmac
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills/pane-displays'
sys.path.insert(0, str(SKILL / 'scripts'))
from webhook_receiver import Inbox, VALIDATOR, make_server, signature


def pure_functions(path: Path, names: set[str]) -> dict:
    tree = ast.parse(path.read_text())
    nodes = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name in names]
    if {node.name for node in nodes} != names or len(nodes) != len(names):
        raise ValueError('Expected contract functions missing or ambiguous')
    namespace = {'Any': Any, 'hashlib': hashlib, 'hmac': hmac, 'json': json}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace


def check(app: Path) -> None:
    services = app / 'api_server/app/services'
    expected = json.loads((SKILL / 'examples/audio/audio-transcribed.json').read_text())
    payloads = pure_functions(services / 'audio_service.py', {'_webhook_payload'})
    data = dict(expected, _id=expected['audio_event_id'], created_at=datetime.fromisoformat(expected['created_at']))
    display = {'label': expected['display_label'], 'hardware_uid': expected['hardware_uid'], 'location': expected['location']}
    actual = payloads['_webhook_payload'](None, data, {'name': expected['group_name']}, display)
    crypto = pure_functions(services / 'webhook_delivery_service.py', {'signature_v2', 'verify_signature_v2', 'payload_bytes'})
    raw = crypto['payload_bytes'](actual)
    wire = json.loads(raw)
    if wire != expected or set(wire) != set(VALIDATOR.schema['properties']) or not VALIDATOR.is_valid(wire):
        raise ValueError('Audio event envelope/schema drift')
    secret, delivery, stamp = 'synthetic-contract-secret', 'del_example', '1792663200'
    supplied = signature(secret, stamp, delivery, raw)
    if supplied != crypto['signature_v2'](secret, stamp, delivery, raw):
        raise ValueError('Signature wire contract drift')
    for delta, valid in [(0, True), (300, True), (301, False), (-30, True), (-31, False)]:
        if crypto['verify_signature_v2'](secret, stamp, delivery, raw, supplied, now=int(stamp)+delta) != valid:
            raise ValueError('Signature clock window drift')
    if crypto['verify_signature_v2'](secret, stamp, delivery, raw+b' ', supplied, now=int(stamp)):
        raise ValueError('Raw-body tamper accepted')
    # Exercise the maintained sender's actual post() method, including HTTP
    # headers, against the standalone receiver. Only safe_request is replaced;
    # the transport below is restricted to our own ephemeral loopback listener.
    tree = ast.parse((services / 'webhook_delivery_service.py').read_text())
    nodes = [node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef) and node.name == 'post']
    if len(nodes) != 1:
        raise ValueError('Expected one actual sender post method')
    captured = {}
    async def capture(method, url, **kwargs):
        captured.update(method=method, url=url, **kwargs)
        return SimpleNamespace(status_code=202)
    namespace = dict(crypto, Any=Any, httpx=SimpleNamespace(Response=object),
                     utcnow=lambda: datetime.now(timezone.utc), safe_request=capture,
                     get_settings=lambda: SimpleNamespace(webhook_request_timeout_sec=10))
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<maintained sender post>', 'exec'), namespace)
    with tempfile.TemporaryDirectory(prefix='pane-wire-contract-') as directory:
        inbox = Inbox(Path(directory) / 'inbox.sqlite')
        server = make_server(inbox, secret=secret, group=expected['project_id'],
                             displays=frozenset({expected['display_id']}), port=0)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        thread.start()
        try:
            target = {'url': 'http://127.0.0.1:%s/webhooks/pane' % server.server_port, 'secret': secret}
            def wire(event, delivery_id):
                asyncio.run(namespace['post'](None, target, event, delivery_id))
                if captured['method'] != 'POST' or captured['url'] != target['url']:
                    raise ValueError('Unexpected sender destination')
                return dict(captured['headers']), captured['content']
            def send(headers, body, extra=()):
                connection = http.client.HTTPConnection(*server.server_address, timeout=3)
                try:
                    connection.putrequest('POST', '/webhooks/pane')
                    for name, value in [*headers.items(), *extra, ('Content-Length', str(len(body)))]:
                        connection.putheader(name, value)
                    connection.endheaders(body)
                    response = connection.getresponse()
                    return response.status, json.loads(response.read())
                finally:
                    connection.close()
            h, raw = wire(actual, 'del_real_sender')
            assert send(h, raw) == (202, {'status': 'accepted'})
            assert send(h, raw) == (202, {'status': 'duplicate'})
            assert send(h, raw+b' ')[0] == 401
            assert send(h, raw, [('X-Pane-Signature-V2', h['X-Pane-Signature-V2'])])[0] == 400
            assert send(h, raw, [('X-Pane-Event', 'webhook.test')])[0] == 400
            assert send(h, raw, [('X-Tablo-Event', 'audio.transcribed')])[0] == 400
            expired = dict(h)
            expired['X-Pane-Timestamp'] = str(int(time.time())-301)
            expired['X-Pane-Signature-V2'] = signature(secret, expired['X-Pane-Timestamp'], 'del_real_sender', raw)
            assert send(expired, raw)[0] == 401
            for change, code in [({'project_id': 'other'}, 403),
                                 ({'screen_id': 'other', 'display_id': 'other'}, 403)]:
                headers, body = wire(dict(actual, **change), 'del_wrong_source')
                assert send(headers, body)[0] == code
            test = json.loads((SKILL / 'examples/audio/webhook-test.json').read_text())
            headers, body = wire(test, 'del_actual_test')
            assert send(headers, body) == (200, {'status': 'test_verified'})
            assert inbox.counts() == {'pending': 1}, 'Test/rejected/duplicate events must not enqueue work'
        finally:
            server.shutdown(); server.server_close(); thread.join(3)
    print('Webhook contract matches: actual sender HTTP -> receiver, 202/dedup/test, headers, tamper, clock and source bounds')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-repo', type=Path, required=True)
    args = parser.parse_args()
    check(args.app_repo.resolve())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
