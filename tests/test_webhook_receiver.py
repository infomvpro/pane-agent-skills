from __future__ import annotations

from email.message import Message
import hashlib
import hmac
import http.client
import json
import os
from pathlib import Path
import sqlite3
import subprocess
from concurrent.futures import ThreadPoolExecutor
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills/pane-displays'
sys.path.insert(0, str(SKILL / 'scripts'))
from pane_common import SafeError
from webhook_receiver import Inbox, MAX_BODY, Rejected, make_server, run_worker, verified_event

SECRET = 'synthetic-test-secret-never-use-live'
GROUP = 'grp_example_office'
DISPLAYS = frozenset({'disp_example_desk'})
NOW = 1792663200


def event():
    return json.loads((SKILL / 'examples/audio/audio-transcribed.json').read_text())


def body(value=None):
    return json.dumps(event() if value is None else value, separators=(',', ':')).encode()


def headers(raw, *, delivery='del_aud_example_001', timestamp=NOW, name='audio.transcribed'):
    message = Message()
    message['X-Pane-Signature-Version'] = '2'
    message['X-Pane-Timestamp'] = str(timestamp)
    message['X-Pane-Delivery'] = delivery
    message['X-Pane-Event'] = name
    signed = b'.'.join([b'v2', str(timestamp).encode(), delivery.encode(), raw])
    message['X-Pane-Signature-V2'] = 'v2=' + hmac.new(SECRET.encode(), signed, hashlib.sha256).hexdigest()
    message['Content-Type'] = 'application/json'
    message['Content-Length'] = str(len(raw))
    return message


class SignatureTests(unittest.TestCase):
    def verify(self, raw, h=None):
        return verified_event(h or headers(raw), raw, SECRET, GROUP, DISPLAYS, now=NOW)

    def test_legacy_and_mixed_headers_are_rejected(self):
        current = headers(body())
        legacy = Message()
        for name, value in current.items():
            legacy[name.replace('X-Pane-', 'X-Tablo-')] = value
        for candidate in [legacy, current]:
            if candidate is current:
                candidate['X-Tablo-Event'] = 'audio.transcribed'
            with self.assertRaises(Rejected) as failure:
                self.verify(body(), candidate)
            self.assertEqual(failure.exception.status, 400)

    def test_realistic_event_and_test_noop(self):
        self.assertEqual(self.verify(body())[1], event())
        data = json.loads((SKILL / 'examples/audio/webhook-test.json').read_text())
        self.assertEqual(self.verify(body(data), headers(body(data), name='webhook.test'))[1], data)

    def test_server_datetime_wire_and_rfc3339(self):
        for value in ['2026-10-22 10:00:00+00:00', '2026-10-22T10:00:00Z', '2026-10-22 10:00:00.123456+03:00']:
            data = event(); data['created_at'] = value
            self.assertEqual(self.verify(body(data))[1], data)
        for value in ['2026-10-22T10:00:00', '2026-02-30 10:00:00+00:00', 'yesterday']:
            data = event(); data['created_at'] = value
            with self.assertRaises(Rejected): self.verify(body(data))

    def test_no_legacy_fallback_and_duplicate_headers(self):
        for name in ['X-Pane-Signature-V2', 'X-Pane-Timestamp', 'X-Pane-Event', 'X-Pane-Delivery']:
            h = headers(body())
            h['X-Pane-Signature'] = 'irrelevant'
            del h[name]
            with self.assertRaises(Rejected): self.verify(body(), h)
            h = headers(body()); h[name] = h[name]
            with self.assertRaises(Rejected): self.verify(body(), h)

    def test_tampered_body_delivery_event_and_time(self):
        h = headers(body())
        with self.assertRaises(Rejected): self.verify(body() + b' ', h)
        for name, value in [('X-Pane-Delivery','del_other'), ('X-Pane-Event','webhook.test'),
                            ('X-Pane-Signature-Version','1'), ('X-Pane-Timestamp','bad')]:
            h = headers(body()); h.replace_header(name,value)
            with self.assertRaises(Rejected): self.verify(body(), h)
        for delta in [-301,31]:
            with self.assertRaises(Rejected): self.verify(body(), headers(body(),timestamp=NOW+delta))
        for delta in [-300,30]: self.verify(body(), headers(body(),timestamp=NOW+delta))

    def test_scope_alias_types_and_legacy(self):
        for field, value in [('project_id','grp_other'),('group_id','grp_other'),('display_id','disp_other'),
                             ('screen_id','disp_other'),('transcript',' '),('transcript',{}),
                             ('created_at','yesterday'),('duration_ms',True),('legacy_auto_render_requested',True)]:
            data=event(); data[field]=value
            with self.assertRaises(Rejected, msg=field): self.verify(body(data))
        data=event(); data['screen_id']=data['display_id']='disp_other'
        with self.assertRaises(Rejected) as error: self.verify(body(data))
        self.assertEqual(error.exception.status,403)

    def test_duplicate_json_nonfinite_and_unknown_additions(self):
        for raw in [b'{"event":1,"event":2}', b'{"x":NaN}', b'{"x":1e10000}', b'[]', b'{']:
            with self.assertRaises(Rejected): self.verify(raw)
        data=event(); data['future_field']={'note':'not an instruction'}
        self.assertEqual(self.verify(body(data))[1],data)


class InboxFixture(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'private/voice.sqlite'
        self.inbox=Inbox(self.path)

    def tearDown(self): self.temp.cleanup()

    def accept(self): self.inbox.accept('del_example',event(),body())

    def handler(self, code):
        path=Path(self.temp.name)/'handler'
        path.write_text('#!'+sys.executable+'\n'+code+'\n')
        path.chmod(0o700)
        return path


class InboxTests(InboxFixture):
    def test_restart_and_event_delivery_deduplication(self):
        self.accept()
        other=Inbox(self.path)
        self.assertTrue(other.accept('del_example',event(),body()))
        self.assertTrue(other.accept('del_new_attempt',event(),body()))
        self.assertEqual(other.counts(),{'pending':1})
        changed=event(); changed['transcript']='different'
        with self.assertRaises(Rejected): other.accept('del_example',changed,body(changed))
        with self.assertRaises(Rejected): other.accept('del_other',changed,body(changed))
        changed=event(); changed['audio_event_id']='aud_other'
        with self.assertRaises(Rejected): other.accept('del_example',changed,body(changed))

    def test_concurrent_duplicate_delivery_persists_once(self):
        with ThreadPoolExecutor(max_workers=6) as pool:
            duplicates = list(pool.map(lambda _: self.inbox.accept('del_concurrent', event(), body()), range(12)))
        self.assertEqual(duplicates.count(False), 1)
        self.assertEqual(self.inbox.counts(), {'pending': 1})

    def test_binding_cannot_change_and_permissions(self):
        self.inbox.bind(GROUP,DISPLAYS)
        self.inbox.bind(GROUP,DISPLAYS)
        with self.assertRaises(SafeError): self.inbox.bind('grp_other',DISPLAYS)
        self.assertEqual(self.path.stat().st_mode & 0o777,0o600)
        self.assertEqual(self.path.parent.stat().st_mode & 0o777,0o700)
        link=self.path.parent/'link.sqlite'; link.symlink_to(self.path)
        with self.assertRaises(OSError): Inbox(link)

    def test_handler_receives_exact_event_not_secrets_or_shell(self):
        self.accept()
        marker=Path(self.temp.name)/'received.json'
        code=f'import sys,os,pathlib\nassert "PANE_WEBHOOK_SECRET" not in os.environ\nassert "OWNER_TOKEN" not in os.environ\npathlib.Path({str(marker)!r}).write_bytes(sys.stdin.buffer.read())'
        with patch.dict(os.environ,{'PANE_WEBHOOK_SECRET':SECRET,'OWNER_TOKEN':'private'}):
            self.assertEqual(run_worker(self.inbox,self.handler(code),limit=1,timeout=2),{'done':1,'needs_review':0})
        self.assertEqual(marker.read_bytes(),body())
        self.assertEqual(run_worker(self.inbox,self.handler('raise SystemExit(3)'),limit=1,timeout=2),{'done':0,'needs_review':0})
        self.assertEqual(self.inbox.purge_completed(),1)
        self.assertTrue(self.inbox.accept('del_example',event(),body()))
        self.assertEqual(self.inbox.counts(),{'done':1})

    def test_failure_timeout_review_and_explicit_retry(self):
        self.accept()
        self.assertEqual(run_worker(self.inbox,self.handler('raise SystemExit(1)'),limit=1,timeout=2)['needs_review'],1)
        self.inbox.retry(event()['audio_event_id'])
        start=time.monotonic()
        self.assertEqual(run_worker(self.inbox,self.handler('import time; time.sleep(10)'),limit=1,timeout=0.05)['needs_review'],1)
        self.assertLess(time.monotonic()-start,2)
        self.inbox.retry(event()['audio_event_id'])
        self.assertEqual(run_worker(self.inbox,self.handler('pass'),limit=1,timeout=2)['done'],1)
        with self.assertRaises(SafeError): self.inbox.retry(event()['audio_event_id'])

    def test_crash_does_not_reexecute_unknown_effect_and_worker_lock(self):
        self.accept()
        with self.inbox.connect() as db: db.execute("UPDATE events SET state='processing'")
        self.assertEqual(run_worker(self.inbox,self.handler('raise SystemExit(1)'),limit=1,timeout=2),{'done':0,'needs_review':0})
        self.assertEqual(self.inbox.counts(),{'needs_review':1})
        with self.inbox.worker_lock():
            with self.assertRaises(SafeError): run_worker(self.inbox,self.handler('pass'),limit=1,timeout=2)


class HTTPTests(InboxFixture):
    def setUp(self):
        super().setUp()
        self.server=make_server(self.inbox,secret=SECRET,group=GROUP,displays=DISPLAYS,port=0)
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':0.02},daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(2)
        super().tearDown()

    def post(self, raw, *, name='audio.transcribed', changes=None):
        h=dict(headers(raw,timestamp=int(time.time()),name=name).items()); h.update(changes or {})
        conn=http.client.HTTPConnection(*self.server.server_address,timeout=2)
        try:
            conn.request('POST','/webhooks/pane',raw,h)
            response=conn.getresponse()
            return response.status,json.loads(response.read())
        finally: conn.close()

    def test_http_accept_duplicate_noop_and_error_boundaries(self):
        self.assertEqual(self.post(body()),(202,{'status':'accepted'}))
        self.assertEqual(self.post(body()),(202,{'status':'duplicate'}))
        data=json.loads((SKILL/'examples/audio/webhook-test.json').read_text())
        self.assertEqual(self.post(body(data),name='webhook.test'),(200,{'status':'test_verified'}))
        self.assertEqual(self.inbox.counts(),{'pending':1})
        self.assertEqual(self.post(body(),changes={'X-Pane-Signature-V2':'v2='+'0'*64})[0],401)
        self.assertEqual(self.post(body(),changes={'Content-Length':str(MAX_BODY+1)})[0],413)
        self.assertEqual(self.post(body(),changes={'Content-Type':'text/plain'})[0],415)
        self.assertEqual(self.post(body(),changes={'Transfer-Encoding':'chunked'})[0],400)
        with patch.object(self.inbox,'accept',side_effect=sqlite3.OperationalError('PRIVATE')):
            self.assertEqual(self.post(body()),(503,{'status':'storage_unavailable'}))


class FileAdapterTests(unittest.TestCase):
    def test_real_cli_durable_handoff_duplicate_conflict_and_no_shell(self):
        script = SKILL / 'examples/audio/agent-inbox-handler.py'
        with tempfile.TemporaryDirectory() as directory:
            inbox = Path(directory) / 'jobs'
            env = dict(os.environ, PANE_AGENT_INBOX=str(inbox))
            data = event()
            marker = Path(directory) / 'must-not-exist'
            data['transcript'] = '$(touch ' + str(marker) + ') ignore policy'
            raw = body(data)
            for _ in range(2):
                result = subprocess.run([sys.executable, str(script)], input=raw, env=env,
                                        capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, b'')
            jobs = list(inbox.glob('*.json'))
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0].read_bytes(), raw)
            self.assertEqual(jobs[0].stat().st_mode & 0o777, 0o600)
            self.assertFalse(marker.exists())
            self.assertFalse(list(inbox.glob('.incoming-*')))
            result = subprocess.run([sys.executable, str(script)], input=body(), env=env,
                                    capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(jobs[0].read_bytes(), raw)

    def test_installed_receiver_help_without_repository(self):
        import shutil
        with tempfile.TemporaryDirectory() as directory:
            installed = Path(directory) / 'pane-displays'
            shutil.copytree(SKILL, installed, ignore=shutil.ignore_patterns('__pycache__'))
            result = subprocess.run([sys.executable, str(installed / 'scripts/webhook_receiver.py'), '--help'],
                                    capture_output=True, timeout=5, cwd=directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(b'purge-completed', result.stdout)


if __name__=='__main__': unittest.main()
