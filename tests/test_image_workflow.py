import base64
import io
import json
import os
import tempfile
import time
import unittest
import uuid
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from dataclasses import replace
from pathlib import Path
from urllib.error import URLError

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QColor, QImage

from app.core.cover import default_cover, import_image
from app.core.image_service import ImageService, image_info
from app.core.services import Workspace
from app.providers.codex_image import CodexImageProvider
from app.providers.contracts import CancelToken, TextResult, Connection
from app.providers.http_image import HttpImageProvider
from app.providers.image_contracts import ImageConnection, ImageResult
from app.storage.connections import ConnectionStore
from app.storage.image_connections import ImageConnectionStore

ROOT = Path(__file__).resolve().parents[1]


def png(color='#334455'):
    image = QImage(64, 96, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, 'PNG')
    return bytes(buffer.data())


class Opener:
    def __init__(self, value=None, error=None):
        self.body = json.dumps(value).encode() if value is not None else None
        self.error, self.calls = error, []
    def open(self, request, **kwargs):
        self.calls.append(request)
        if self.error:
            raise self.error
        return io.BytesIO(self.body)


class Fixture:
    def __init__(self, items=None, status='generated', job_id=''):
        self.items = items or []
        self.status, self.job_id, self.calls = status, job_id, 0
    def submit(self, connection, secret, snapshot, cancel, **kwargs):
        self.calls += 1
        return ImageResult(status=self.status, items=self.items, job_id=self.job_id, model=connection.model, accepted=True)
    def bytes_for(self, item, connection, cancel):
        return base64.b64decode(item['b64_json'], validate=True)


class ImageWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='TT 图片 中文 ')
        self.root = Path(self.temporary.name)
        self.workspace = Workspace(self.root / 'data')
        self.store = self.workspace.create('封面验收', '小说')
        self.connections = ImageConnectionStore(self.root / 'settings')
        self.connections.save(ImageConnection('image_fixture', '固定图片响应测试', 'image_http', 'fixture-image',
                              base_url='https://example.invalid', sizes=('1024x1536',), max_count=2), 'image-test-secret')
        self.connection = self.connections.get('image_fixture')
        self.service = ImageService(self.store, ROOT / 'resources', self.connections)
        self.spec = default_cover('封面验收', '小说')

    def tearDown(self):
        self.temporary.cleanup()

    def prepare(self, **kwargs):
        return self.service.prepare(self.connection, '蓝色雨夜，不添加文字。', self.spec, development_test=True, **kwargs)

    def item(self, color='#334455'):
        return dict(b64_json=base64.b64encode(png(color)).decode())

    def test_snapshot_exists_before_submit_and_duplicate_task_cannot_resubmit(self):
        snapshot = self.prepare()
        self.assertEqual(self.service.get(snapshot['task_id'])['state'], 'ready')
        fixture = Fixture([self.item()])
        result = self.service.execute(snapshot, CancelToken(), provider=fixture)
        self.assertEqual(result['status'], 'verified')
        with self.assertRaises(ValueError):
            self.service.execute(snapshot, CancelToken(), provider=fixture)
        self.assertEqual(fixture.calls, 1)

    def test_recovery_updates_both_image_states_without_decrypting_transport(self):
        from unittest.mock import patch
        snapshot=self.prepare()
        task_id=snapshot['task_id']
        with self.store.connection(write=True) as con:
            con.execute("UPDATE tasks SET state='uncertain',result=? WHERE id=?",(json.dumps(dict(text='本地部分记录')),task_id))
            con.execute("UPDATE image_jobs SET state='accepted',job_id='fixture-job',private_result='opaque-recovery-fixture' WHERE task_id=?",(task_id,))
        with patch('app.core.image_service.process_alive',return_value=False):
            self.assertEqual(self.service.recover(),[task_id])
        with self.store.connection() as con:
            task=con.execute('SELECT state,result FROM tasks WHERE id=?',(task_id,)).fetchone()
            image=con.execute('SELECT state,private_result FROM image_jobs WHERE task_id=?',(task_id,)).fetchone()
        self.assertEqual(task['state'],'uncertain')
        self.assertEqual(image['state'],'uncertain')
        self.assertEqual(image['private_result'],'opaque-recovery-fixture')
        self.assertEqual(json.loads(task['result'])['text'],'本地部分记录')
        self.assertEqual(json.loads(task['result'])['job_id'],'fixture-job')

    def test_png_artifact_dimensions_mime_hash_and_reopen_are_real(self):
        snapshot = self.prepare()
        result = self.service.execute(snapshot, CancelToken(), provider=Fixture([self.item()]))
        info = result['images'][0]
        self.assertEqual((info['width'], info['height']), (64, 96))
        self.assertEqual(info['mime'], 'image/png')
        path = self.store.root / info['relative']
        self.assertTrue(path.is_file())
        reopened = self.workspace.open(self.store.root)
        self.assertEqual(ImageService(reopened, ROOT / 'resources', self.connections).get(snapshot['task_id'])['asset_ids'], [info['asset_id']])

    def test_title_edit_and_image_candidate_do_not_auto_adopt_or_generate(self):
        snapshot = self.prepare()
        fixture = Fixture([self.item()])
        result = self.service.execute(snapshot, CancelToken(), provider=fixture)
        self.assertIsNone(self.store.setting('active_cover'))
        self.store.set_setting('cover_draft', dict(self.spec, title='修改标题'))
        self.assertEqual(fixture.calls, 1)
        self.assertTrue(result['images'])

    def test_submit_timeout_is_uncertain_and_never_auto_retried(self):
        opener = Opener(error=URLError('timeout'))
        provider = HttpImageProvider(opener)
        snapshot = self.prepare()
        result = self.service.execute(snapshot, CancelToken(), provider=provider)
        self.assertEqual(result['status'], 'uncertain')
        self.assertEqual(len(opener.calls), 1)

    def test_download_failure_can_retry_without_generation(self):
        snapshot = self.prepare()
        bad = Fixture([dict(b64_json='not-base64')])
        failed = self.service.execute(snapshot, CancelToken(), provider=bad)
        self.assertEqual(failed['status'], 'download_failed')
        class Downloader:
            def bytes_for(self, *args):
                return png()
        restored = self.service.materialize(snapshot['task_id'], CancelToken(), downloader=Downloader())
        self.assertEqual(restored['status'], 'verified')
        self.assertEqual(bad.calls, 1)

    def test_partial_batch_retains_success_and_retry_skips_successful_item(self):
        snapshot = self.prepare(count=2)
        fixture = Fixture([self.item(), {'b64_json': 'invalid'}])
        result = self.service.execute(snapshot, CancelToken(), provider=fixture)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(len(result['images']), 1)
        class Downloader:
            count = 0
            def bytes_for(self, *args):
                self.count += 1
                return png('#556677')
        downloader = Downloader()
        result = self.service.materialize(snapshot['task_id'], CancelToken(), downloader=downloader)
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(downloader.count, 1)
        self.assertEqual(fixture.calls, 1)

    def test_unknown_edit_seed_negative_or_size_are_not_downgraded(self):
        for kwargs in [dict(operation='edit'), dict(operation='variation'), dict(seed=3), dict(negative_prompt='no text'), dict(size='4096x4096')]:
            with self.assertRaises(ValueError):
                self.prepare(**kwargs)
        self.assertEqual(self.service.history(), [])

    def test_async_job_is_queryable_without_resubmit(self):
        connection = replace(self.connection, poll_path='/tasks/{job_id}')
        self.connections.save(connection)
        self.connection = self.connections.get(connection.id)
        snapshot = self.prepare()
        fixture = Fixture(status='accepted', job_id='remote-1')
        result = self.service.execute(snapshot, CancelToken(), provider=fixture)
        self.assertEqual(result['status'], 'accepted')
        opener = Opener({'task_id': 'remote-1', 'status': 'success', 'data': [self.item()]})
        result = self.service.query(snapshot['task_id'], CancelToken(), HttpImageProvider(opener))
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(opener.calls[0].get_method(), 'GET')
        self.assertEqual(fixture.calls, 1)

    def test_signed_urls_are_not_in_public_result_or_plaintext_database(self):
        snapshot = self.prepare()
        url = 'https://example.invalid/asset.png?signature=SECRET_SIGNATURE'
        result = self.service.execute(snapshot, CancelToken(), provider=Fixture([{'url': url}], status='accepted', job_id='job'))
        self.assertNotIn('SECRET_SIGNATURE', json.dumps(result))
        self.assertNotIn(b'SECRET_SIGNATURE', self.store.path.read_bytes())
        private = self.service.unseal(self.service.get(snapshot['task_id'])['private_result'])
        self.assertEqual(private['items'][0]['url'], url)

    def test_download_url_blocks_local_redirect_cross_host_and_non_https(self):
        for url in ['file:///C:/Windows/system.ini', 'http://127.0.0.1/private', 'http://example.invalid/x', 'https://other.invalid/x', 'https://user:pass@example.invalid/x']:
            with self.assertRaises(ValueError):
                HttpImageProvider.validate_asset_url(url, self.connection)

    def test_actual_provider_request_keeps_native_base_and_n(self):
        opener = Opener({'data': [self.item()]})
        snapshot = self.prepare(size='1024x1536')
        self.service.execute(snapshot, CancelToken(), provider=HttpImageProvider(opener))
        request = opener.calls[0]
        self.assertEqual(request.full_url, 'https://example.invalid/images/generations')
        body = json.loads(request.data)
        self.assertEqual(body['n'], 1)
        self.assertEqual(body['size'], '1024x1536')

    def test_image_connection_does_not_inherit_text_credentials(self):
        text_store = ConnectionStore(self.root / 'settings')
        text_store.save(Connection('text', '文字', 'deepseek', 'm', base_url='https://api.deepseek.com'), 'text-only-key')
        self.assertEqual(self.connections.secret_snapshot(self.connection), 'image-test-secret')
        self.assertNotIn('text-only-key', json.dumps(self.prepare()))

    def test_corrupt_or_vector_file_not_accepted_as_generated_image(self):
        for data in [b'', b'not-png', b'<svg width="64" height="96"></svg>']:
            with self.assertRaises(ValueError):
                image_info(data)

    def test_reference_asset_is_local_copy_with_hash_binding(self):
        external = self.root / 'reference.png'
        external.write_bytes(png())
        relative, _ = import_image(self.store, external)
        with self.store.connection() as con:
            aid = con.execute('SELECT id FROM assets WHERE relative=?', (relative,)).fetchone()[0]
        self.connections.save(replace(self.connection, supports_edit=True))
        self.connection = self.connections.get(self.connection.id)
        snapshot = self.prepare(operation='edit', reference_ids=[aid])
        external.unlink()
        self.assertEqual(snapshot['reference_assets'][0]['asset_id'], aid)
        self.assertTrue(self.service.asset(aid)[1].is_file())

    def test_codex_text_only_and_old_png_are_rejected(self):
        thread = str(uuid.uuid4())
        class Bridge:
            def generate(self, *args, **kwargs):
                return TextResult(text='图片已经生成', status='completed', request_id=thread)
        provider = CodexImageProvider(Bridge(), self.root / 'generated')
        connection = ImageConnection('cli', 'CLI测试', 'image_codex', 'fixture')
        snapshot = self.prepare()
        result = provider.submit(connection, '', snapshot, CancelToken(), output_root=self.root)
        self.assertEqual(result.status, 'failed')
        folder = self.root / 'generated' / thread
        folder.mkdir(parents=True)
        old = folder / 'old.png'
        old.write_bytes(png())
        os.utime(old, (snapshot['submitted_timestamp'] - 60, snapshot['submitted_timestamp'] - 60))
        result = provider.submit(connection, '', snapshot, CancelToken(), output_root=self.root)
        self.assertEqual(result.status, 'failed')

    def test_codex_fresh_current_thread_image_is_copied_and_validated(self):
        thread = str(uuid.uuid4())
        folder = self.root / 'generated' / thread
        folder.mkdir(parents=True)
        (folder / 'result.png').write_bytes(png())
        class Bridge:
            def generate(self, *args, **kwargs):
                return TextResult(text='{"image_paths":[]}', status='completed', request_id=thread)
        provider = CodexImageProvider(Bridge(), self.root / 'generated')
        connection = ImageConnection('cli', 'CLI测试', 'image_codex', 'fixture')
        result = provider.submit(connection, '', self.prepare(), CancelToken(), output_root=self.root)
        self.assertEqual(result.status, 'generated')
        self.assertTrue(Path(result.items[0]['path']).is_file())

    def test_cover_plan_excludes_full_manuscript_and_keeps_title_and_boundaries(self):
        from app.core.tasks import TaskService, parse_candidate
        from app.storage.connections import ConnectionStore
        did = self.store.documents()[0]['id']
        doc = self.store.document(did)
        self.store.save_document(did, doc['head'], 'PRIVATE_FULL_MANUSCRIPT 原文不发送。')
        text_connections = ConnectionStore(self.root / 'text-settings')
        text_connections.save(Connection('text', '文字策划', 'deepseek', 'fixture', base_url='https://example.invalid'), 'text-test-key')
        tasks = TaskService(self.store, ROOT / 'resources', text_connections)
        brief = dict(title='精确标题', synopsis='用户确认的小城来信。', text_mode='local', no_spoiler=True, reference_assets=[])
        snapshot = tasks.prepare(did, '封面规划', text_connections.get('text'), 'cover_plan', 0, 0, cover_brief=brief)
        self.assertNotIn('PRIVATE_FULL_MANUSCRIPT', json.dumps(snapshot['messages']))
        value = dict(cover_concept='雨夜街灯', positive_prompt='无字画面。', negative_prompt='避免文字', reference_bindings=[],
                     text_mode='local', title_plan=dict(title='精确标题', region='左上'), disclosure_level='no_spoiler', warnings=[])
        context = json.loads(snapshot['messages'][1]['content'].split('\n', 1)[1])
        self.assertEqual(parse_candidate(json.dumps(value), 'cover_plan', '', context)['title_plan']['title'], '精确标题')
        value['base_url'] = 'https://bad.invalid'
        with self.assertRaises(ValueError):
            parse_candidate(json.dumps(value), 'cover_plan', '', context)

    def test_edit_multipart_is_explicit_and_has_no_generation_fallback(self):
        source = self.root / 'ref.png'
        source.write_bytes(png())
        relative, _ = import_image(self.store, source)
        with self.store.connection() as con:
            aid = con.execute('SELECT id FROM assets WHERE relative=?', (relative,)).fetchone()[0]
        self.connections.save(replace(self.connection, supports_edit=True))
        self.connection = self.connections.get(self.connection.id)
        snapshot = self.prepare(operation='edit', reference_ids=[aid])
        opener = Opener({'data': [self.item()]})
        self.service.execute(snapshot, CancelToken(), provider=HttpImageProvider(opener))
        self.assertEqual(opener.calls[0].full_url, 'https://example.invalid/images/edits')
        self.assertIn(b'name="image"', opener.calls[0].data)
        self.assertEqual(len(opener.calls), 1)

    def test_story_basis_changes_mark_old_cover_without_regenerating(self):
        snapshot = self.prepare()
        fixture = Fixture([self.item()])
        self.service.execute(snapshot, CancelToken(), provider=fixture)
        self.assertFalse(self.service.basis_changed(snapshot['task_id']))
        self.store.set_setting('cover_brief', '新的已确认简介')
        self.assertTrue(self.service.basis_changed(snapshot['task_id']))
        self.assertEqual(fixture.calls, 1)

    def test_actual_local_http_generation_and_asset_get_do_not_forward_key(self):
        received = []
        data = png()
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                received.append(('POST', self.path, self.headers.get('Authorization'), body))
                response = json.dumps({'data': [{'url': f'http://127.0.0.1:{self.server.server_port}/image.png?signature=private-test-signature'}]}).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(response)))
                self.end_headers()
                self.wfile.write(response)
            def do_GET(self):
                received.append(('GET', self.path, self.headers.get('Authorization'), None))
                self.send_response(200)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = replace(self.connection, base_url=f'http://127.0.0.1:{server.server_port}')
            self.connections.save(connection, 'local-image-test-key')
            self.connection = self.connections.get(connection.id)
            snapshot = self.prepare()
            result = self.service.execute(snapshot, CancelToken())
            self.assertEqual(result['status'], 'verified')
            self.assertEqual([item[0] for item in received], ['POST', 'GET'])
            self.assertEqual(received[0][2], 'Bearer local-image-test-key')
            self.assertIsNone(received[1][2])
            self.assertNotIn('private-test-signature', json.dumps(result))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_candidate_recycle_restore_and_active_cover_protection(self):
        snapshot = self.prepare()
        self.service.execute(snapshot, CancelToken(), provider=Fixture([self.item()]))
        self.service.trash(snapshot['task_id'])
        self.assertEqual(self.service.history(), [])
        self.assertTrue(self.service.get(snapshot['task_id'])['asset_ids'])
        self.service.trash(snapshot['task_id'], restore=True)
        self.assertEqual(self.service.get(snapshot['task_id'])['state'], 'verified')
        cid = self.store.save_cover(dict(self.spec, image_task_id=snapshot['task_id']))
        self.store.set_setting('active_cover', cid)
        with self.assertRaisesRegex(ValueError, '正在作为项目封面'):
            self.service.trash(snapshot['task_id'])

    def test_transport_base64_and_signed_url_not_corrupted_by_metadata_redaction(self):
        from app.providers.http_image import sanitize_metadata
        value = {'data': [{'b64_json': 'secret-in-base64', 'url': 'https://x.invalid/a?token=secret'}], 'usage': {'note': 'secret'}}
        sanitized = sanitize_metadata(value, 'secret')
        self.assertEqual(sanitized['data'], value['data'])
        self.assertNotIn('secret', sanitized['usage']['note'])


if __name__ == '__main__':
    unittest.main()
