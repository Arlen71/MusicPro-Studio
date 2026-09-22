"""Exercise the ctypes boundary, including construction of the output pointer."""
import ctypes
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import win_dialog


class Call:
    def __init__(self, result=None, body=None): self.result=result;self.body=body;self.calls=[]
    def __call__(self,*args):
        self.calls.append(args)
        return self.body(*args) if self.body else self.result


class FolderPickerTests(unittest.TestCase):
    def simulate(self, cancelled):
        selected='D:\\Video manbalar\\Ўзбек videolar'
        ole=SimpleNamespace(CoInitializeEx=Call(0),CoUninitialize=Call(),CoTaskMemFree=Call())
        def copy_path(pidl, buffer, size, flags):
            self.assertEqual(pidl,123)
            buffer.value=selected
            return True
        shell=SimpleNamespace(SHBrowseForFolderW=Call(None if cancelled else 123),
                              SHGetPathFromIDListEx=Call(body=copy_path))
        with patch.object(ctypes,'WinDLL',lambda name,**kw: ole if name=='ole32' else shell,create=True),patch.object(win_dialog.os,'name','nt'):
            result=win_dialog.choose_folder()
        self.assertEqual(result,'' if cancelled else selected)
        self.assertEqual(len(ole.CoUninitialize.calls),1)
        self.assertEqual(len(ole.CoTaskMemFree.calls),0 if cancelled else 1)
    def test_unicode_selection_releases_native_memory(self):self.simulate(False)
    def test_cancel_returns_empty_path(self):self.simulate(True)


if __name__=='__main__':unittest.main()
