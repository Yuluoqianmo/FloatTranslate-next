import json
import threading

import httpx
import pytest
from PIL import Image
from PySide6.QtCore import QPointF, QPoint, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

from floattranslate.frame import RecognitionFrame
from floattranslate.layout import OverlayRegion, TextRegion
from floattranslate.pipeline import Pipeline
from floattranslate.providers import Connection, ModelClient, completed_json_strings, Cancelled


@pytest.mark.parametrize("buffer,expected", [
    ('["你好", "世', ["你好"]),
    ('["a\\"b", "c"]', ['a"b', 'c']),
    ('["a\\', []),
    ('["\\u4f60\\u597d", "b"]', ["你好", "b"]),
    ('```json\n["first", "sec', ["first"]),
    ('not an array', []),
])
def test_stream_partial_json_only_returns_complete_strings(buffer, expected):
    assert completed_json_strings(buffer) == expected


def stream_transport(parts, bodies):
    def handler(request):
        bodies.append(json.loads(request.content))
        events = []
        for text in parts:
            payload = {"choices": [{"delta": {"content": text}}]}
            events.append("data: "+json.dumps(payload,ensure_ascii=False)+"\n\n")
        events.append("data: [DONE]\n\n")
        return httpx.Response(200, headers={"content-type":"text/event-stream"},content="".join(events).encode())
    return httpx.MockTransport(handler)


def test_deepseek_disables_thinking_and_streams_first_paragraph_before_last():
    bodies, updates = [], []
    client = ModelClient(Connection("deepseek","https://api.deepseek.com/v1","openai","synthetic"),
                         stream_transport(['["你好",',' "世界"]'],bodies))
    try:
        result = client.translate_blocks("selected-model",["Hello","World"],"中文",on_partial=lambda values:updates.append(list(values)))
        assert result == ["你好","世界"]
        assert updates[0] == ["你好"] and updates[-1] == result
        assert bodies[0]["stream"] is True and bodies[0]["thinking"] == {"type":"disabled"}
    finally:
        client.close()


def test_unknown_gateway_does_not_receive_deepseek_only_parameters():
    bodies = []
    client = ModelClient(Connection("custom","https://gateway.example/v1","openai","synthetic"),
                         stream_transport(['["你好"]'],bodies))
    try:
        client.translate_blocks("deepseek-any-model",["Hello"],"中文",on_partial=lambda values:None)
        assert "thinking" not in bodies[0]
    finally:
        client.close()


def test_speed_option_can_preserve_provider_thinking_default():
    bodies = []
    client = ModelClient(Connection("deepseek","https://api.deepseek.com/v1","openai","synthetic",False),
                         stream_transport(['["你好"]'],bodies))
    try:
        client.translate_blocks("selected-model",["Hello"],"中文",on_partial=lambda values:None)
        assert "thinking" not in bodies[0]
    finally:
        client.close()


def test_stream_cancellation_stops_stale_translation():
    bodies, updates = [], []
    event = threading.Event()
    client = ModelClient(Connection("custom","https://gateway.example/v1","openai","synthetic"),
                         stream_transport(['["你好",',' "世界"]'],bodies))
    def progress(values):
        updates.append(list(values))
        event.set()
    try:
        with pytest.raises(Cancelled):
            client.translate_blocks("model",["Hello","World"],"中文",on_partial=progress,cancelled=event.is_set)
        assert updates == [["你好"]]
    finally:
        client.close()


def test_gateway_rejecting_stream_falls_back_once():
    bodies = []
    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        if body.get("stream"):
            return httpx.Response(400,json={"error":"Streaming is not supported"})
        return httpx.Response(200,json={"choices":[{"message":{"content":'["你好"]'}}]})
    client = ModelClient(Connection("custom","https://gateway.example/v1","openai","synthetic"),httpx.MockTransport(handler))
    try:
        assert client.translate_blocks("model",["Hello"],"中文",on_partial=lambda values:None) == ["你好"]
        assert len(bodies) == 2 and bodies[0]["stream"] is True and "stream" not in bodies[1]
    finally:
        client.close()


def test_scroll_reuses_individual_paragraphs_and_reanchors():
    class OCR:
        def regions(self,image,language):
            if image.getpixel((0,0)) == (0,0,0):
                return [TextRegion("a",0,0,80,20), TextRegion("b",0,40,80,20)]
            return [TextRegion("b",0,0,80,20), TextRegion("c",0,40,80,20)]
    class Client:
        requests = []
        def __init__(self,connection): pass
        def close(self): pass
        def translate_blocks(self,model,texts,target):
            self.requests.append(texts)
            return ["translated-"+text for text in texts]
    pipeline = Pipeline(OCR(),Client)
    connection = Connection("custom","https://example.com/v1","openai","key")
    pipeline.overlay(connection,"model","中文",Image.new("RGB",(100,100),"black"))
    result = pipeline.overlay(connection,"model","中文",Image.new("RGB",(100,100),"white"))
    assert Client.requests == [["a","b"],["c"]]
    assert result[0].source.y == 0 and result[0].translation == "translated-b"
    assert pipeline.metrics["cache_hits"] == 1 and pipeline.metrics["paragraphs"] == 2
    pipeline.close()


def test_wheel_immediately_clears_masks_and_rejects_old_progress(monkeypatch):
    application = QApplication.instance() or QApplication([])
    frame = RecognitionFrame(test_mode=True)
    frame.show()
    application.processEvents()
    region = OverlayRegion(TextRegion("old",20,20,100,30),"旧译文")
    frame._regions = [region]
    revision = frame._revision
    forwarded = []
    monkeypatch.setattr("floattranslate.frame.forward_wheel",lambda delta,horizontal,**kwargs:forwarded.append((delta,horizontal)) or True)
    event = QWheelEvent(QPointF(50,50),QPointF(150,150),QPoint(),QPoint(0,-120),
                        Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.ScrollUpdate,False)
    QApplication.sendEvent(frame,event)
    assert frame._regions == [] and frame._cancel_scan.is_set()
    assert forwarded == [(-120,False)]
    frame._progress(((revision,1),[region]))
    assert not frame._regions
    frame.close()


def test_background_page_change_clears_overlay_even_with_auto_off(monkeypatch):
    application = QApplication.instance() or QApplication([])
    frame = RecognitionFrame(test_mode=True)
    frame.show()
    application.processEvents()
    frame._hint = False
    frame._excluded = True
    frame._auto = False
    before = Image.new("RGB",(100,100),"white")
    frame._observed_frame = frame._fingerprint(before)
    frame._regions = [OverlayRegion(TextRegion("old",10,10,80,20),"旧译文")]
    monkeypatch.setattr("floattranslate.frame.capture_region",lambda rect:(Image.new("RGB",(100,100),"black"),1))
    frame._watch_view()
    assert not frame._regions and frame._view_unstable and not frame._auto
    frame.close()
