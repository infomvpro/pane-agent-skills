"""Compare synthetic voice fixtures with selected real Pane payload/signing functions.

Uses an explicit trusted application checkout. Extracts only pure function ASTs;
no application imports, database, credentials, network or production writes.
"""
from __future__ import annotations

import argparse
from datetime import datetime
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
from webhook_receiver import VALIDATOR, signature


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
    print('Webhook contract matches: actual payload, schema fields, raw-byte signature and time window')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-repo', type=Path, required=True)
    args = parser.parse_args()
    check(args.app_repo.resolve())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
