"""Paint real project metadata in the home page's compact list view."""
from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from app.ui.theme import THEMES

PREVIEW_ROLE = int(Qt.ItemDataRole.UserRole) + 1


class ProjectListDelegate(QStyledItemDelegate):
    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.owner = owner

    def sizeHint(self, option, index):
        return QSize(400, 94)

    def paint(self, painter, option, index):
        data = index.data(PREVIEW_ROLE)
        if not data:
            return super().paint(painter, option, index)
        colors = THEMES[self.owner.theme]
        rect = option.rect.adjusted(12, 0, -12, 0)
        painter.save()
        painter.setClipRect(option.rect)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor(colors['soft']))
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(option.rect, QColor(colors['card']))
        thumbnail = data.get('thumbnail')
        if thumbnail and not thumbnail.isNull():
            image = thumbnail.scaled(56, 72, Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap(rect.left(), rect.top() + (rect.height() - image.height()) // 2, image)
        first_column = int(rect.width() * .56)
        second_column = int(rect.width() * .20)
        left = rect.left() + 72
        title_area = QRect(left, rect.top() + 20, max(40, first_column - 88), 26)
        font = QFont('Microsoft YaHei UI')
        font.setPixelSize(max(16, self.owner.options.get('ui_font_size', 14)))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(colors['text']))
        painter.drawText(title_area, Qt.AlignmentFlag.AlignVCenter,
                         painter.fontMetrics().elidedText(data['name'], Qt.TextElideMode.ElideRight, title_area.width()))
        font.setBold(False)
        font.setPixelSize(max(14, self.owner.options.get('ui_font_size', 14)))
        painter.setFont(font)
        painter.setPen(QColor(colors['muted']))
        summary_area = QRect(left, rect.top() + 49, title_area.width(), 22)
        painter.drawText(summary_area, Qt.AlignmentFlag.AlignVCenter,
                         painter.fontMetrics().elidedText(data['summary'].replace('\n', ' '),
                                                         Qt.TextElideMode.ElideRight, summary_area.width()))
        painter.setPen(QColor(colors['text']))
        kind_area = QRect(rect.left() + first_column, rect.top(), second_column, rect.height())
        painter.drawText(kind_area, Qt.AlignmentFlag.AlignVCenter, data['kind'])
        status_left = kind_area.right() + 12
        status_area = QRect(status_left, rect.center().y() - 16, max(40, rect.right() - status_left), 32)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(colors['soft']))
        painter.drawRoundedRect(status_area, 6, 6)
        painter.setPen(QColor(colors['accent']))
        painter.drawText(status_area, Qt.AlignmentFlag.AlignCenter, data['status'])
        painter.setPen(QPen(QColor(colors['border'])))
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        if option.state & QStyle.StateFlag.State_HasFocus:
            painter.setPen(QPen(QColor(colors['accent']), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(option.rect.adjusted(1, 1, -1, -1), 6, 6)
        painter.restore()
