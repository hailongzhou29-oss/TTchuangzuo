from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImageReader

from app.core.files import atomic_write, digest, inside
from app.core.cover import RATIOS
from app.core.rules import ProjectRules
from app.core.processes import process_alive
from app.core.task_runtime import owned_task,execution_owner,owner_alive
from app.providers.contracts import normalize_usage, redact
from app.providers.codex_image import CodexImageProvider
from app.providers.http_image import HttpImageProvider, MAX_IMAGE_BYTES
from app.providers.image_contracts import ImageConnection, ImageResult
from app.storage.connections import SecretVault
from app.storage.project import new_id, now
from app.core.budget import BudgetBook, BudgetError, estimate

ACTIVE = {'ready', 'submitting', 'accepted', 'generating', 'downloading'}


def image_info(data):
    if not 1 <= len(data) <= MAX_IMAGE_BYTES:
        raise ValueError('图片字节数为空或超过30MB')
    buffer = QBuffer()
    buffer.setData(data)
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    reader.setDecideFormatFromContent(True)
    reader.setAutoTransform(True)
    size = reader.size()
    if not size.isValid() or size.width() * size.height() > 40_000_000 or max(size.width(), size.height()) > 16384 or reader.imageCount() > 1:
        raise ValueError('图片尺寸/帧数超出校验范围')
    fmt = bytes(reader.format()).decode('ascii').lower()
    if fmt not in {'png', 'jpeg', 'jpg', 'webp'}:
        raise ValueError('产物须为可解码的 PNG/JPEG/WebP 栅格图片')
    image = reader.read()
    if image.isNull():
        raise ValueError('图片解码失败')
    return dict(width=image.width(), height=image.height(), mime='image/jpeg' if fmt in {'jpeg', 'jpg'} else 'image/' + fmt,
                extension='.jpg' if fmt in {'jpeg', 'jpg'} else '.' + fmt, sha256=digest(data), has_alpha=image.hasAlphaChannel())


class ImageService:
    def __init__(self, store, resources, connections):
        self.store, self.resources, self.connections = store, resources, connections
        self.budget_book=BudgetBook(connections.path.parent)

    def asset(self, asset_id):
        with self.store.connection() as con:
            row = con.execute('SELECT * FROM assets WHERE id=?', (asset_id,)).fetchone()
        if not row:
            raise ValueError('参考资产不属于当前项目')
        value = dict(row)
        path = inside(self.store.root, value['relative'])
        if not path.is_file():
            raise ValueError('参考资产文件缺失，请修复后重试')
        data = path.read_bytes()
        if digest(data) != value['hash']:
            raise ValueError('参考资产哈希已改变')
        value.update(image_info(data))
        return value, path

    def prepare(self, connection, prompt, cover_spec, *, operation='generate', reference_ids=(), mask_id=None,
                size=None, count=1, negative_prompt='', quality=None, seed=None, development_test=False):
        connection.validate()
        if not isinstance(cover_spec, dict) or cover_spec.get('ratio') not in RATIOS:
            raise ValueError('封面比例规格无效，未创建请求')
        if not connection.enabled:
            raise ValueError('图片连接已停用')
        if not prompt.strip() or len(prompt) > 30000:
            raise ValueError('画面提示词为空或过长')
        if operation not in {'generate', 'edit'}:
            raise ValueError('未声明支持该图片操作，不会降级为文生图')
        if operation == 'edit' and (not connection.supports_edit or not reference_ids):
            raise ValueError('该通道未声明参考编辑能力，或缺少底图')
        if operation == 'generate' and reference_ids and connection.provider == 'image_http':
            raise ValueError('参考图须明确选择参考编辑，不能偷偷丢弃参考')
        if mask_id and (operation != 'edit' or not connection.supports_mask):
            raise ValueError('该通道没有已声明的蒙版编辑能力')
        if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= connection.max_count:
            raise ValueError('数量超出通道声明')
        if size and size not in connection.sizes:
            raise ValueError('尺寸不在该通道已声明范围内')
        if negative_prompt and not connection.supports_negative:
            raise ValueError('通道未声明独立负面提示词参数')
        if seed is not None and (not connection.supports_seed or not isinstance(seed, int) or isinstance(seed, bool)):
            raise ValueError('通道未声明 seed 参数')
        if quality and quality not in connection.qualities:
            raise ValueError('质量参数未声明')
        if len(reference_ids) > 4 or len(set(reference_ids)) != len(reference_ids):
            raise ValueError('参考图最多4张且不能重复')
        references = []
        total_reference_bytes = 0
        for index, aid in enumerate(reference_ids):
            asset, path = self.asset(aid)
            total_reference_bytes += path.stat().st_size
            references.append(dict(asset_id=aid, relative=asset['relative'], order=index, purpose='画面参考', hash=asset['hash'], mime=asset['mime']))
        if total_reference_bytes > 60 * 1024**2:
            raise ValueError('参考图总量超过60MB，请使用必要的图片')
        mask = None
        if mask_id:
            mask, _ = self.asset(mask_id)
            first, _ = self.asset(reference_ids[0])
            if mask['mime'] != 'image/png' or not mask['has_alpha']:
                raise ValueError('蒙版须为含透明通道的 PNG')
            if (mask['width'], mask['height']) != (first['width'], first['height']):
                raise ValueError('蒙版尺寸须与第一张底图一致')
        if connection.provider == 'image_http':
            secret = self.connections.secret_snapshot(connection)
            if not secret:
                raise ValueError('该独立图片连接尚未保存 KEY')
            if secret in prompt or (negative_prompt and secret in negative_prompt):
                raise ValueError('画面提示包含该连接真实凭据，未创建请求')
        task_id = new_id()
        rule_service = ProjectRules(self.store, self.resources)
        rules = [r for r in rule_service.rules() if r['enabled'] and r['rule_id'] in {'G10', {'小说': 'G11', '剧本': 'G12', '文案': 'G13'}[self.store.metadata()['kind']], *({'G14'} if operation == 'edit' else set())}]
        snapshot = dict(schema_version=1, task_id=task_id, request_id=task_id, project_id=self.store.metadata()['id'],
            stage='image_generate', cover_id=self.store.setting('active_cover'), cover_revision_hash=digest(json.dumps(cover_spec, sort_keys=True, ensure_ascii=False)),
            connection_id=connection.id, model_id=connection.model, model_selection=connection.public(), operation=operation,
            prompt=prompt.strip(), negative_prompt=negative_prompt, reference_assets=references, mask_asset=mask,
            requested_ratio=cover_spec['ratio'], provider_size=size, count=count, quality=quality, seed=seed,
            cover_spec=dict(cover_spec), rule_snapshot=rules, prompt_snapshot_id=digest(prompt + json.dumps(rules, ensure_ascii=False)),
            budget_ref='用户本次图片请求', budget=dict(requested_images=count, actual_cost=None, currency=None),
            submitted_timestamp=time.time(), owner_pid=os.getpid(), development_test=development_test,
            estimated_input_tokens=None)
        snapshot['source_basis'] = self.basis()
        snapshot['budget']['monetary_limits']=self.store.setting('budget_settings',{}).get('monetary_limits',{})
        with self.store.connection(write=True) as con:
            existing = con.execute("SELECT task_id FROM image_jobs WHERE state IN ('ready','submitting','accepted','generating','downloading') LIMIT 1").fetchone()
            if existing:
                raise ValueError('当前项目已有图片任务，先查询/停止现有任务，未重复提交')
            con.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?)', (task_id, snapshot['project_id'], None, 'image_generate', json.dumps(snapshot, ensure_ascii=False), 'ready', None, now(), now()))
            con.execute('INSERT INTO image_jobs VALUES(?,?,?,?,?,?)', (task_id, '', 'ready', None, '[]', now()))
        return snapshot

    def get(self, task_id):
        with self.store.connection() as con:
            row = con.execute('SELECT t.*,i.job_id,i.private_result,i.asset_ids FROM tasks t JOIN image_jobs i ON t.id=i.task_id WHERE t.id=?', (task_id,)).fetchone()
        if not row:
            raise ValueError('图片任务不属于当前项目')
        value = dict(row)
        value['snapshot'] = json.loads(value['snapshot'])
        value['result'] = json.loads(value['result']) if value['result'] else None
        value['asset_ids'] = json.loads(value['asset_ids'])
        return value

    def history(self, include_trash=False):
        with self.store.connection() as con:
            where = '' if include_trash else " WHERE t.state!='trash'"
            return [dict(row) for row in con.execute('SELECT t.id,t.created,t.state,i.job_id FROM tasks t JOIN image_jobs i ON t.id=i.task_id' + where + ' ORDER BY t.rowid DESC LIMIT 100')]

    @staticmethod
    def seal(value):
        return base64.b64encode(SecretVault._crypt(json.dumps(value, ensure_ascii=False).encode('utf-8'))).decode('ascii')

    @staticmethod
    def unseal(value):
        return json.loads(SecretVault._crypt(base64.b64decode(value), decrypt=True).decode('utf-8'))

    def update(self, task_id, result, private=None, assets=None):
        encrypted = self.seal(private) if private is not None else None
        with self.store.connection(write=True) as con:
            con.execute('UPDATE tasks SET state=?,result=?,updated=? WHERE id=?', (result['status'], json.dumps(result, ensure_ascii=False), now(), task_id))
            con.execute('UPDATE image_jobs SET state=?,job_id=?,private_result=COALESCE(?,private_result),asset_ids=COALESCE(?,asset_ids),updated=? WHERE task_id=?',
                (result['status'], result.get('job_id', ''), encrypted, json.dumps(assets) if assets is not None else None, now(), task_id))

    @owned_task('image_submit')
    def execute(self, snapshot, cancel, on_state=lambda state: None, provider=None):
        task_id = snapshot['task_id']
        with self.store.connection(write=True) as con:
            row = con.execute('SELECT state FROM image_jobs WHERE task_id=?', (task_id,)).fetchone()
            if not row or row[0] != 'ready':
                raise ValueError('同一图片任务已提交，不能再次发送')
            con.execute('UPDATE image_jobs SET state=?,updated=? WHERE task_id=?', ('submitting', now(), task_id))
            con.execute('UPDATE tasks SET state=?,updated=? WHERE id=?', ('submitting', now(), task_id))
        connection = ImageConnection.from_dict(snapshot['model_selection'])
        job_root = inside(self.store.root, 'assets/.image_jobs/' + task_id)
        job_root.mkdir(parents=True, exist_ok=True)
        references = [self.asset(item['asset_id'])[1] for item in snapshot['reference_assets']]
        mask = self.asset(snapshot['mask_asset']['id'])[1] if snapshot['mask_asset'] else None
        gateway = provider or (CodexImageProvider() if connection.provider == 'image_codex' else HttpImageProvider())
        on_state('submitting')
        try:
            price=connection.pricing if connection.provider=='image_http' else {}
            amount=estimate(price,image_count=snapshot['count']) if price else None
            reservation=self.budget_book.reserve(snapshot['project_id'],task_id,0,amount,price,snapshot['budget'].get('monetary_limits',{}))
            secret = self.connections.secret_snapshot(connection) if connection.provider == 'image_http' else ''
            options = dict(references=references, mask=mask)
            if connection.provider == 'image_codex':
                options['output_root'] = job_root
            result = gateway.submit(connection, secret, snapshot, cancel, **options)
            self.budget_book.settle(reservation,amount if result.status=='generated' else None,rejected=result.accepted is False)
        except BudgetError as exc:
            result=ImageResult(status='budget_paused',model=connection.model,error=str(exc),accepted=False)
        except Exception as exc:
            result = ImageResult(status='cancelled' if cancel.cancelled else 'uncertain', model=connection.model, error=redact('图片请求结果待确认：' + str(exc)))
        public = result.public()
        if connection.pricing and connection.provider=='image_http':
            public['estimated_cost']=estimate(connection.pricing,image_count=snapshot['count'])
            public['currency']=connection.pricing['currency']
            public['price_version']=connection.pricing['version']
            public['cost_status']='估算，不是账单'
        public['development_test'] = snapshot['development_test']
        private = dict(items=result.items)
        self.update(task_id, public, private)
        with self.store.connection(write=True) as con:
            con.execute('INSERT INTO usage_ledger VALUES(?,?,?,?,?,?,?)', (new_id(), task_id, connection.name, result.model,
                json.dumps(dict(normalize_usage(connection.provider, result.raw_usage), requested_images=snapshot['count']), ensure_ascii=False),
                json.dumps(result.raw_usage, ensure_ascii=False), now()))
        if result.status == 'generated':
            return self.materialize(task_id, cancel, on_state, gateway if connection.provider == 'image_http' else HttpImageProvider())
        return public

    @owned_task('image_download')
    def materialize(self, task_id, cancel, on_state=lambda state: None, downloader=None):
        task = self.get(task_id)
        snapshot = task['snapshot']
        connection = ImageConnection.from_dict(snapshot['model_selection'])
        private = self.unseal(task['private_result']) if task['private_result'] else dict(items=[])
        assets = list(task['asset_ids'])
        items = private['items']
        failures = []
        public = dict(task['result'] or {}, status='downloading')
        self.update(task_id, public)
        on_state('downloading')
        downloader = downloader or HttpImageProvider()
        for index, item in enumerate(items):
            if item.get('asset_id'):
                continue
            if cancel.cancelled:
                break
            try:
                if item.get('path'):
                    path = Path(item['path']).resolve()
                    job_root = inside(self.store.root, 'assets/.image_jobs/' + task_id)
                    if not path.is_relative_to(job_root):
                        raise ValueError('CLI 产物路径超出本任务沙箱')
                data = downloader.bytes_for(item, connection, cancel)
                info = image_info(data)
                relative = 'assets/' + info['sha256'] + info['extension']
                atomic_write(inside(self.store.root, relative), data)
                aid = self.store.register_asset(relative, info['sha256'], info['mime'])
                items[index] = dict(asset_id=aid, relative=relative, source_fingerprint=self.fingerprint(item), **info)
                if aid not in assets:
                    assets.append(aid)
                # Persist each successful image before downloading the next.
                self.update(task_id, dict(public, images=[i for i in items if i.get('asset_id')]), dict(items=items), assets)
            except Exception as exc:
                failures.append(f'第{index + 1}张下载/校验失败：' + redact(str(exc)))
        complete = len([item for item in items if item.get('asset_id')])
        if cancel.cancelled:
            status = 'partial' if complete else 'cancelled'
        elif complete == snapshot['count']:
            status = 'verified'
        elif complete:
            status = 'partial'
        else:
            status = 'download_failed'
        warnings = list(public.get('warnings', []))
        for item in items:
            if item.get('asset_id'):
                x, y = (int(part) for part in snapshot['requested_ratio'].split(':'))
                if abs(item['width'] / item['height'] - x / y) > .03:
                    warnings.append('实际比例与请求不同；未拉伸原图，可在本地排版中裁切')
        public.update(status=status, images=[item for item in items if item.get('asset_id')], errors=failures, warnings=warnings)
        if complete > snapshot['count']:
            public['warnings'].append('服务返回图片数超过请求，保留产物并等待人工选择，不伪装请求完全匹配')
            public['extra_count'] = complete - snapshot['count']
        if complete < snapshot['count']:
            public['missing_count'] = snapshot['count'] - complete
        self.update(task_id, public, dict(items=items), assets)
        if status == 'verified' and not snapshot['development_test']:
            try:
                current = self.connections.get(connection.id)
                if all(getattr(current, key) == getattr(connection, key) for key in ('provider', 'model', 'base_url', 'credential_version', 'cli_path')):
                    from dataclasses import replace
                    verification = dict(current.verification, image_generation=dict(status='已实测', checked=now(), actual_images=complete,
                        dimensions=[[item['width'], item['height']] for item in items if item.get('asset_id')]))
                    self.connections.save(replace(current, verification=verification, capability_status='图片生成与产物已实测；编辑等能力分别验收'))
            except ValueError:
                pass
        return public

    def basis(self):
        with self.store.connection() as con:
            rows = con.execute("SELECT id,version FROM facts WHERE state='confirmed' ORDER BY id").fetchall()
        return dict(brief_hash=digest(self.store.setting('cover_brief', '')),
                    fact_versions=[dict(id=row['id'], version=row['version']) for row in rows])

    def basis_changed(self, task_id):
        return self.get(task_id)['snapshot'].get('source_basis') != self.basis()

    @owned_task('image_query')
    def query(self, task_id, cancel, provider=None):
        task = self.get(task_id)
        connection = self.connections.get(task['snapshot']['connection_id'])
        frozen = task['snapshot']['model_selection']
        if (connection.provider, connection.base_url, connection.model) != (frozen['provider'], frozen['base_url'], frozen['model']):
            raise ValueError('查询连接与原任务不匹配，未发送')
        if connection.provider != 'image_http':
            raise ValueError('CLI 无远端任务查询；可检查已登记产物或发明确的新任务')
        gateway = provider or HttpImageProvider()
        result = gateway.query(connection, self.connections.secret_snapshot(connection), task['job_id'], cancel)
        public = result.public()
        public['development_test'] = task['snapshot']['development_test']
        old_private = self.unseal(task['private_result']) if task['private_result'] else dict(items=[])
        successes = [item for item in old_private['items'] if item.get('asset_id')]
        if successes:
            public['images'] = successes
        known = {item.get('source_fingerprint') for item in successes}
        combined = list(successes)
        for item in result.items:
            if self.fingerprint(item) not in known:
                combined.append(item)
        self.update(task_id, public, dict(items=combined))
        return self.materialize(task_id, cancel, downloader=gateway) if result.status == 'generated' else public

    def trash(self, task_id, restore=False):
        runtime=execution_owner(self.store,task_id)
        if runtime and runtime['active'] and owner_alive({},runtime):
            raise ValueError('该图片任务仍在处理，请先停止或等待完成')
        task = self.get(task_id)
        result = dict(task['result'] or {})
        if restore:
            if task['state'] != 'trash':
                raise ValueError('该图片候选不在回收区')
            result['status'] = result.pop('previous_state', 'verified' if task['asset_ids'] else 'uncertain')
        else:
            if task['state'] in ACTIVE:
                raise ValueError('正在运行的图片任务须先停止或完成')
            active = self.store.setting('active_cover')
            if any(cover['id'] == active and cover['spec'].get('image_task_id') == task_id for cover in self.store.covers()):
                raise ValueError('该图片正在作为项目封面，先选择其他封面再回收')
            result.update(previous_state=task['state'], status='trash')
        self.update(task_id, result)

    @staticmethod
    def fingerprint(item):
        if item.get('source_fingerprint'):
            return item['source_fingerprint']
        if item.get('url'):
            from urllib.parse import urlparse
            value = urlparse(item['url'])
            return digest(value.scheme + '://' + str(value.hostname) + value.path)
        return digest(str(item.get('b64_json') or item.get('path') or ''))

    def recover(self):
        recovered = []
        with self.store.connection() as con:
            rows=[dict(row) for row in con.execute("SELECT t.id,t.snapshot,t.result,i.job_id FROM tasks t JOIN image_jobs i ON t.id=i.task_id WHERE t.state!='trash' AND (t.state IN ('ready','submitting','accepted','generating','downloading') OR i.state IN ('ready','submitting','accepted','generating','downloading'))")]
        for task in rows:
            if not owner_alive(json.loads(task['snapshot']),execution_owner(self.store,task['id']),fallback=process_alive):
                result = dict(json.loads(task['result']) if task['result'] else {}, status='uncertain', job_id=task['job_id'], error='上次本地进程已结束，先按任务号查询；没有自动重新生成')
                # Recovery preserves encrypted transport data; it does not need to decrypt it.
                self.update(task['id'], result)
                recovered.append(task['id'])
        return recovered
