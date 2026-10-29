from __future__ import annotations

import ctypes
import sys
import math

from PIL import Image
from PySide6.QtCore import QRect
from PySide6.QtGui import QGuiApplication, QImage


def exclude_from_capture(window) -> bool:
    """Windows 10 2004+: capture underlying content instead of our own translation."""
    if sys.platform != "win32":
        return False
    try:
        user32 = ctypes.windll.user32
        user32.SetWindowDisplayAffinity.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        user32.SetWindowDisplayAffinity.restype = ctypes.c_bool
        return bool(user32.SetWindowDisplayAffinity(int(window.winId()), 0x11))
    except (OSError, AttributeError):
        return False


def capture_region(rect: QRect) -> tuple[Image.Image, float]:
    """Composite intersections in global logical coordinates at a uniform DPR.

    Handles negative screen origins and mixed Retina/normal displays. QScreen
    captures must run on the GUI thread; OCR/network run on a worker thread.
    """
    screens = [screen for screen in QGuiApplication.screens() if screen.geometry().intersects(rect)]
    if not screens:
        raise RuntimeError("识别框不在可用屏幕内，请移动到屏幕上")
    scale = max(screen.devicePixelRatio() for screen in screens)
    # Bound transient screenshot memory for very large / mixed-DPI desktops.
    scale = min(scale, math.sqrt(12_000_000/max(1, rect.width()*rect.height())))
    result = Image.new("RGB", (max(1, round(rect.width()*scale)), max(1, round(rect.height()*scale))), "white")
    for screen in screens:
        intersection = screen.geometry().intersected(rect)
        local = intersection.translated(-screen.geometry().topLeft())
        shot = screen.grabWindow(0, local.x(), local.y(), local.width(), local.height())
        if shot.isNull():
            raise RuntimeError("无法截取屏幕，请检查系统的屏幕录制权限")
        image = shot.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
        pixels = Image.frombytes("RGBA", (image.width(), image.height()), bytes(image.constBits()), "raw", "RGBA", image.bytesPerLine())
        size = (max(1, round(intersection.width()*scale)), max(1, round(intersection.height()*scale)))
        if pixels.size != size:
            pixels = pixels.resize(size, Image.Resampling.LANCZOS)
        result.paste(pixels.convert("RGB"), (round((intersection.x()-rect.x())*scale), round((intersection.y()-rect.y())*scale)))
    return result, scale
