"""A file entry avoids Windows PowerShell's native -c quoting differences."""
import sys

if __name__=='__main__':
    if sys.version_info<(3,12):
        print('启动失败：需要 Python 3.12 或以上。当前版本：'+sys.version.split()[0]); raise SystemExit(1)
    try:
        import PySide6
    except ImportError:
        print('启动失败：当前 Python 缺少 PySide6，请按说明安装依赖。'); raise SystemExit(1)
    print('运行环境：Python '+sys.version.split()[0]+'，PySide6 '+PySide6.__version__)
