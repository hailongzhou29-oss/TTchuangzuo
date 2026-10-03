"""Nonblocking completion sound using the desktop's configured notification audio."""
import os

def play_completion_sound():
    try:
        if os.name=='nt':
            import winsound
            winsound.PlaySound('SystemAsterisk',winsound.SND_ALIAS|winsound.SND_ASYNC|winsound.SND_NODEFAULT)
        else:
            from PySide6.QtWidgets import QApplication
            QApplication.beep()
        return True
    except (RuntimeError,OSError):
        return False
