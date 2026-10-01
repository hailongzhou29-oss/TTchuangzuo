import io
import json
import os
import tempfile
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from app.core.services import Workspace
from app.core.tasks import TaskService, parse_candidate
from app.providers.codex_text import CodexTextProvider, command_prefix
from app.providers.contracts import CancelToken, Connection, TextResult, normalize_usage
from app.providers.http_text import HttpTextProvider, AbortScope, cancellable_opener
from app.storage.connections import ConnectionStore, SecretVault
from app.storage.project import ConflictError, LockedError

ROOT = Path(__file__).resolve().parents[1]


class FakeOpener:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.requests = response, error, []

    def open(self, request, timeout):
        self.requests.append(request)
        if self.error:
            raise self.error
        return io.BytesIO(self.response)


def sse(text='候选正文', finish='stop', usage=None, done=True):
    chunks = [dict(id='req-1', model='model-actual', choices=[dict(delta=dict(content=text), finish_reason=None)])]
    chunks.append(dict(choices=[dict(delta={}, finish_reason=finish)], usage=usage))
    data = ''.join('data: ' + json.dumps(chunk, ensure_ascii=False) + '\n\n' for chunk in chunks)
    if done:
        data += 'data: [DONE]\n\n'
    return data.encode('utf-8')


class FixtureProvider:
    def __init__(self, text, status='completed', delay=0):
        self.text, self.status, self.delay = text, status, delay

    def generate(self, connection, secret, messages, cancel, on_text, **kwargs):
        on_text(self.text)
        if self.delay:
            time.sleep(self.delay)
        return TextResult(text=self.text, status=self.status, finish_reason='stop', model=connection.model)


class TextTaskTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='TT 文字测试 中文 ')
        self.root = Path(self.temporary.name)
        self.workspace = Workspace(self.root / 'data')
        self.store = self.workspace.create('任务测试', '剧本')
        self.did = self.store.documents()[0]['id']
        self.store.save_document(self.did, self.store.document(self.did)['head'], '甲：开始。\n乙：原句。\n结束。')
        self.connections = ConnectionStore(self.root / 'settings')
        self.connections.save(Connection('test', '开发测试固定响应', 'deepseek', 'fake-model', base_url='https://example.invalid'), 'local-only-test-secret')
        self.connection = self.connections.get('test')
        self.service = TaskService(self.store, ROOT / 'resources', self.connections)

    def tearDown(self):
        self.temporary.cleanup()

    def snapshot(self, stage='draft_patch', start=6, end=11, **kwargs):
        return self.service.prepare(self.did, '修改当前选区', self.connection, stage, start, end, development_test=True, **kwargs)

    def test_stream_finish_and_usage(self):
        raw = dict(prompt_tokens=100, completion_tokens=20, prompt_cache_hit_tokens=80, completion_tokens_details=dict(reasoning_tokens=5))
        opener = FakeOpener(sse(usage=raw))
        parts = []
        result = HttpTextProvider(opener).generate(self.connection, 'secret', [dict(role='user', content='你好')], CancelToken(), parts.append)
        self.assertEqual(result.status, 'completed')
        self.assertEqual(result.text, ''.join(parts))
        self.assertEqual(result.usage['input'], 100)
        self.assertEqual(result.usage['cached_read'], 80)
        self.assertIsNone(result.usage['actual_cost'])
        self.assertEqual(len(opener.requests), 1)

    def test_nonstream_json_and_missing_usage(self):
        body = json.dumps(dict(id='n', model='actual', choices=[dict(message=dict(content='正文'), finish_reason='stop')])).encode()
        result = HttpTextProvider(FakeOpener(body)).generate(replace(self.connection, stream=False), 'secret', [], CancelToken())
        self.assertEqual(result.status, 'completed')
        self.assertIsNone(result.usage['input'])
        self.assertIsNone(result.usage['output'])

    def test_truncation_not_completed(self):
        result = HttpTextProvider(FakeOpener(sse(finish='length'))).generate(self.connection, 'secret', [], CancelToken())
        self.assertEqual(result.status, 'incomplete')
        self.assertTrue(result.text)

    def test_missing_finish_is_uncertain_no_retry(self):
        opener = FakeOpener(sse(finish=None, done=False))
        result = HttpTextProvider(opener).generate(self.connection, 'secret', [], CancelToken())
        self.assertEqual(result.status, 'uncertain')
        self.assertEqual(len(opener.requests), 1)

    def test_http_auth_rejection_not_retried(self):
        opener = FakeOpener(error=HTTPError('https://example.invalid', 401, 'unauthorized', {}, None))
        result = HttpTextProvider(opener).generate(self.connection, 'secret', [], CancelToken())
        self.assertEqual(result.status, 'failed')
        self.assertFalse(result.accepted)
        self.assertEqual(len(opener.requests), 1)

    def test_network_acceptance_unknown_not_retried(self):
        opener = FakeOpener(error=URLError('timeout'))
        result = HttpTextProvider(opener).generate(self.connection, 'secret', [], CancelToken())
        self.assertEqual(result.status, 'uncertain')
        self.assertIsNone(result.accepted)
        self.assertEqual(len(opener.requests), 1)

    def test_cancel_retains_partial(self):
        token = CancelToken()
        def receive(text):
            token.cancel()
        result = HttpTextProvider(FakeOpener(sse())).generate(self.connection, 'secret', [], token, receive)
        self.assertEqual(result.status, 'cancelled')
        self.assertEqual(result.text, '候选正文')

    def test_unsupported_reasoning_not_sent(self):
        opener = FakeOpener(sse())
        with self.assertRaises(ValueError):
            HttpTextProvider(opener).generate(self.connection, 'secret', [], CancelToken(), reasoning='max')
        self.assertEqual(len(opener.requests), 0)

    def test_provider_urls_preserve_native_base(self):
        for provider, base in [('deepseek', 'https://api.deepseek.com'), ('ark', 'https://ark.cn-beijing.volces.com/api/v3'), ('qwen', 'https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1')]:
            opener = FakeOpener(sse())
            con = replace(self.connection, provider=provider, base_url=base)
            HttpTextProvider(opener).generate(con, 'secret', [], CancelToken())
            self.assertEqual(opener.requests[0].full_url, base + '/chat/completions')

    def test_vault_is_encrypted_and_not_in_project_or_config(self):
        secret = 'local-only-test-secret'
        self.assertEqual(self.connections.secret_snapshot(self.connection), secret)
        self.assertNotIn(secret.encode(), self.connections.vault.path.read_bytes())
        self.assertNotIn(secret, self.connections.path.read_text(encoding='utf-8'))
        snapshot = self.snapshot()
        self.assertNotIn(secret, json.dumps(snapshot))
        self.assertNotIn(secret.encode(), self.store.path.read_bytes())

    def test_credential_change_before_execute_prevents_submission(self):
        snapshot = self.snapshot()
        self.connections.save(self.connection, 'new-local-secret')
        provider = FixtureProvider('{"text":"候选"}')
        with patch.object(provider, 'generate', wraps=provider.generate) as generate:
            result = self.service.execute(snapshot, CancelToken(), provider=provider)
            self.assertEqual(generate.call_count, 0)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('凭据已变更', result['error'])

    def test_snapshot_frozen_and_scope_rules(self):
        snapshot = self.snapshot()
        with self.store.connection() as con:
            frozen = json.loads(con.execute('SELECT snapshot FROM tasks WHERE id=?', (snapshot['task_id'],)).fetchone()[0])
        self.assertEqual(snapshot, frozen)
        self.assertEqual({r['rule_id'] for r in snapshot['rule_snapshot']}, {'G01', 'G03', 'G09'})
        self.assertEqual(snapshot['selected_text'], '乙：原句。')
        self.assertEqual(snapshot['model_selection']['model'], 'fake-model')

    def test_patch_adoption_changes_only_selected_text_and_records_block(self):
        snapshot = self.snapshot()
        self.service.execute(snapshot, CancelToken(), provider=FixtureProvider('{"text":"乙：新句。"}'))
        before = self.store.document(self.did)['text']
        result = self.service.adopt(snapshot['task_id'])
        self.assertEqual(result['text'], '甲：开始。\n乙：新句。\n结束。')
        self.assertNotEqual(before, result['text'])
        with self.store.connection() as con:
            self.assertTrue(con.execute('SELECT block_id FROM patches').fetchone()[0])
        self.assertEqual(self.service.get(snapshot['task_id'])['state'], 'accepted')

    def test_stale_candidate_does_not_overwrite_new_revision(self):
        snapshot = self.snapshot()
        self.service.execute(snapshot, CancelToken(), provider=FixtureProvider('{"text":"乙：新句。"}'))
        old = self.store.document(self.did)
        self.store.save_document(self.did, old['head'], old['text'] + '\n用户新编辑')
        with self.assertRaises(ConflictError):
            self.service.adopt(snapshot['task_id'])
        self.assertIn('用户新编辑', self.store.document(self.did)['text'])

    def test_lock_conflict_rolls_back_patch_transaction(self):
        self.store.lock(self.did, '乙：原句。', 6)
        snapshot = self.snapshot()
        self.service.execute(snapshot, CancelToken(), provider=FixtureProvider('{"text":"乙：新句。"}'))
        with self.assertRaises(LockedError):
            self.service.adopt(snapshot['task_id'])
        self.assertEqual(self.service.get(snapshot['task_id'])['state'], 'completed')
        with self.store.connection() as con:
            self.assertEqual(con.execute('SELECT COUNT(*) FROM patches').fetchone()[0], 0)

    def test_invalid_output_and_cancelled_result_cannot_be_adopted(self):
        snapshot = self.snapshot()
        result = self.service.execute(snapshot, CancelToken(), provider=FixtureProvider('不是 JSON'))
        self.assertEqual(result['status'], 'invalid_output')
        self.assertEqual(result['text'], '不是 JSON')
        with self.assertRaises(ValueError):
            self.service.adopt(snapshot['task_id'])
        token = CancelToken()
        token.cancel()
        new = self.snapshot()
        result = self.service.execute(new, token, provider=FixtureProvider('{"text":"已取消"}'))
        self.assertEqual(result['status'], 'cancelled')

    def test_minimal_test_excludes_work_and_locks(self):
        self.store.lock(self.did, '乙：原句。', 6)
        snapshot = self.service.prepare(self.did, '测试连接', self.connection, 'discussion', 0, 0, test_request=True)
        messages = json.dumps(snapshot['messages'], ensure_ascii=False)
        self.assertNotIn('乙：原句。', messages)
        self.assertIn('乙：原句。', self.store.document(self.did)['text'])

    def test_reviews_require_evidence_from_frozen_source(self):
        with self.assertRaises(ValueError):
            parse_candidate('{"issues":[{"evidence":"不存在的句子","issue":"问题","suggestion":"建议"}]}', 'review_draft', '原文')

    def test_context_limit_does_not_silently_drop_mandatory_text(self):
        with self.assertRaisesRegex(ValueError, '必需内容'):
            self.service.prepare(self.did, '修改', replace(self.connection, context_limit=4096), 'draft_patch', 7, 12)

    def test_schema_upgrade_keeps_pre_upgrade_database(self):
        self.assertTrue(list((self.store.root / 'backups').glob('升级前_v1_*.sqlite')))
        with self.store.connection() as con:
            self.assertEqual(con.execute('PRAGMA user_version').fetchone()[0], 6)
        self.assertTrue(list((self.store.root / 'backups').glob('升级前_v2_*.sqlite')))

    def test_interrupted_owner_recovery_preserves_partial_without_resubmitting(self):
        snapshot = self.snapshot()
        snapshot['owner_pid'] = 0
        with self.store.connection(write=True) as con:
            con.execute('UPDATE tasks SET snapshot=?,state=?,result=? WHERE id=?',
                (json.dumps(snapshot), 'generating', json.dumps(dict(text='已接收片段')), snapshot['task_id']))
        self.assertEqual(self.service.recover_unfinished(), [snapshot['task_id']])
        task = self.service.get(snapshot['task_id'])
        self.assertEqual(task['state'], 'uncertain')
        self.assertEqual(task['result']['text'], '已接收片段')
        self.assertEqual(len(self.service.history()), 1)

    def test_live_owner_is_not_marked_interrupted(self):
        snapshot = self.snapshot()
        self.assertEqual(self.service.recover_unfinished(), [])
        self.assertEqual(self.service.get(snapshot['task_id'])['state'], 'ready')

    def test_actual_local_http_stream_cancel_interrupts_blocked_receive(self):
        release = threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                chunk = {'choices': [{'delta': {'content': '真实本机传输'}, 'finish_reason': None}]}
                self.wfile.write(('data: ' + json.dumps(chunk) + '\n\n').encode())
                self.wfile.flush()
                release.wait(3)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        token = CancelToken()
        started = time.monotonic()
        timer = threading.Timer(.2, token.cancel)
        timer.start()
        try:
            connection = replace(self.connection, base_url='http://127.0.0.1:' + str(server.server_port))
            result = HttpTextProvider().generate(connection, 'local-test-key', [], token)
            self.assertEqual(result.status, 'cancelled')
            self.assertEqual(result.text, '真实本机传输')
            self.assertLess(time.monotonic() - started, 2)
        finally:
            timer.cancel()
            release.set()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_https_handler_uses_verified_python312_context(self):
        from urllib.request import HTTPSHandler, Request
        import ssl
        scope = AbortScope(CancelToken(), time.monotonic() + 30)
        opener = cancellable_opener(scope)
        handler = next(h for h in opener.handlers if isinstance(h, HTTPSHandler))
        with patch.object(handler, 'do_open', return_value='prepared') as opening:
            self.assertEqual(handler.https_open(Request('https://example.invalid')), 'prepared')
        context = opening.call_args.kwargs['context']
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)

    def test_model_discovery_can_run_before_model_id_is_known(self):
        opener = FakeOpener(json.dumps({'data': [{'id': 'discovered-model'}]}).encode())
        connection = replace(self.connection, model='')
        models = HttpTextProvider(opener).list_models(connection, 'fake-key')
        self.assertEqual(models, ['discovered-model'])
        with self.assertRaises(ValueError):
            connection.validate()

    def test_provider_or_host_change_never_inherits_old_secret(self):
        self.connections.save(replace(self.connection, provider='qwen', base_url='https://dashscope.aliyuncs.com/compatible-mode/v1'))
        changed = self.connections.get('test')
        self.assertEqual(self.connections.secret_snapshot(changed), '')
        self.connections.save(changed, 'new-qwen-key')
        updated = self.connections.get('test')
        self.assertEqual(self.connections.secret_snapshot(updated), 'new-qwen-key')
        self.connections.save(replace(updated, base_url='https://other.example.invalid'))
        self.assertEqual(self.connections.secret_snapshot(self.connections.get('test')), '')

    def test_failed_config_save_preserves_old_credential_binding(self):
        with patch('app.storage.connections.write_json', side_effect=OSError('定向模拟配置写入失败')):
            with self.assertRaises(OSError):
                self.connections.save(self.connection, 'replacement-test-key')
        current = self.connections.get('test')
        self.assertEqual(current.credential_version, self.connection.credential_version)
        self.assertEqual(self.connections.secret_snapshot(current), 'local-only-test-secret')

    def test_legacy_vault_entry_is_read_only_as_current_reference(self):
        self.connections.vault.set('legacy', 'legacy-test-key')
        self.connections.save(replace(self.connection, id='legacy', credential_version=1))
        legacy = self.connections.get('legacy')
        self.assertEqual(self.connections.secret_snapshot(legacy), 'legacy-test-key')
        self.connections.save(replace(legacy, provider='qwen', base_url='https://qwen.example.invalid'))
        self.assertEqual(self.connections.secret_snapshot(self.connections.get('legacy')), '')

    def test_deleted_connection_removes_all_secret_versions(self):
        self.connections.save(self.connection, 'second-test-key')
        self.connections.delete('test')
        self.assertFalse(any(key == 'test' or key.startswith('test:v') for key in self.connections.vault._read()))


if __name__ == '__main__':
    unittest.main()
