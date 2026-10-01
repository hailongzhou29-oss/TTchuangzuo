from PySide6.QtCore import Signal, QSignalBlocker
from PySide6.QtGui import QTextBlockFormat, QTextCursor
from PySide6.QtWidgets import QTextEdit


class WritingEditor(QTextEdit):
    composition_changed = Signal(bool)

    def __init__(self):
        super().__init__()
        self.composing = False
        self.setObjectName('editor')
        self.setAcceptRichText(False)
        self.setPlaceholderText('从一个想法开始，或导入已有作品。')

    def setPlainText(self, text):
        super().setPlainText(text)
        # Formatting is local presentation and never enters the stored plain text.
        blocker = QSignalBlocker(self)
        cursor = QTextCursor(self.document())
        cursor.select(QTextCursor.SelectionType.Document)
        block_format = QTextBlockFormat()
        block_format.setLineHeight(170, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
        cursor.mergeBlockFormat(block_format)
        self.document().clearUndoRedoStacks()
        del blocker

    def inputMethodEvent(self, event):
        self.composing = bool(event.preeditString())
        self.composition_changed.emit(self.composing)
        super().inputMethodEvent(event)

    def keyPressEvent(self, event):
        if self.composing:
            # The input method owns keys until its composition commits.
            event.ignore()
            return
        super().keyPressEvent(event)
