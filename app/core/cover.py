from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QImage, QImageReader, QPainter

from app.core.files import atomic_write, digest, inside
from app.storage.project import ProjectStore

RATIOS = {'2:3': (800, 1200), '3:4': (900, 1200), '4:5': (960, 1200), '16:9': (1280, 720), '9:16': (720, 1280), '4:3': (1200, 900), '1:1': (1000, 1000)}


def default_cover(title: str, kind: str):
    return dict(title=title, subtitle='', author='', ratio='2:3', background='#283044', color='#F5EFE6',
                font='Microsoft YaHei', font_size=68, position='上部', image=None, kind=kind,
        focus_x=50, focus_y=50, origin='本地排版模板', include_local_text=True, transparent=False)


def validate_image(path: Path):
    if not path.is_file() or not 1 <= path.stat().st_size <= 30 * 1024**2:
        raise ValueError('图片文件为空或超过 30MB')
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    size = reader.size()
    if not size.isValid() or size.width() * size.height() > 40_000_000 or max(size.width(), size.height()) > 16384:
        raise ValueError('图片尺寸无效或超过解码限制')
    if reader.imageCount() > 1:
        raise ValueError('暂不支持多帧图片，请导入静态图片')
    image = reader.read()
    if image.isNull():
        raise ValueError('图片无法解码')
    return image


def import_image(store: ProjectStore, source: Path):
    image = validate_image(source)
    data = source.read_bytes()
    content_hash = digest(data)
    relative = f'assets/{content_hash}{source.suffix.lower()}'
    destination = inside(store.root, relative)
    if not destination.is_file():
        atomic_write(destination, data)
    store.register_asset(relative, content_hash)
    return relative, image


def render_cover(spec: dict, root: Path | None = None, width=None, safe_area=False) -> QImage:
    native_width, native_height = RATIOS[spec['ratio']]
    output_width = width or native_width
    output_height = round(output_width * native_height / native_width)
    image = QImage(output_width, output_height, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent if spec.get('transparent') else QColor(spec['background']))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.scale(output_width / native_width, output_height / native_height)
    try:
        if spec.get('image'):
            if root is None:
                raise ValueError('未指定封面素材所在项目')
            base = validate_image(inside(root, spec['image']))
            scale = max(native_width / base.width(), native_height / base.height())
            crop_width, crop_height = native_width / scale, native_height / scale
            left = (base.width() - crop_width) * spec.get('focus_x', 50) / 100
            top = (base.height() - crop_height) * spec.get('focus_y', 50) / 100
            painter.drawImage(QRectF(0, 0, native_width, native_height), base, QRectF(left, top, crop_width, crop_height))
            if spec.get('include_local_text', True):
                painter.fillRect(QRectF(0, 0, native_width, native_height), QColor(0, 0, 0, 65))
        if not spec.get('include_local_text', True):
            if safe_area:
                painter.setPen(QColor('#C6AC63'))
                painter.drawRect(QRectF(native_width * .09, native_height * .08, native_width * .82, native_height * .84))
            return image
        margin = native_width * .09
        title_height = native_height * .36
        title_top = {'上部': native_height * .14, '中部': native_height * .34, '下部': native_height * .54}[spec['position']]
        painter.setPen(QColor(spec['color']))
        font = QFont(spec['font'])
        font.setPixelSize(spec['font_size'])
        font.setBold(True)
        painter.setFont(font)
        flags = Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap | Qt.TextFlag.TextWrapAnywhere
        rect = QRectF(margin, title_top, native_width - 2 * margin, title_height)
        required = painter.boundingRect(rect, int(flags), spec['title'])
        if required.height() > title_height:
            raise ValueError('标题超出安全区，请减小字号或增加手动换行')
        painter.drawText(rect, int(flags), spec['title'])
        font.setPixelSize(max(20, round(spec['font_size'] * .40)))
        font.setBold(False)
        painter.setFont(font)
        painter.drawText(QRectF(margin, title_top + required.height() + 30, native_width - 2 * margin, native_height * .12), int(flags), spec.get('subtitle', ''))
        painter.drawText(QRectF(margin, native_height * .86, native_width - 2 * margin, native_height * .09), int(flags), spec.get('author', ''))
        if safe_area:
            painter.setPen(QColor('#C6AC63'))
            painter.drawRect(QRectF(margin, native_height * .08, native_width - 2 * margin, native_height * .84))
    finally:
        painter.end()
    return image
