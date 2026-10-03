"""Start the actual application entry point, then close its empty test window."""
import sys
import tempfile
import logging
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QTimer,Qt
from PySide6.QtWidgets import QApplication
from app.main import main
from app.ui.v2_window import MainWindow
from app.core.test_isolation import start_test_runtime
from app import __version__

show = MainWindow.show
def timed_show(window):
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    QApplication.instance().setProperty('native_hidden_test',True)
    show(window)
    assert __version__ in window.windowTitle()
    assert QApplication.instance().applicationVersion()==__version__
    QTimer.singleShot(500, QApplication.instance().quit)

local_checks=ROOT/'logs'; local_checks.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix='source-startup-',dir=local_checks) as temporary:
    base=start_test_runtime(Path(temporary))/'data'
    with patch.object(MainWindow, 'show', timed_show):
        try:
            result = main(['--data-root', str(base), '--preferences', str(base / 'preferences.json')])
        finally:
            sys.excepthook = sys.__excepthook__
            logging.shutdown()
    if result != 0:
        raise SystemExit(result)
print('SOURCE_STARTUP_PASS')
