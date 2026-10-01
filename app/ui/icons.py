from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from app.ui.theme import THEMES

ROOT = Path(__file__).resolve().parents[2] / 'resources' / 'icons'


def icon(name, color='#596579', size=24):
    path = ROOT / (name + '.svg')
    if not path.is_file():
        return QIcon()
    data = path.read_bytes().replace(b'currentColor', color.encode('ascii'))
    renderer = QSvgRenderer(QByteArray(data))
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)


BUTTON_ICONS = {
    '新建项目': 'plus', '导入作品': 'upload', '打开目录': 'folder', '继续创作': 'arrow-right',
    '保存': 'check', '封面': 'book', '新增章 / 场 / 文档': 'plus', '导航': 'layout-sidebar-left-collapse',
    '收起助手': 'layout-sidebar-right-collapse', '打开助手': 'sparkles', '资料与规则': 'folder',
    '模型与设置': 'settings', '卡片视图': 'book', '列表视图': 'file-text',
}

NAV_ICONS = ['file-text', 'book', 'movie', 'pencil', 'stack-2', 'arrows-exchange', 'book', 'bulb', 'folder', 'settings']
