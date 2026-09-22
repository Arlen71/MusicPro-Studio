"""Native folder picker for the running platform, in a short-lived helper process.

Windows keeps the existing Shell32 dialog untouched. macOS uses the Finder panel
through osascript, so the packaged Python still needs no Tcl/Tk. A cancelled
dialog reports an empty path and exit code 0, exactly like the Windows helper.
"""
from __future__ import annotations
import os
import subprocess
import sys

PROMPT = 'MusicPro — papkani tanlang'

# -128 is the AppleScript "user cancelled" error; it is not a failure.
MAC_SCRIPT = f'''activate
try
\tset chosen to choose folder with prompt "{PROMPT}"
on error number -128
\treturn ""
end try
return POSIX path of chosen
'''


def choose_folder_macos() -> str:
    try:
        p = subprocess.run(['/usr/bin/osascript', '-e', MAC_SCRIPT],
                           capture_output=True, encoding='utf-8', errors='replace', timeout=600)
    except (OSError, subprocess.SubprocessError) as error:
        raise OSError(f'macOS papka tanlash oynasini ochib bo‘lmadi: {error}') from error
    if p.returncode:
        raise OSError((p.stderr or '').strip() or 'macOS papka tanlash oynasi ochilmadi.')
    path = (p.stdout or '').strip()
    # AppleScript returns folders with a trailing separator; the root keeps its own.
    return path[:-1] if len(path) > 1 and path.endswith('/') else path


def choose_folder() -> str:
    if os.name == 'nt':
        from win_dialog import choose_folder as windows_picker
        return windows_picker()
    if sys.platform == 'darwin':
        return choose_folder_macos()
    raise RuntimeError('Papka oynasi bu tizimda mavjud emas. Manzilni qo‘lda kiriting.')


if __name__ == '__main__':
    try:
        sys.stdout.buffer.write(choose_folder().encode('utf-8'))
    except Exception as error:
        sys.stderr.buffer.write(str(error).encode('utf-8'))
        raise SystemExit(1)
