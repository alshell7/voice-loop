"""Opt-in OS capture exclusion. This is not a security or DRM boundary."""

import ctypes
import sys
import weakref
from ctypes import wintypes

from PySide6.QtCore import QEvent, QObject, Signal
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid

WDA_NONE = 0
WDA_EXCLUDEFROMCAPTURE = 0x11


class NativeCaptureProtection:
    def __init__(self):
        platform = QApplication.platformName()
        self.supported = (sys.platform == "win32" and platform == "windows") or (
            sys.platform == "darwin" and platform == "cocoa"
        )
        self.limitation = (
            "Windows excludes these windows from supported screenshots and screen sharing. "
            "Some capture methods can bypass this protection."
            if sys.platform == "win32"
            else "Limited on macOS: legacy capture exclusion only. Modern tools using "
            "ScreenCaptureKit can still capture these windows."
            if sys.platform == "darwin"
            else "Capture exclusion is unavailable on Linux. Your desktop controls screen sharing."
        )
        self._api = None

    def _windows(self):
        if self._api is None:
            api = ctypes.WinDLL("user32", use_last_error=True)
            api.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
            api.SetWindowDisplayAffinity.restype = wintypes.BOOL
            api.GetWindowDisplayAffinity.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
            api.GetWindowDisplayAffinity.restype = wintypes.BOOL
            self._api = api
        return self._api

    def _macos(self):
        if self._api is None:
            api = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
            api.sel_registerName.argtypes = [ctypes.c_char_p]
            api.sel_registerName.restype = ctypes.c_void_p
            # Separate signatures avoid mutating a variadic objc_msgSend binding.
            pointer = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(
                ("objc_msgSend", api)
            )
            getter = ctypes.CFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p)(
                ("objc_msgSend", api)
            )
            setter = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong)(
                ("objc_msgSend", api)
            )
            self._api = api, pointer, getter, setter
        return self._api

    def read(self, handle):
        if not self.supported:
            raise OSError("Capture exclusion is unavailable in this display session.")
        if sys.platform == "win32":
            result = wintypes.DWORD()
            if not self._windows().GetWindowDisplayAffinity(handle, ctypes.byref(result)):
                raise ctypes.WinError(ctypes.get_last_error())
            return result.value
        api, pointer, getter, _setter = self._macos()
        window = pointer(handle, api.sel_registerName(b"window"))
        if not window:
            raise OSError("The native macOS window is not ready.")
        return getter(window, api.sel_registerName(b"sharingType"))

    def apply(self, handle, enabled):
        if not self.supported:
            raise OSError("Capture exclusion is unavailable in this display session.")
        if sys.platform == "win32":
            expected = WDA_EXCLUDEFROMCAPTURE if enabled else WDA_NONE
            if not self._windows().SetWindowDisplayAffinity(handle, expected):
                raise ctypes.WinError(ctypes.get_last_error())
        else:
            api, pointer, _getter, setter = self._macos()
            window = pointer(handle, api.sel_registerName(b"window"))
            if not window:
                raise OSError("The native macOS window is not ready.")
            expected = 0 if enabled else 1  # NSWindowSharingNone / ReadOnly
            setter(window, api.sel_registerName(b"setSharingType:"), expected)
        if self.read(handle) != expected:
            raise OSError("The operating system did not confirm the requested capture setting.")


class CaptureProtection(QObject):
    changed = Signal()

    def __init__(self, owner, enabled=False, *, backend=None):
        super().__init__(owner)
        self.backend = backend or NativeCaptureProtection()
        self.enabled = bool(enabled)
        self._roots = weakref.WeakSet([owner])
        self._applied = weakref.WeakKeyDictionary()
        self._errors = weakref.WeakKeyDictionary()
        self._applying = False
        QApplication.instance().installEventFilter(self)

    def register(self, window):
        self._roots.add(window)
        self.apply_window(window)

    def owns(self, widget):
        current = widget
        while current is not None:
            if current in self._roots:
                return True
            current = current.parent()
        return False

    @property
    def status(self):
        if not self.backend.supported:
            return "Unavailable in this display session."
        if self._errors:
            return "Could not apply capture protection: " + next(iter(self._errors.values()))
        if not self.enabled:
            return "Off · Voice Loop windows can appear in captures."
        if sys.platform == "darwin":
            return "Legacy exclusion requested · modern macOS capture is not blocked."
        return "On · capture exclusion requested for Voice Loop windows."

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        for window in QApplication.topLevelWidgets():
            if self.owns(window):
                self.apply_window(window, force=True)
        self.changed.emit()

    def apply_window(self, window, *, force=False):
        if self._applying or not self.backend.supported or not isValid(window):
            return
        if not window.isWindow() or window.windowHandle() is None:
            return
        if not self.enabled and window not in self._applied and window not in self._errors:
            return
        self._applying = True
        try:
            handle = int(window.winId())
            request = (handle, self.enabled)
            if not force and self._applied.get(window) == request:
                return
            try:
                self.backend.apply(handle, self.enabled)
                self._applied[window] = request
                self._errors.pop(window, None)
            except (OSError, ValueError) as exc:
                self._errors[window] = str(exc)
            self.changed.emit()
        finally:
            self._applying = False

    def eventFilter(self, watched, event):
        if (
            event.type() in (QEvent.Type.Show, QEvent.Type.WinIdChange)
            and isinstance(watched, QWidget)
            and watched.isWindow()
            and self.owns(watched)
        ):
            # Show is delivered before the first exposed frame; WinIdChange also
            # covers native handles recreated by window flags or platform changes.
            self.apply_window(watched, force=True)
        return False

    def close(self):
        QApplication.instance().removeEventFilter(self)
