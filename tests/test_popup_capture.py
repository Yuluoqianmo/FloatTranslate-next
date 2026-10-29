from PIL import Image
from PySide6.QtWidgets import QApplication

from floattranslate.frame import RecognitionFrame
from floattranslate.layout import OverlayRegion, TextRegion


def test_popup_is_not_mistaken_for_changed_page(monkeypatch):
    application = QApplication.instance() or QApplication([])
    frame = RecognitionFrame(test_mode=True)
    frame.show()
    application.processEvents()
    frame._excluded = True
    region = OverlayRegion(TextRegion("hello",20,20,100,30),"你好")
    frame._regions = [region]
    calls = []
    monkeypatch.setattr("floattranslate.frame.capture_region",lambda rect:calls.append(rect) or (Image.new("RGB",(100,100)),1))
    monkeypatch.setattr(QApplication,"activePopupWidget",lambda:frame)
    frame._watch_view()
    frame.scan(force=True)
    assert not calls and frame._regions == [region]
    frame.close()
