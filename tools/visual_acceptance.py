"""Render the home page at the reference viewport with isolated design fixtures."""
import json
import sys
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Match the reference's pixel viewport rather than the host monitor's 175% DPI.
os.environ['QT_SCALE_FACTOR'] = '1'
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton
from app.core.cover import default_cover, import_image
from app.core.services import Workspace
from app.ui.theme import THEMES
from app.ui.home import ProjectThumbnail
from app.ui.project_list import PREVIEW_ROLE
from app.ui.window import MainWindow

app = QApplication([])
evidence = ROOT / 'docs' / 'evidence'
evidence.mkdir(parents=True, exist_ok=True)
def capture(window, path):
    # Store logical pixels so 175% Windows scaling does not inflate the comparison.
    frame = window.grab().toImage()
    frame = frame.scaled(window.size(), Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    frame.setDevicePixelRatio(1)
    if not frame.save(str(path)):
        raise RuntimeError('界面截图保存失败')

reference = QImage(str(ROOT / 'resources' / '03_首页概念图.png'))
fixtures = [
    ('雨夜来信', '小说', '一封迟到的信，让平静的小城再次陷入谜团。\n十年前的雨夜，一封未送达的信改变了几个人的命运。如今，熟悉的小城再起波澜。', (289, 200, 245, 325)),
    ('周末出发', '剧本', '把周末交给山海，在路上遇见生活的另一种可能。', (291, 628, 242, 255)),
    ('一场误会', '剧本', '一次阴差阳错的相遇，让平凡的日子有了新的可能。', (551, 628, 201, 253)),
    ('城里的光', '文案', '在这座城市里，总有人为梦想悄悄发光。', (805, 628, 201, 253)),
]
checks = []
with tempfile.TemporaryDirectory(prefix='TT 视觉验收 隔离演示 ') as temporary:
    directory = Path(temporary)
    workspace = Workspace(directory / 'data')
    stores = []
    for title, kind, summary, rect in reversed(fixtures):
        store = workspace.create(title, kind)
        store.set_setting('creation_constraints',dict(primary_genre={'雨夜来信':'悬疑小说','周末出发':'文旅剧本','一场误会':'带货短剧','城里的光':'人物口播'}[title]))
        store.set_setting('summary', summary)
        sample = directory / (title + '.png')
        if not reference.copy(*rect).save(str(sample)):
            raise RuntimeError('无法读取附件中的参考封面')
        relative, _ = import_image(store, sample)
        spec = default_cover('', kind)
        spec.update(image=relative, ratio='3:4' if title=='雨夜来信' else '4:5',origin='隔离视觉验收：附件封面参考', subtitle='', author='', include_local_text=False)
        cid = store.save_cover(spec)
        store.set_setting('active_cover', cid)
        stores.append(store)
    window = MainWindow(workspace, ROOT / 'resources', directory / 'preferences.json')
    window.resize(1487, 1058)
    window.show()
    QTest.qWait(100)
    window.open_project(stores[-1].root, writing=False)
    window.navigation.setCurrentRow(0)
    window.home.select_project(str(stores[-1].root))
    QTest.qWait(100)
    window.home.render_projects()
    # The database's latest-edit ordering is valid in production. Fix this fixture's
    # order explicitly so repeated visual captures compare the same books.
    ordered = sorted((window.project_list.takeItem(0) for _ in range(window.project_list.count())),
                     key=lambda item: next(i for i, store in enumerate(reversed(stores))
                                           if str(store.root) == item.data(Qt.ItemDataRole.UserRole)))
    for item in ordered:
        window.project_list.addItem(item)
    window.home.select_project(str(stores[-1].root))
    window.home.render_projects()
    for theme in THEMES:
        window.theme_combo.setCurrentText(theme)
        QTest.qWait(100)
        path = evidence / ('home_' + theme + '.png')
        capture(window, path)
        checks.append(dict(theme=theme, viewport=[window.width(), window.height()], screenshot=path.name,
                           page='创作项目首页', fixture_scope='temporary_only'))
    checks.append(dict(check='完整封面预览不裁切标题', passed=all(
        abs(cover.pixmap().width() / cover.pixmap().height() - cover.source.width() / cover.source.height()) < .02
        for cover in window.home.cards.findChildren(ProjectThumbnail))))
    window.home.toggle_view()
    QTest.qWait(80)
    capture(window, evidence / 'home_列表视图.png')
    window.theme_combo.setCurrentText('雾白浅色')
    QTest.qWait(80)
    capture(window, evidence / 'home_雾白列表.png')
    checks.append(dict(check='作品列表封面与真实草稿状态', passed=all(
        window.project_list.item(i).data(PREVIEW_ROLE)['status'] == '草稿' and
        not window.project_list.item(i).data(PREVIEW_ROLE)['thumbnail'].isNull()
        for i in range(window.project_list.count()))))
    checks.append(dict(check='列表表头保持类型与进度', passed=window.home.list_header.isVisible()))
    selected = window.project_list.currentItem().data(Qt.ItemDataRole.UserRole)
    checks.append(dict(check='卡片/列表保留项目选择', passed=selected == str(stores[-1].root)))
    before_order = [window.project_list.item(i).data(Qt.ItemDataRole.UserRole)
                    for i in range(window.project_list.count())]
    window.home.toggle_view()
    window.home.toggle_view()
    checks.append(dict(check='卡片列表切换保持排序', passed=before_order == [
        window.project_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(window.project_list.count())]))
    row = window.project_list.item(1)
    row_root = row.data(Qt.ItemDataRole.UserRole)
    position = window.project_list.visualItemRect(row).center()
    QTest.mouseClick(window.project_list.viewport(), Qt.MouseButton.LeftButton, pos=position)
    QTest.mouseDClick(window.project_list.viewport(), Qt.MouseButton.LeftButton,
                     pos=position)
    QTest.qWait(60)
    checks.append(dict(check='列表双击打开对应项目正文', passed=window.pages.currentWidget() == window.writing and
                       str(window.store.root) == row_root))
    window.navigation.setCurrentRow(0)
    window.resize(1024, 640)
    QTest.qWait(80)
    capture(window, evidence / 'home_1024.png')
    checks.append(dict(check='首页窄屏', passed=not window.assistant.isVisible()))
    title_buttons = window.home.cards.findChildren(QPushButton, 'cardTitle')
    if title_buttons:
        QTest.mouseClick(title_buttons[0], Qt.MouseButton.LeftButton)
        QTest.qWait(50)
        checks.append(dict(check='点击项目卡片打开实际文档', passed=window.pages.currentWidget() == window.writing and window.document_id is not None))
    window.navigation.setCurrentRow(0)
    window.home.toggle_filters()
    window.project_search.setText('交给山海')
    checks.append(dict(check='按真实项目摘要搜索', passed=window.project_list.count() == 1 and
                       window.project_list.item(0).data(PREVIEW_ROLE)['name'] == '周末出发'))
    window.home.toggle_view()
    checks.append(dict(check='卡片列表切换保留筛选', passed=window.project_search.text() == '交给山海' and
                       window.project_list.count() == 1))
    window.project_search.setText('不存在的作品名称')
    clear = window.home.cards.findChild(QPushButton, 'clearProjectFilters')
    checks.append(dict(check='搜索无结果提供清除筛选', passed=clear is not None and window.project_list.count() == 0))
    if clear:
        QTest.mouseClick(clear, Qt.MouseButton.LeftButton)
        checks.append(dict(check='清除筛选恢复实际项目', passed=window.project_list.count() == 4 and
                           window.project_search.text() == '' and window.project_filter.currentIndex() == 0))
    window.close()
(evidence / 'home_visual_results.json').write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding='utf-8')
if any(item.get('passed') is False for item in checks):
    print('HOME_VISUAL_CAPTURE_FAIL')
    raise SystemExit(1)
print('HOME_VISUAL_CAPTURE_PASS')
