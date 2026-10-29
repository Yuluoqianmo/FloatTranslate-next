from contextlib import nullcontext
from types import SimpleNamespace
import sys

from PIL import Image
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication

from floattranslate import capture
from floattranslate.ocr import MacOCR
from floattranslate.hotkey import mac_modifier_flags


def test_mac_hotkey_modifiers_follow_qt_command_control_semantics():
    assert mac_modifier_flags(Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier) == (1 << 20) | (1 << 19)
    assert mac_modifier_flags(Qt.KeyboardModifier.MetaModifier) == 1 << 18
    assert mac_modifier_flags(Qt.KeyboardModifier.ShiftModifier) == 1 << 17


def test_capture_negative_origin_and_mixed_dpi(monkeypatch):
    application = QApplication.instance() or QApplication([])
    class Screen:
        def __init__(self, rect, dpr, color):
            self.rect, self.dpr, self.color = rect, dpr, color
            self.request = None
        def geometry(self):
            return self.rect
        def devicePixelRatio(self):
            return self.dpr
        def grabWindow(self, window, x, y, width, height):
            self.request = (x,y,width,height)
            result = QPixmap(round(width*self.dpr), round(height*self.dpr))
            result.fill(QColor(self.color))
            result.setDevicePixelRatio(self.dpr)
            return result
    left = Screen(QRect(-200,0,200,100), 2, "red")
    right = Screen(QRect(0,0,200,100), 1, "blue")
    monkeypatch.setattr(capture.QGuiApplication, "screens", lambda: [left, right])
    image, scale = capture.capture_region(QRect(-150,20,200,60))
    assert scale == 2 and image.size == (400,120)
    assert left.request == (50,20,150,60) and right.request == (0,20,50,60)
    assert image.getpixel((299,59)) == (255,0,0)
    assert image.getpixel((300,59)) == (0,0,255)


def test_mac_vision_bottom_left_coordinates_convert_to_top_left(monkeypatch):
    # Validate conversion against a fixture without claiming a real Mac execution.
    box = SimpleNamespace(origin=SimpleNamespace(x=0.1,y=0.2), size=SimpleNamespace(width=0.5,height=0.1))
    observation = SimpleNamespace(boundingBox=lambda: box,
                                  topCandidates_=lambda count: [SimpleNamespace(string=lambda: "Hello")])
    class Request:
        @classmethod
        def alloc(cls): return cls()
        def init(self): return self
        def setRecognitionLevel_(self, value): pass
        def setUsesLanguageCorrection_(self, value): pass
        def setRecognitionLanguages_(self, value): self.languages = value
        def results(self): return [observation]
    class Handler:
        @classmethod
        def alloc(cls): return cls()
        def initWithCGImage_options_(self, data, options): return self
        def performRequests_error_(self, requests, error): return True, None
    monkeypatch.setitem(sys.modules,"Vision", SimpleNamespace(VNRecognizeTextRequest=Request, VNImageRequestHandler=Handler, VNRequestTextRecognitionLevelAccurate=1))
    monkeypatch.setitem(sys.modules,"Foundation", SimpleNamespace(
        NSData=SimpleNamespace(dataWithBytes_length_=lambda data,length:data),
        NSDictionary=SimpleNamespace(dictionary=lambda: {})))
    monkeypatch.setitem(sys.modules,"objc", SimpleNamespace(autorelease_pool=nullcontext))
    monkeypatch.setitem(sys.modules,"Quartz", SimpleNamespace(
        CGImageSourceCreateWithData=lambda data,options: data,
        CGImageSourceCreateImageAtIndex=lambda source,index,options: source))
    regions = MacOCR().regions(Image.new("RGB", (1000,500)), "en-US")
    assert len(regions) == 1
    box = regions[0]
    assert box.x == 100 and round(box.y) == 350 and box.width == 500 and box.height == 50

    calls = []
    def perform(cg_image, language, *, fast):
        calls.append(fast)
        if not fast:
            raise RuntimeError('TextRecognition.CRImageReaderError.unknownError')
        return Request.alloc().init()
    monkeypatch.setattr(MacOCR, '_perform', staticmethod(perform))
    engine = MacOCR()
    assert engine.regions(Image.new('RGB',(1000,500)), 'en-US')
    assert engine.regions(Image.new('RGB',(1000,500)), 'en-US')
    assert calls == [False, True, True]
    assert engine.last_backend == 'Apple Vision（兼容识别）'
