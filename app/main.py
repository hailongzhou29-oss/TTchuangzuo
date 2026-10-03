from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox
from app import __version__

from app.core.services import Workspace
from app.core.data_root import startup_paths,set_runtime_data_root
from app.ui.v2_window import APPLICATION_NAME, MainWindow

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=APPLICATION_NAME + ' 源码开发版')
    parser.add_argument('--data-root', type=Path)
    parser.add_argument('--preferences', type=Path)
    args = parser.parse_args(argv)
    data_root,preferences,locator=startup_paths(ROOT,args.data_root,args.preferences)
    set_runtime_data_root(data_root)
    log_root = data_root / 'logs'
    log_root.mkdir(parents=True,exist_ok=True)
    logging.basicConfig(filename=log_root / 'startup.log', encoding='utf-8', level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APPLICATION_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName('TTChuangzuo')
    from app.ui.icons import application_icon,install_windows_identity
    from app.ui.interaction import ui_font
    install_windows_identity(); app.setWindowIcon(application_icon()); app.setFont(ui_font())
    def failure(kind, value, traceback):
        logging.error('未处理异常', exc_info=(kind, value, traceback))
        QMessageBox.critical(None, '程序操作异常', f'{value}\n日志保留于 {log_root / "startup.log"}')
    sys.excepthook = failure
    try:
        workspace=Workspace(data_root/'internal_data')
        window = MainWindow(workspace, ROOT / 'resources', preferences)
        window.runtime_locator=locator
        window.show()
        logging.info('源码启动成功 version=%s Python=%s PySide6=%s', __version__, sys.version.split()[0], __import__('PySide6').__version__)
        return app.exec()
    except Exception:
        logging.exception('启动失败')
        raise


if __name__ == '__main__':
    raise SystemExit(main())
