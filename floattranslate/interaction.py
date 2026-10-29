"""Forward a wheel gesture to the native window exposed by clearing the mask."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import sys


def forward_wheel(delta: int, horizontal=False, exclude_hwnd=None) -> bool:
    if sys.platform != "win32" or not delta:
        return False
    user32 = ctypes.windll.user32
    point = wintypes.POINT()
    if not user32.GetCursorPos(ctypes.byref(point)):
        return False
    user32.WindowFromPoint.argtypes = [wintypes.POINT]
    user32.WindowFromPoint.restype = wintypes.HWND
    target = user32.WindowFromPoint(point)
    if exclude_hwnd and target == exclude_hwnd:
        # The cursor can sit on a resize edge that remains in our window mask.
        # Never post a wheel back to ourselves: that would create an input loop.
        user32.GetWindow.argtypes = [wintypes.HWND,wintypes.UINT]
        user32.GetWindow.restype = wintypes.HWND
        user32.GetWindowRect.argtypes = [wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        target = user32.GetWindow(exclude_hwnd,2)  # GW_HWNDNEXT
        while target:
            rect = wintypes.RECT()
            if user32.IsWindowVisible(target) and user32.GetWindowRect(target,ctypes.byref(rect)):
                if rect.left <= point.x < rect.right and rect.top <= point.y < rect.bottom:
                    break
            target = user32.GetWindow(target,2)
    if not target:
        return False
    # Posting directly to the exposed window avoids re-injecting a gesture into
    # our overlay and works independently of the inactive-window scroll setting.
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    modifiers = (0x0008 if user32.GetKeyState(0x11) & 0x8000 else 0) | (0x0004 if user32.GetKeyState(0x10) & 0x8000 else 0)
    wparam = ((delta & 0xffff) << 16) | modifiers
    lparam = (point.x & 0xffff) | ((point.y & 0xffff) << 16)
    return bool(user32.PostMessageW(target, 0x020E if horizontal else 0x020A, wparam, lparam))
