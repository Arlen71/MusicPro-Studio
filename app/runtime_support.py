"""Application-local paths and a process lock; no registry/PATH installation."""
from __future__ import annotations
import json
import os
import re
import sys
from pathlib import Path

VERSION = '1.8.0'


def console_python() -> str:
    path = Path(sys.executable)
    candidate = path.with_name('python.exe')
    return str(candidate) if os.name == 'nt' and candidate.is_file() else sys.executable


def installation_guard(app_root: Path):
    """Keep the setup/uninstaller from replacing a running installed copy."""
    if os.name != 'nt' or not (app_root.parent/'installed.flag').is_file():
        return None
    import ctypes as C
    from ctypes import wintypes as W
    kernel = C.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [C.c_void_p, W.BOOL, W.LPCWSTR]
    kernel.CreateMutexW.restype = W.HANDLE
    handle = kernel.CreateMutexW(None, False, 'Local\\MusicProStudio.Installed')
    if not handle: raise C.WinError(C.get_last_error())
    # Windows closes this handle when this application process exits.
    return handle


def data_directory(app_root: Path) -> Path:
    override = os.environ.get('MUSICPRO_DATA_DIR')
    if override:
        return Path(override).expanduser().resolve()
    bundle = app_root.parent
    if (bundle / 'installed.flag').is_file():
        if sys.platform == 'darwin':
            return Path.home() / 'Library' / 'Application Support' / 'MusicProStudio' / 'data'
        local = os.environ.get('LOCALAPPDATA')
        if not local:
            raise RuntimeError('LOCALAPPDATA topilmadi. Windows hisobingizni tekshiring.')
        return Path(local) / 'MusicProStudio' / 'data'
    if (bundle / 'bundle.json').is_file():
        return bundle / 'data'
    return app_root / 'data'


class InstanceLock:
    """Keep the open handle alive for the entire server lifetime."""
    def __init__(self, folder: Path):
        folder.mkdir(parents=True, exist_ok=True)
        self.path = folder / 'instance.lock'
        self.file = None

    def acquire(self) -> bool:
        handle = self.path.open('a+b')
        # Never rewrite another process's locked byte before acquiring the lock.
        if self.path.stat().st_size == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self.file = handle
        return True

    def close(self):
        if self.file:
            self.file.close()
            self.file = None


def existing_address(folder: Path) -> str | None:
    try:
        value = json.loads((folder / 'instance.json').read_text(encoding='utf-8'))
        address = value.get('address', '')
        if re.fullmatch(r'http://127\.0\.0\.1:87(?:6[5-9]|7[0-9]|8[0-4])', address):
            return address
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return None
