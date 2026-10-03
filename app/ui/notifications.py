"""Nonblocking completion sound using the desktop's configured notification audio."""
import os
from pathlib import Path

DEFAULT_AUDIO='gentle-bell.wav'
AUDIO_LABELS={'gentle-bell.wav':'轻柔铃音','clear-chime.wav':'清亮提示','warm-chord.wav':'温暖和弦'}

def audio_directory(): return Path(__file__).resolve().parents[2]/'resources'/'audio'/'notifications'

def available_audio():
    folder=audio_directory()
    return [(path.name,AUDIO_LABELS.get(path.name,path.stem)) for path in sorted(folder.glob('*.wav')) if path.is_file()]

def play_completion_sound(filename=None):
    try:
        folder=audio_directory(); selected=folder/Path(filename or DEFAULT_AUDIO).name
        if not selected.is_file(): selected=folder/DEFAULT_AUDIO
        if not selected.is_file(): return False
        if os.name=='nt':
            import winsound
            winsound.PlaySound(str(selected),winsound.SND_FILENAME|winsound.SND_ASYNC|winsound.SND_NODEFAULT)
        else:
            return False
        return True
    except (RuntimeError,OSError):
        return False
