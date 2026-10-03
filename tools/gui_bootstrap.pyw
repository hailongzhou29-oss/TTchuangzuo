"""Windowless source launcher with an explicit, retained startup failure log."""
import ctypes
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def main():
    from app.core.data_root import startup_paths,set_runtime_data_root
    explicit_preferences=Path(sys.argv[sys.argv.index('--preferences')+1]) if '--preferences' in sys.argv else None
    explicit_root=Path(sys.argv[sys.argv.index('--data-root')+1]) if '--data-root' in sys.argv else None
    data_root,preferences,_=startup_paths(ROOT,explicit_root,explicit_preferences); set_runtime_data_root(data_root)
    logs=data_root/'logs'; logs.mkdir(parents=True,exist_ok=True)
    stream=(logs/'gui-runtime.log').open('a',encoding='utf-8',buffering=1)
    sys.stdout=stream; sys.stderr=stream; sys._tt_log_stream=stream
    logging.basicConfig(filename=logs/'startup.log',encoding='utf-8',level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    try:
        if sys.version_info<(3,12): raise RuntimeError('需要 Python 3.12 或以上')
        import PySide6
        environment='Python '+sys.version.split()[0]+'，PySide6 '+PySide6.__version__
        logging.info('无控制台启动 pid=%s interpreter=%s %s',os.getpid(),sys.executable,environment)
        if len(sys.argv)>2 and sys.argv[1]=='--startup-probe':
            from PySide6.QtWidgets import QApplication
            app=QApplication([])
            titles=[]
            if os.name=='nt':
                callback=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
                def visit(hwnd,_):
                    pid=ctypes.c_ulong(); ctypes.windll.user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
                    if pid.value==os.getpid() and ctypes.windll.user32.IsWindowVisible(hwnd):
                        title=ctypes.create_unicode_buffer(256); ctypes.windll.user32.GetWindowTextW(hwnd,title,256); titles.append(title.value)
                    return True
                ctypes.windll.user32.EnumWindows(callback(visit),0)
            Path(sys.argv[2]).write_text(json.dumps(dict(pid=os.getpid(),platform=app.platformName(),visible_owned_windows=titles,console_attached=bool(ctypes.windll.kernel32.GetConsoleWindow()) if os.name=='nt' else False,environment=environment),ensure_ascii=False,indent=2),encoding='utf-8')
            return 0
        from app.main import main as run_app
        return run_app(sys.argv[1:])
    except Exception as exc:
        logging.exception('无控制台启动失败')
        message=f'启动失败：{exc}\n日志：{logs / "startup.log"}'
        if os.name=='nt': ctypes.windll.user32.MessageBoxW(None,message,'TT创作助手启动失败',0x10)
        else: print(message)
        return 1

if __name__=='__main__': raise SystemExit(main())
