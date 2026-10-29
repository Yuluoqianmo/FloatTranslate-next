from PIL import Image,ImageDraw
import sys
import pytest
from PySide6.QtCore import QPoint,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from floattranslate.frame import RecognitionFrame,interaction_at,DRAG_BAR_HEIGHT
from floattranslate.scene import Scene,changed
from floattranslate.layout import OverlayRegion,TextRegion
from floattranslate.providers import Connection


def test_visual_comparison_ignores_caret_and_small_color_noise():
    image = Image.new("RGB",(720,400),"white")
    baseline = Scene.capture(image)
    caret = image.copy()
    ImageDraw.Draw(caret).rectangle((200,100,200,120),fill="black")
    assert not changed(baseline,Scene.capture(caret))
    assert not changed(baseline,Scene.capture(Image.new("RGB",image.size,(253,253,253))))
    text = image.copy()
    ImageDraw.Draw(text).rectangle((150,100,190,115),fill="black")
    assert changed(baseline,Scene.capture(text))
    assert changed(baseline,Scene.capture(Image.new("RGB",(721,400),"white")))


def test_movement_band_and_large_resize_corners():
    for x in (40,100,360,600,680):
        assert interaction_at(QPoint(x,18),720,400) == ""
    for point,edge in [((20,20),"tl"),((700,20),"tr"),((20,380),"bl"),((700,380),"br")]:
        assert interaction_at(QPoint(*point),720,400) == edge
    assert interaction_at(QPoint(3,200),720,400) == "l"
    assert interaction_at(QPoint(10,200),720,400) == ""


@pytest.mark.skipif(sys.platform != "win32", reason="Windows shaped-window native mask")
def test_native_mask_is_not_reset_when_unchanged():
    application = QApplication.instance() or QApplication([])
    frame = RecognitionFrame(test_mode=True)
    frame.show()
    application.processEvents()
    calls = []
    original = frame.setMask
    frame.setMask = lambda mask:(calls.append(mask),original(mask))[-1]
    frame._update_native_mask()
    frame._update_native_mask()
    assert not calls
    frame._regions = [OverlayRegion(TextRegion("hello",20,30,100,30),"你好")]
    frame._update_native_mask()
    frame._update_native_mask()
    assert len(calls) == 1
    assert frame.mask().contains(QPoint(80,18))
    frame.close()


def test_static_auto_scan_skips_worker_animation_and_mask_reset(monkeypatch):
    application = QApplication.instance() or QApplication([])
    frame = RecognitionFrame(test_mode=True)
    frame.show()
    application.processEvents()
    frame._excluded = True
    image = Image.new("RGB",(300,200),"white")
    connection = Connection("custom","http://localhost:1234/v1","openai","")
    region = OverlayRegion(TextRegion("hello",20,20,100,30),"你好")
    class Pipeline:
        calls = 0
        metrics = {}
        def overlay(self,*args,**kwargs):
            self.calls += 1
            if kwargs.get("on_progress"):
                kwargs["on_progress"]([region])
            return [region]
        def close(self): pass
    frame.pipeline = Pipeline()
    monkeypatch.setattr(frame,"_connection",lambda:connection)
    monkeypatch.setattr("floattranslate.frame.capture_region",lambda rect:(image,1.0))
    frame.scan(force=True)
    for _ in range(100):
        QTest.qWait(10)
        if not frame._busy and not frame._capture_pending:
            break
    assert frame.pipeline.calls == 1 and frame._regions == [region]
    masks = []
    original = frame.setMask
    frame.setMask = lambda mask:(masks.append(mask),original(mask))[-1]
    for _ in range(4):
        frame.scan()
        QTest.qWait(30)
        assert not frame._busy and not frame.animation_timer.isActive()
        assert frame._regions == [region]
    assert frame.pipeline.calls == 1 and not masks
    # A manual request remains available even for an identical image.
    frame.scan(force=True)
    for _ in range(100):
        QTest.qWait(10)
        if not frame._busy and not frame._capture_pending:
            break
    assert frame.pipeline.calls == 2
    frame.close()


def test_wide_top_band_moves_with_simple_drag():
    application = QApplication.instance() or QApplication([])
    frame = RecognitionFrame(test_mode=True)
    frame.show()
    application.processEvents()
    start = frame.pos()
    QTest.mousePress(frame,Qt.MouseButton.LeftButton,pos=QPoint(80,18))
    QTest.mouseMove(frame,QPoint(130,48))
    QTest.mouseRelease(frame,Qt.MouseButton.LeftButton,pos=QPoint(130,48))
    assert frame.pos() == start+QPoint(50,30)
    assert DRAG_BAR_HEIGHT == 28
    frame.close()
