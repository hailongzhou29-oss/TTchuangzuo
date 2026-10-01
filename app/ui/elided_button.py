from PySide6.QtCore import QSize,Qt
from PySide6.QtWidgets import QPushButton,QStyle,QStyleOptionButton,QStylePainter

class ElidedButton(QPushButton):
    def minimumSizeHint(self):
        return QSize(60,30)
    def sizeHint(self):
        return QSize(180,32)
    def paintEvent(self,event):
        painter=QStylePainter(self)
        option=QStyleOptionButton()
        self.initStyleOption(option)
        option.text=self.fontMetrics().elidedText(self.text(),Qt.TextElideMode.ElideRight,max(1,self.width()-12))
        painter.drawControl(QStyle.ControlElement.CE_PushButton,option)
