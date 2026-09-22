"""Windows folder picker using Shell32. The embedded Python needs no Tcl/Tk."""
from __future__ import annotations
import os
import sys


def choose_folder() -> str:
    if os.name != 'nt':
        raise RuntimeError('Papka oynasi Windows uchun. Manzilni qo‘lda kiriting.')
    import ctypes as C
    from ctypes import wintypes as W
    ole = C.WinDLL('ole32', use_last_error=True)
    shell = C.WinDLL('shell32', use_last_error=True)
    ole.CoInitializeEx.argtypes = [C.c_void_p, W.DWORD]
    ole.CoInitializeEx.restype = C.c_long
    ole.CoUninitialize.argtypes = []
    ole.CoTaskMemFree.argtypes = [C.c_void_p]

    class BROWSEINFO(C.Structure):
        _fields_ = [('hwndOwner', W.HWND), ('pidlRoot', C.c_void_p),
                    ('pszDisplayName', W.LPWSTR), ('lpszTitle', W.LPCWSTR),
                    ('ulFlags', W.UINT), ('lpfn', C.c_void_p),
                    ('lParam', C.c_ssize_t), ('iImage', C.c_int)]

    shell.SHBrowseForFolderW.argtypes = [C.POINTER(BROWSEINFO)]
    shell.SHBrowseForFolderW.restype = C.c_void_p
    shell.SHGetPathFromIDListEx.argtypes = [C.c_void_p, W.LPWSTR, W.DWORD, W.DWORD]
    shell.SHGetPathFromIDListEx.restype = W.BOOL
    result = ole.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED, on this helper process.
    if result < 0:
        raise OSError('Windows papka tanlash oynasini boshlash mumkin bo‘lmadi.')
    pidl = None
    try:
        display = C.create_unicode_buffer(260)
        info = BROWSEINFO(None, None, C.cast(display, W.LPWSTR), 'MusicPro — papkani tanlang', 0x51, None, 0, 0)
        # RETURNONLYFSDIRS | EDITBOX | NEWDIALOGSTYLE
        pidl = shell.SHBrowseForFolderW(C.byref(info))
        if not pidl:
            return ''
        path = C.create_unicode_buffer(32768)
        if not shell.SHGetPathFromIDListEx(pidl, path, len(path), 0):
            raise OSError('Tanlangan joy oddiy fayl papkasi emas.')
        return path.value
    finally:
        if pidl:
            ole.CoTaskMemFree(pidl)
        ole.CoUninitialize()


if __name__ == '__main__':
    try:
        sys.stdout.buffer.write(choose_folder().encode('utf-8'))
    except Exception as error:
        sys.stderr.buffer.write(str(error).encode('utf-8'))
        raise SystemExit(1)
