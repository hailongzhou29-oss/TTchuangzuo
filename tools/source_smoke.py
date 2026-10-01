"""Start the actual application entry point, then close its empty test window."""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from app.main import main
from app.ui.window import MainWindow

show = MainWindow.show
def timed_show(window):
    show(window)
    QTimer.singleShot(500, QApplication.instance().quit)

with tempfile.TemporaryDirectory(prefix='TT 源码启动检查 ') as temporary:
    with patch.object(MainWindow, 'show', timed_show):
        try:
            result = main(['--data-root', str(Path(temporary) / 'data'), '--preferences', str(Path(temporary) / 'preferences.json')])
        except Exception:
            sys.excepthook = sys.__excepthook__
            raise
    if result != 0:
        raise SystemExit(result)
print('SOURCE_STARTUP_PASS')
