"""Windows shell identity for the running Rootlize process.

Public taskbar / Alt+Tab identity is Rootlize. This is not DATA_DIR_NAME
and must not be used to build %APPDATA% paths.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import HRESULT, POINTER, c_ubyte, c_uint16, c_uint32, c_ulong, c_void_p, wintypes

from app.branding import APP_NAME

# Explicit AppUserModelID. Empty AUMID makes Win11 prefer the window-class
# icon (PyInstaller default) over WM_SETICON.
WINDOWS_APP_USER_MODEL_ID = f"{APP_NAME}.App"

_WM_SETICON = 0x0080
_ICON_SMALL = 0
_ICON_BIG = 1
_ICON_SMALL2 = 2
_GCLP_HICON = -14
_GCLP_HICONSM = -34
_VT_LPWSTR = 31
_IMAGE_ICON = 1
_LR_LOADFROMFILE = 0x0010
_SM_CXICON = 11
_SM_CYICON = 12
_SM_CXSMICON = 49
_SM_CYSMICON = 50
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010
_SWP_FRAMECHANGED = 0x0020
_HWND_TOP = 0

_hicon_big = 0
_hicon_small = 0


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", c_uint32),
        ("Data2", c_uint16),
        ("Data3", c_uint16),
        ("Data4", c_ubyte * 8),
    ]


def _guid(text: str) -> _GUID:
    a, b, c, d, e = text.split("-")
    packed = bytes.fromhex(d + e)
    return _GUID(int(a, 16), int(b, 16), int(c, 16), (c_ubyte * 8).from_buffer_copy(packed))


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", c_uint32)]


class _PROPVARIANT(ctypes.Structure):
    class _Data(ctypes.Union):
        _fields_ = [("pwszVal", wintypes.LPWSTR), ("uhVal", ctypes.c_uint64)]

    _anonymous_ = ("data",)
    _fields_ = [
        ("vt", c_uint16),
        ("reserved1", c_uint16),
        ("reserved2", c_uint16),
        ("reserved3", c_uint16),
        ("data", _Data),
    ]


class _IPropertyStoreVtbl(ctypes.Structure):
    _fields_ = [
        ("QueryInterface", c_void_p),
        ("AddRef", c_void_p),
        ("Release", c_void_p),
        ("GetCount", c_void_p),
        ("GetAt", c_void_p),
        ("GetValue", c_void_p),
        ("SetValue", c_void_p),
        ("Commit", c_void_p),
    ]


class _IPropertyStore(ctypes.Structure):
    _fields_ = [("lpVtbl", POINTER(_IPropertyStoreVtbl))]


_PKEY_APP_USER_MODEL_ID = _PROPERTYKEY(
    _guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), 5
)
# System.AppUserModel.RelaunchIconResource — taskbar button icon path.
_PKEY_RELAUNCH_ICON_RESOURCE = _PROPERTYKEY(
    _guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), 3
)
_IID_IPROPERTY_STORE = _guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")


def apply_windows_app_user_model_id() -> str:
    """Bind this process to the Rootlize shell ID. Call before QApplication()."""
    aumid = WINDOWS_APP_USER_MODEL_ID
    if sys.platform != "win32":
        return aumid
    try:
        fn = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        fn.argtypes = [wintypes.LPCWSTR]
        fn.restype = ctypes.c_long
        fn(aumid)
    except OSError:
        pass
    return aumid


def current_windows_app_user_model_id() -> str:
    if sys.platform != "win32":
        return ""
    try:
        getter = ctypes.windll.shell32.GetCurrentProcessExplicitAppUserModelID
        getter.argtypes = [POINTER(wintypes.LPWSTR)]
        getter.restype = ctypes.c_long
        value = wintypes.LPWSTR()
        if getter(ctypes.byref(value)) != 0 or not value:
            return ""
        text = value.value or ""
        ctypes.windll.ole32.CoTaskMemFree(value)
        return text
    except OSError:
        return ""


def windows_relaunch_icon_resource() -> str:
    """ICO Windows uses for the running taskbar button when AUMID is set.

    Prefer the bundled multi-size ICO over ``exe,0``. PyInstaller EXE
    resources often expose a 16px glyph that Win11 then upscales.
    """
    from app.ui.app_icon import app_ico_path

    return str(app_ico_path())


def _set_window_string_props(hwnd: int, values: list[tuple[_PROPERTYKEY, str]]) -> None:
    shell32 = ctypes.windll.shell32
    store_ptr = c_void_p()
    getter = shell32.SHGetPropertyStoreForWindow
    getter.argtypes = [wintypes.HWND, POINTER(_GUID), POINTER(c_void_p)]
    getter.restype = HRESULT
    hr = getter(wintypes.HWND(hwnd), ctypes.byref(_IID_IPROPERTY_STORE), ctypes.byref(store_ptr))
    if hr != 0 or not store_ptr.value:
        return
    store = ctypes.cast(store_ptr, POINTER(_IPropertyStore)).contents
    vtbl = store.lpVtbl.contents
    set_value = ctypes.WINFUNCTYPE(HRESULT, c_void_p, POINTER(_PROPERTYKEY), POINTER(_PROPVARIANT))(
        vtbl.SetValue
    )
    commit = ctypes.WINFUNCTYPE(HRESULT, c_void_p)(vtbl.Commit)
    release = ctypes.WINFUNCTYPE(c_ulong, c_void_p)(vtbl.Release)
    kept: list[tuple[ctypes.Array, _PROPVARIANT]] = []
    try:
        for key, text in values:
            buf = ctypes.create_unicode_buffer(text)
            variant = _PROPVARIANT()
            variant.vt = _VT_LPWSTR
            # LPWSTR fields reject c_wchar_Array; keep buf alive until Commit.
            variant.pwszVal = ctypes.cast(buf, wintypes.LPWSTR)
            kept.append((buf, variant))
            set_value(store_ptr, ctypes.byref(key), ctypes.byref(variant))
        commit(store_ptr)
    finally:
        release(store_ptr)


def _load_hicon(path: str, cx: int, cy: int) -> int:
    user32 = ctypes.windll.user32
    handle = wintypes.HANDLE()
    ident = ctypes.c_uint()
    user32.PrivateExtractIconsW.argtypes = [
        wintypes.LPCWSTR,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        POINTER(wintypes.HANDLE),
        POINTER(ctypes.c_uint),
        ctypes.c_uint,
        ctypes.c_uint,
    ]
    user32.PrivateExtractIconsW.restype = ctypes.c_uint
    extracted = user32.PrivateExtractIconsW(
        path, 0, cx, cy, ctypes.byref(handle), ctypes.byref(ident), 1, 0
    )
    if extracted and handle:
        return int(handle.value or 0)
    user32.LoadImageW.argtypes = [
        wintypes.HINSTANCE,
        wintypes.LPCWSTR,
        ctypes.c_uint,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    user32.LoadImageW.restype = wintypes.HANDLE
    loaded = user32.LoadImageW(None, path, _IMAGE_ICON, cx, cy, _LR_LOADFROMFILE)
    return int(loaded or 0)


def _cached_hicons() -> tuple[int, int]:
    global _hicon_big, _hicon_small
    if _hicon_big and _hicon_small:
        return _hicon_big, _hicon_small
    from app.ui.app_icon import app_ico_path

    path = app_ico_path()
    if not path.is_file():
        return 0, 0
    user32 = ctypes.windll.user32
    # Never stamp ICON_BIG from the 16px glyph; Win11 upscales that on the taskbar.
    cx = max(int(user32.GetSystemMetrics(_SM_CXICON) or 32), 32)
    cy = max(int(user32.GetSystemMetrics(_SM_CYICON) or 32), 32)
    cxsm = int(user32.GetSystemMetrics(_SM_CXSMICON) or 16)
    cysm = int(user32.GetSystemMetrics(_SM_CYSMICON) or 16)
    _hicon_big = _load_hicon(str(path), cx, cy)
    _hicon_small = _load_hicon(str(path), cxsm, cysm)
    if not _hicon_small:
        _hicon_small = _hicon_big
    if not _hicon_big:
        _hicon_big = _hicon_small
    return _hicon_big, _hicon_small


def apply_windows_window_icons(widget) -> None:
    """Stamp AUMID and load capixe.ico onto WM_SETICON and the window class."""
    if sys.platform != "win32" or widget is None:
        return
    try:
        hwnd = int(widget.winId())
        if not hwnd:
            return
        apply_windows_app_user_model_id()
    except Exception:
        return
    try:
        _set_window_string_props(
            hwnd,
            [
                (_PKEY_APP_USER_MODEL_ID, WINDOWS_APP_USER_MODEL_ID),
                (_PKEY_RELAUNCH_ICON_RESOURCE, windows_relaunch_icon_resource()),
            ],
        )
    except Exception:
        pass
    try:
        user32 = ctypes.windll.user32
        user32.SendMessageW.argtypes = [
            wintypes.HWND,
            ctypes.c_uint,
            ctypes.c_size_t,
            ctypes.c_size_t,
        ]
        user32.SendMessageW.restype = ctypes.c_size_t
        user32.SetClassLongPtrW.argtypes = [
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_size_t,
        ]
        user32.SetClassLongPtrW.restype = ctypes.c_size_t
        user32.SetWindowPos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
        ]
        user32.SetWindowPos.restype = wintypes.BOOL

        native = wintypes.HWND(hwnd)
        h_big, h_small = _cached_hicons()
        if h_big:
            user32.SendMessageW(native, _WM_SETICON, _ICON_BIG, h_big)
            user32.SetClassLongPtrW(native, _GCLP_HICON, h_big)
        if h_small:
            user32.SendMessageW(native, _WM_SETICON, _ICON_SMALL, h_small)
            user32.SendMessageW(native, _WM_SETICON, _ICON_SMALL2, h_small)
            user32.SetClassLongPtrW(native, _GCLP_HICONSM, h_small)
        user32.SetWindowPos(
            native,
            wintypes.HWND(_HWND_TOP),
            0,
            0,
            0,
            0,
            _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOZORDER | _SWP_NOACTIVATE | _SWP_FRAMECHANGED,
        )
    except Exception:
        pass
