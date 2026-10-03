"""Source entry compatible with the standard Windows Python windowless launcher."""
import ctypes
import json
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def main():
    try:
        configured=json.loads((ROOT/'local.runtime.json').read_text(encoding='utf-8-sig'))['python']
        interpreter=Path(configured).with_name('pythonw.exe')
        if not interpreter.is_file(): raise RuntimeError('未找到所配置的 pythonw.exe：'+str(interpreter))
        subprocess.Popen([str(interpreter),str(ROOT/'tools/gui_bootstrap.pyw'),*sys.argv[1:]],cwd=ROOT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except Exception as exc:
        ctypes.windll.user32.MessageBoxW(None,'启动失败：'+str(exc),'TT创作助手启动失败',0x10)
        return 1
    return 0

if __name__=='__main__': raise SystemExit(main())
