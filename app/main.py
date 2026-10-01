from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from app.core.services import Workspace
from app.ui.v2_window import APPLICATION_NAME, MainWindow

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=APPLICATION_NAME + ' 源码开发版')
    parser.add_argument('--data-root', type=Path, default=ROOT / 'user_data')
    parser.add_argument('--preferences', type=Path)
    args = parser.parse_args(argv)
    log_root = ROOT / 'logs'
    log_root.mkdir(exist_ok=True)
    logging.basicConfig(filename=log_root / 'startup.log', encoding='utf-8', level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APPLICATION_NAME)
    app.setOrganizationName('TTChuangzuo')
    def failure(kind, value, traceback):
        logging.error('未处理异常', exc_info=(kind, value, traceback))
        QMessageBox.critical(None, '程序操作异常', f'{value}\n日志保留于 {log_root / "startup.log"}')
    sys.excepthook = failure
    settings_root = Path(os.environ.get('LOCALAPPDATA', str(ROOT / 'user_data'))) / 'TTChuangzuo'
    preferences = args.preferences or settings_root / 'preferences.json'
    try:
        window = MainWindow(Workspace(args.data_root), ROOT / 'resources', preferences)
        window.show()
        logging.info('源码启动成功 Python=%s PySide6=%s', sys.version.split()[0], __import__('PySide6').__version__)
        return app.exec()
    except Exception:
        logging.exception('启动失败')
        raise


if __name__ == '__main__':
    raise SystemExit(main())
