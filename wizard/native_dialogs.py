"""Native file dialogs for WebView shell (tk parent may be hidden)."""
from __future__ import annotations

import sys
from typing import Any


def _json_initial_dir() -> str | None:
    try:
        from setup_wizard import _json_file_dialog_initialdir

        d = _json_file_dialog_initialdir()
        return d if d else None
    except Exception:
        return None


def _win32_open_file(*, title: str) -> str | None:
    import ctypes
    from ctypes import wintypes

    comdlg32 = ctypes.windll.comdlg32
    OFN_FILEMUSTEXIST = 0x00001000
    OFN_PATHMUSTEXIST = 0x00000800
    OFN_EXPLORER = 0x00080000

    class OPENFILENAMEW(ctypes.Structure):
        _fields_ = [
            ("lStructSize", wintypes.DWORD),
            ("hwndOwner", wintypes.HWND),
            ("hInstance", wintypes.HINSTANCE),
            ("lpstrFilter", wintypes.LPCWSTR),
            ("lpstrCustomFilter", wintypes.LPWSTR),
            ("nMaxCustFilter", wintypes.DWORD),
            ("nFilterIndex", wintypes.DWORD),
            ("lpstrFile", wintypes.LPWSTR),
            ("nMaxFile", wintypes.DWORD),
            ("lpstrFileTitle", wintypes.LPWSTR),
            ("nMaxFileTitle", wintypes.DWORD),
            ("lpstrInitialDir", wintypes.LPCWSTR),
            ("lpstrTitle", wintypes.LPCWSTR),
            ("Flags", wintypes.DWORD),
            ("nFileOffset", wintypes.WORD),
            ("nFileExtension", wintypes.WORD),
            ("lpstrDefExt", wintypes.LPCWSTR),
            ("lCustData", wintypes.LPARAM),
            ("lpfnHook", wintypes.LPVOID),
            ("lpTemplateName", wintypes.LPCWSTR),
            ("pvReserved", wintypes.LPVOID),
            ("dwReserved", wintypes.DWORD),
            ("FlagsEx", wintypes.DWORD),
        ]

    buf = ctypes.create_unicode_buffer(65536)
    initial = _json_initial_dir() or ""
    ofn = OPENFILENAMEW()
    ofn.lStructSize = ctypes.sizeof(OPENFILENAMEW)
    ofn.hwndOwner = None
    ofn.lpstrFilter = "JSON sequences (*.json)\0*.json\0All files (*.*)\0*.*\0\0"
    ofn.lpstrFile = buf
    ofn.nMaxFile = len(buf)
    ofn.lpstrInitialDir = initial
    ofn.lpstrTitle = title
    ofn.Flags = OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_EXPLORER
    if comdlg32.GetOpenFileNameW(ctypes.byref(ofn)):
        return buf.value
    return None


def _win32_save_file(*, title: str, initialfile: str) -> str | None:
    import ctypes
    from ctypes import wintypes

    comdlg32 = ctypes.windll.comdlg32
    OFN_OVERWRITEPROMPT = 0x00000002
    OFN_PATHMUSTEXIST = 0x00000800
    OFN_EXPLORER = 0x00080000

    class OPENFILENAMEW(ctypes.Structure):
        _fields_ = [
            ("lStructSize", wintypes.DWORD),
            ("hwndOwner", wintypes.HWND),
            ("hInstance", wintypes.HINSTANCE),
            ("lpstrFilter", wintypes.LPCWSTR),
            ("lpstrCustomFilter", wintypes.LPWSTR),
            ("nMaxCustFilter", wintypes.DWORD),
            ("nFilterIndex", wintypes.DWORD),
            ("lpstrFile", wintypes.LPWSTR),
            ("nMaxFile", wintypes.DWORD),
            ("lpstrFileTitle", wintypes.LPWSTR),
            ("nMaxFileTitle", wintypes.DWORD),
            ("lpstrInitialDir", wintypes.LPCWSTR),
            ("lpstrTitle", wintypes.LPCWSTR),
            ("Flags", wintypes.DWORD),
            ("nFileOffset", wintypes.WORD),
            ("nFileExtension", wintypes.WORD),
            ("lpstrDefExt", wintypes.LPCWSTR),
            ("lCustData", wintypes.LPARAM),
            ("lpfnHook", wintypes.LPVOID),
            ("lpTemplateName", wintypes.LPCWSTR),
            ("pvReserved", wintypes.LPVOID),
            ("dwReserved", wintypes.DWORD),
            ("FlagsEx", wintypes.DWORD),
        ]

    buf = ctypes.create_unicode_buffer(initialfile)
    initial = _json_initial_dir() or ""
    ofn = OPENFILENAMEW()
    ofn.lStructSize = ctypes.sizeof(OPENFILENAMEW)
    ofn.hwndOwner = None
    ofn.lpstrFilter = "JSON sequences (*.json)\0*.json\0All files (*.*)\0*.*\0\0"
    ofn.lpstrFile = buf
    ofn.nMaxFile = 65536
    ofn.lpstrInitialDir = initial
    ofn.lpstrTitle = title
    ofn.lpstrDefExt = "json"
    ofn.Flags = OFN_OVERWRITEPROMPT | OFN_PATHMUSTEXIST | OFN_EXPLORER
    if comdlg32.GetSaveFileNameW(ctypes.byref(ofn)):
        p = buf.value
        if p and not p.lower().endswith(".json"):
            p += ".json"
        return p
    return None


def ask_open_json_file(*, title: str = "Load sequence", parent: Any = None) -> str | None:
    if sys.platform == "win32":
        try:
            p = _win32_open_file(title=title)
            if p:
                return p
        except Exception:
            pass

    from tkinter import filedialog

    path = filedialog.askopenfilename(
        parent=parent,
        title=title,
        filetypes=[("JSON sequence", "*.json"), ("All files", "*.*")],
        initialdir=_json_initial_dir(),
    )
    return path or None


def ask_save_json_file(
    *,
    title: str = "Save sequence",
    initialfile: str = "default_sequence.json",
    parent: Any = None,
) -> str | None:
    if sys.platform == "win32":
        try:
            p = _win32_save_file(title=title, initialfile=initialfile)
            if p:
                return p
        except Exception:
            pass

    from tkinter import filedialog

    path = filedialog.asksaveasfilename(
        parent=parent,
        title=title,
        defaultextension=".json",
        filetypes=[("JSON sequence", "*.json"), ("All files", "*.*")],
        initialfile=initialfile,
        initialdir=_json_initial_dir(),
    )
    return path or None
