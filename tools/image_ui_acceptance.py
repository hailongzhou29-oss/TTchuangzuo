"""Actual Qt image-job/candidate/cover workflow with labelled fixed PNG response."""
import base64
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app.core.services import Workspace
from app.providers.image_contracts import ImageConnection, ImageResult
from app.ui.cover_dialog import CoverDialog
from app.ui.window import MainWindow

app = QApplication([])
checks = []
evidence = ROOT / 'docs' / 'evidence'
image = QImage(512, 768, QImage.Format.Format_RGB32)
image.fill(QColor('#24455C'))
buffer = QBuffer()
buffer.open(QIODevice.OpenModeFlag.WriteOnly)
image.save(buffer, 'PNG')
data = bytes(buffer.data())

class FixtureProvider:
    calls = 0
    def submit(self, connection, secret, snapshot, cancel, **kwargs):
        self.calls += 1
        time.sleep(.1)
        return ImageResult(status='generated', items=[dict(b64_json=base64.b64encode(data).decode())], model='fixture', accepted=True)
    def bytes_for(self, item, *args):
        return base64.b64decode(item['b64_json'])

with tempfile.TemporaryDirectory(prefix='TT 封面界面验收 ') as temporary:
    root = Path(temporary)
    workspace = Workspace(root / 'data')
    store = workspace.create('开发测试 · 固定PNG', '小说')
    window = MainWindow(workspace, ROOT / 'resources', root / 'settings' / 'preferences.json')
    window.show()
    window.open_project(store.root)
    window.image_connections.save(ImageConnection('image_fixture', '开发测试固定图片响应', 'image_http', 'fixture',
        base_url='https://example.invalid', sizes=('1024x1536',)), 'fixture-image-key')
    cover = CoverDialog(store, window)
    cover.show()
    cover.tabs.setCurrentIndex(1)
    cover.prompt.setPlainText('蓝色雨夜的画面，只用于隔离测试；无真实模型调用。')
    fixture = FixtureProvider()
    cover.generate_background(provider=fixture, confirmed=True)
    deadline = time.monotonic() + 5
    while window.active_image_task and time.monotonic() < deadline:
        QTest.qWait(30)
    task = cover.image_service.get(cover.last_image_task)
    checks.append(dict(check='后台响应产生可解码真实PNG并登记任务', passed=task['state'] == 'verified' and len(task['asset_ids']) == 1))
    checks.append(dict(check='固定图片响应明确标开发测试', passed='开发测试固定图片响应' in cover.message.text()))
    checks.append(dict(check='生成候选不自动替换项目封面', passed=store.setting('active_cover') is None))
    cover.grab().save(str(evidence / 'ui_图片任务固定响应.png'))
    cover.use_candidate()
    cover.title.setText('中文标题本地改字')
    QTest.qWait(50)
    checks.append(dict(check='采用底图后改标题没有新生图请求', passed=fixture.calls == 1))
    cover.adopt()
    checks.append(dict(check='明确设为封面后保留版本', passed=bool(store.setting('active_cover')) and len(store.covers()) == 1))
    cover.grab().save(str(evidence / 'ui_模型底图本地排版.png'))
    checks.append(dict(check='标题层保持可编辑且原图尺寸可见', passed=cover.spec['title'] == '中文标题本地改字' and cover.spec['image_source_width'] == 512))
    cover.close()
    reopened = CoverDialog(store, window)
    checks.append(dict(check='重开恢复项目内底图及排版', passed=reopened.spec.get('image') == cover.spec['image']))
    reopened.close()
    window.close()

(evidence / 'image_ui_results.json').write_text(json.dumps(dict(mode='固定PNG测试，无真实生图调用', checks=checks), ensure_ascii=False, indent=2), encoding='utf-8')
for check in checks:
    print(('PASS ' if check['passed'] else 'FAIL ') + check['check'])
if not all(check['passed'] for check in checks):
    raise SystemExit(1)
