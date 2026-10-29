import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from floattranslate.frame import RecognitionFrame, edge_at, resized_rect, MIN_WIDTH, MIN_HEIGHT
from floattranslate.layout import OverlayRegion, TextRegion
from floattranslate.settings import Settings
from floattranslate.style import STYLESHEET


@pytest.fixture(scope="module")
def application():
    instance = QApplication.instance() or QApplication([])
    instance.setStyleSheet(STYLESHEET)
    return instance


@pytest.fixture
def frame(application):
    widget = RecognitionFrame(test_mode=True)
    widget.setGeometry(100, 100, 720, 400)
    widget.show()
    application.processEvents()
    yield widget
    widget.close()
    application.processEvents()


@pytest.mark.parametrize("point,edge", [((1,1),"tl"), ((400,1),"t"), ((719,1),"tr"), ((1,200),"l"), ((719,200),"r"), ((1,399),"bl"), ((400,399),"b"), ((719,399),"br"), ((200,200),"")])
def test_all_eight_resize_handles(point, edge):
    assert edge_at(QPoint(*point), 720, 400) == edge


@pytest.mark.parametrize("edge", ["tl", "t", "tr", "l", "r", "bl", "b", "br"])
def test_resize_minimum_and_opposite_edge_anchor(edge):
    start = QRect(100,100,600,400)
    delta = QPoint(1000 if "l" in edge else -1000, 1000 if "t" in edge else -1000)
    result = resized_rect(start, edge, delta)
    assert result.width() >= MIN_WIDTH and result.height() >= MIN_HEIGHT
    if "l" in edge:
        assert result.right() == start.right()
    if "t" in edge:
        assert result.bottom() == start.bottom()


def test_mouse_drag_resizes_and_clears_old_overlay(frame):
    frame._regions = [OverlayRegion(TextRegion("Hello", 10, 10, 100, 30), "你好")]
    QTest.mousePress(frame, Qt.MouseButton.LeftButton, pos=QPoint(718,398))
    QTest.mouseMove(frame, QPoint(818,458))
    QTest.mouseRelease(frame, Qt.MouseButton.LeftButton, pos=QPoint(818,458))
    assert frame.width() == 820 and frame.height() == 460
    assert frame._regions == []


def test_mouse_drag_moves_frame(frame):
    start = frame.pos()
    QTest.mousePress(frame, Qt.MouseButton.LeftButton, pos=QPoint(200,200))
    QTest.mouseMove(frame, QPoint(240,230))
    QTest.mouseRelease(frame, Qt.MouseButton.LeftButton, pos=QPoint(240,230))
    assert frame.pos() == start+QPoint(40,30)


def test_stale_worker_result_does_not_repaint_after_resize(frame):
    frame._set_busy(True)
    revision = frame._revision
    frame.resize(800,450)
    result = [OverlayRegion(TextRegion("Hello",10,10,100,30), "你好")]
    frame._completed(((revision,1.0), result, None))
    assert not frame._busy and frame._regions == []


def test_overlay_respects_retina_scale_and_reduce_motion(frame):
    frame.apply_settings(Settings(reduce_motion=True))
    regions = [OverlayRegion(TextRegion("Hello",40,40,300,60), "你好，世界")]
    frame._completed(((frame._revision,2.0), regions, None))
    assert frame._image_scale == 2.0 and frame._regions == regions
    assert not frame.animation_timer.isActive()
    assert not frame.grab().isNull()


@pytest.mark.parametrize("page,title", [("api","连接你的模型"), ("ocr","识别与语言"), ("appearance","边框与动效")])
def test_preferences_reachable_and_render(frame, application, page, title):
    frame.preferences(page)
    application.processEvents()
    dialog = frame._dialog
    assert dialog is not None
    assert any(label.text() == title for label in dialog.findChildren(__import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel))
    assert not dialog.grab().isNull()
    if page == "ocr":
        frame.preferences_pool.waitForDone(10000)
        application.processEvents()
    dialog.close()
    application.processEvents()
