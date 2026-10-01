"""Local process identity, including creation time to distinguish reused PIDs."""
import ctypes
import os
from pathlib import Path


def process_alive(pid):
    if not isinstance(pid,int) or isinstance(pid,bool) or pid<=0:
        return False
    if pid==os.getpid():
        return True
    if os.name=='nt':
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=kernel.OpenProcess(0x1000,False,pid)
        if not handle:
            return ctypes.get_last_error()==5
        try:
            code=wintypes.DWORD()
            kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
            return not kernel.GetExitCodeProcess(handle,ctypes.byref(code)) or code.value==259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid,0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def process_started(pid):
    if not isinstance(pid,int) or isinstance(pid,bool) or pid<=0:
        return None
    if os.name=='nt':
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=kernel.OpenProcess(0x1000,False,pid)
        if not handle:
            return None
        try:
            creation,exit_time,kernel_time,user_time=[wintypes.FILETIME() for _ in range(4)]
            kernel.GetProcessTimes.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4
            if not kernel.GetProcessTimes(handle,ctypes.byref(creation),ctypes.byref(exit_time),ctypes.byref(kernel_time),ctypes.byref(user_time)):
                return None
            return str((creation.dwHighDateTime<<32)|creation.dwLowDateTime)
        finally:
            kernel.CloseHandle(handle)
    try:
        fields=Path('/proc')/str(pid)/'stat'
        return fields.read_text().rsplit(')',1)[1].split()[19]
    except (OSError,IndexError):
        return None
