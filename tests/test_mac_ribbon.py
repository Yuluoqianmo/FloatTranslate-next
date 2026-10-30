"""Exercise macOS ribbon controls and the transparent refracted contour."""
import sys

import pytest
from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from floattranslate.bookmark import BookmarkFrame
from floattranslate.hotkey import ToggleHotkey
from floattranslate.ribbon import paint_contour


@pytest.mark.skipif(sys.platform != 'darwin', reason='macOS ribbon')
def test_ribbon_buttons_drag_and_settings_preserve_desktop_presence(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(ToggleHotkey, 'install', lambda *args: None)
    frame = BookmarkFrame(test_mode=True)
    app.processEvents()
    calls = []
    monkeypatch.setattr(frame, 'queue_manual_translation', lambda delay: calls.append('translate'))
    monkeypatch.setattr(frame, 'clear_translation', lambda: calls.append('original'))
    for widget in (frame, frame.bookmark, frame.halo, frame.transition):
        assert widget.testAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
    QTest.mouseClick(frame.bookmark, Qt.MouseButton.LeftButton, pos=QPoint(24, 64))
    QTest.mouseClick(frame.bookmark, Qt.MouseButton.LeftButton, pos=QPoint(24, 143))
    assert calls == ['translate', 'original']
    # Dragging from an action moves the ribbon instead of triggering that action.
    calls.clear()
    origin = frame.bookmark.pos()
    QTest.mousePress(frame.bookmark, Qt.MouseButton.LeftButton, pos=QPoint(24, 64))
    QTest.mouseMove(frame.bookmark, QPoint(44, 74))
    QTest.mouseRelease(frame.bookmark, Qt.MouseButton.LeftButton, pos=QPoint(24, 64))
    assert frame.bookmark.pos() == origin+QPoint(20, 10)
    assert calls == ['original']
    from dataclasses import replace
    frame.apply_settings(replace(frame.settings, always_on_top=False))
    assert frame.bookmark.isVisible() and not frame.isVisible()
    assert frame.bookmark.testAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
    frame.close()
    app.processEvents()


def test_refraction_moves_only_the_contour_and_reduce_motion_stops_it():
    app = QApplication.instance() or QApplication([])
    def rendered(phase, reduce_motion=False):
        image = QImage(360, 220, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint_contour(painter, QRectF(14, 14, 332, 192), phase=phase,
                      busy=True, paused=False, error=False,
                      reduce_motion=reduce_motion, border_width=2)
        painter.end()
        return image
    a, b = rendered(0), rendered(100)
    assert a != b
    assert a.pixelColor(180, 110).alpha() == 0
    assert b.pixelColor(180, 110).alpha() == 0
    assert rendered(0, True) == rendered(100, True)
