"""Actual Qt widgets + event loop, isolated project data, no model requests."""
import argparse
import json
import os
import sys
import tempfile
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
parser = argparse.ArgumentParser()
parser.add_argument('--offscreen', action='store_true')
parser.add_argument('--scale', default='1')
args = parser.parse_args()
if args.offscreen:
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_SCALE_FACTOR'] = args.scale

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFontDatabase, QImage, QInputMethodEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from app.core.cover import default_cover, import_image, render_cover
from app.core.services import Workspace
from app.ui.cover_dialog import CoverDialog
from app.ui.theme import THEMES
from app.ui.window import MainWindow

artifacts = ROOT / 'docs' / 'evidence'
artifacts.mkdir(parents=True, exist_ok=True)
checks = []
app = QApplication([])
if args.offscreen:
    # The Windows offscreen plugin does not enumerate the system font database.
    for filename in ('msyh.ttc', 'msyhbd.ttc'):
        font_path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / filename
        if font_path.is_file():
            QFontDatabase.addApplicationFont(str(font_path))
with tempfile.TemporaryDirectory(prefix='TT 中文路径 UI ') as temporary:
    directory = Path(temporary)
    workspace = Workspace(directory / '工作区')
    window = MainWindow(workspace, ROOT / 'resources', directory / '偏好.json')
    window.show()
    QTest.qWait(100)
    checks.append(dict(check='首次启动无 KEY / 空项目', passed=window.project_list.count() == 0))
    store = workspace.create('秋日来信 · 验收项目', '剧本')
    did = store.documents()[0]['id']
    text = '【场1】历史教室 / 日 / 内\n\n老师：有些选择，一旦做出，就得承担后果。\n学生：那他当时知道，会失去什么吗？\n\n老师把地图摊在桌上，停了片刻。'
    store.save_document(did, store.document(did)['head'], text)
    window.open_project(store.root)
    window.editor.moveCursor(window.editor.textCursor().MoveOperation.End)
    window.editor.insertPlainText('\n学生：我想先听他的理由。')
    QTest.qWait(1200)
    checks.append(dict(check='真实编辑 / 自动保存', passed='先听他的理由' in store.document(did)['text']))
    before_failure = store.document(did)['text']
    window.editor.insertPlainText('\n未落盘草稿')
    with patch.object(window.store, 'save_document', side_effect=OSError('定向测试：磁盘写入失败')):
        failure = window.save(show_error=False)
    checks.append(dict(check='保存失败保留内存草稿 / 不误报已保存',
                       passed=not failure and window.dirty and '未落盘草稿' in window.editor.toPlainText()
                       and store.document(did)['text'] == before_failure and '尚未保存' in window.status.text()))
    window.editor.undo()
    window.save()
    for theme in THEMES:
        window.theme_combo.setCurrentText(theme)
        QTest.qWait(80)
        output = artifacts / f'ui_{theme}_scale{args.scale}.png'
        if not window.grab().save(str(output)):
            raise RuntimeError('界面截图保存失败')
        checks.append(dict(check='主题渲染 ' + theme, passed=True, screenshot=output.name))
    window.resize(1024, 640)
    QTest.qWait(120)
    window.grab().save(str(artifacts / f'ui_1024_scale{args.scale}.png'))
    checks.append(dict(check='1024 紧凑布局', passed=not window.assistant.isVisible() and window.editor.width() >= 300))
    event = QInputMethodEvent('组字中', [])
    QApplication.sendEvent(window.editor, event)
    checks.append(dict(check='组合输入暂停自动保存', passed=window.editor.composing and not window.autosave.isActive()))
    commit = QInputMethodEvent()
    commit.setCommitString('中文')
    QApplication.sendEvent(window.editor, commit)
    window.save()
    checks.append(dict(check='组合输入提交后保留文字', passed='中文' in store.document(did)['text']))
    window.enter_focus()
    window.exit_focus()
    checks.append(dict(check='专注视图恢复目录', passed=window.directory.isVisible()))
    spec = default_cover('秋日来信', '剧本')
    image = render_cover(spec, store.root)
    image_path = directory / '底图.png'
    image.save(str(image_path))
    imported, _ = import_image(store, image_path)
    spec.update(image=imported, title='中文封面准确排版')
    output = artifacts / f'cover_local_scale{args.scale}.png'
    if not render_cover(spec, store.root).save(str(output)):
        raise RuntimeError('封面导出失败')
    checks.append(dict(check='封面导入 / 标题排版 / 导出', passed=not QImage(str(output)).isNull(), screenshot=output.name))
    cover = CoverDialog(store, window)
    cover.show()
    QTest.qWait(80)
    cover.title.setText('独立标题')
    cover.adopt()
    checks.append(dict(check='封面界面保存 / 采用', passed=bool(store.setting('active_cover')) and len(store.covers()) == 1))
    cover.grab().save(str(artifacts / f'ui_cover_scale{args.scale}.png'))
    cover.close()
    window.save()
    window.close()
    reopened = MainWindow(workspace, ROOT / 'resources', directory / '偏好.json')
    checks.append(dict(check='偏好与项目恢复', passed=reopened.document_id == did and '中文' in reopened.editor.toPlainText()))
    reopened.close()

result = dict(platform='offscreen' if args.offscreen else 'Windows Qt', scale=args.scale,
              device_pixel_ratio=app.primaryScreen().devicePixelRatio(), checks=checks)
(artifacts / f'ui_results_scale{args.scale}.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
for check in checks:
    print(('PASS ' if check['passed'] else 'FAIL ') + check['check'])
if not all(check['passed'] for check in checks):
    raise SystemExit(1)
