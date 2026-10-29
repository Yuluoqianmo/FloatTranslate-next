"""Opt-in local smoke test. Uses synthetic text and a localhost model fixture.

No external model request or user credential is used. Run on a real desktop;
macOS screen-recording authorization must be granted manually if requested.
"""
from __future__ import annotations

import json
import sys
import threading
import time
import traceback
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QCursor, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu, QWidget, QPushButton

from .capture import capture_region
from .frame import RecognitionFrame
from .providers import Connection, ModelClient
from .settings import Settings
from .settings import SecretStore


class Document(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("FloatTranslate · synthetic test document")
        self.scroll_offset = 0
        self.resize(1120, 750)
        self.move(80, 65)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#f4f6fa"))
        p.fillRect(QRect(24, 24, self.width()-48, self.height()-48), QColor("#ffffff"))
        p.translate(0,-self.scroll_offset)
        p.setPen(QColor("#858d9f"))
        p.setFont(QFont("Arial", 11))
        p.drawText(60, 65, "FLOATTRANSLATE / LOCAL TEST DOCUMENT")
        p.setPen(QColor("#222838"))
        p.setFont(QFont("Arial", 28, QFont.Weight.DemiBold))
        p.drawText(60, 145, "Make room for better ideas.")
        p.setFont(QFont("Arial", 16))
        for y, text in [
            (220,"Let technology fit into your work, not interrupt your thinking."),
            (310,"Select the text you want to understand."),
            (350,"The translation appears at the original position."),
            (450,"Keep the rhythm of reading, and the structure of the page."),
        ]:
            p.drawText(60, y, text)
        p.setPen(QColor("#9299a8"))
        p.setFont(QFont("Arial", 12))
        p.drawText(60, 625, "A calmer workspace gives your ideas room to grow.")
        p.drawText(60, 660, "This is a local test fixture. No remote model is called.")
        p.end()

    def wheelEvent(self,event):
        self.scroll_offset = max(0,self.scroll_offset-round(event.angleDelta().y()/3))
        self.update()
        event.accept()


class MockModel(BaseHTTPRequestHandler):
    calls = 0
    def log_message(self, *args):
        pass

    def do_GET(self):
        data = json.dumps({"data": [{"id": "local-test-model"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        MockModel.calls += 1
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        texts = json.loads(body["messages"][-1]["content"])
        translations = []
        for text in texts:
            lower = text.lower()
            if "better" in lower or "ideas" in lower:
                value = "为更好的想法留出空间。"
            elif "technology" in lower or "interrupt" in lower:
                value = "让技术融入你的工作，而不是打断你的思路。"
            elif "rhythm" in lower or "structure" in lower:
                value = "保留阅读节奏，也保留页面原有的结构。"
            elif "select" in lower:
                value = "选择需要理解的文字。"
            elif "translation" in lower or "position" in lower:
                value = "译文会在原文的位置自然呈现。"
            else:
                value = "本地识别与覆盖翻译测试。"
            translations.append(value)
        data = json.dumps({"choices": [{"message": {"content": json.dumps(translations, ensure_ascii=False)}}]}, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)


def wait_until(application, predicate, timeout=30):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        application.processEvents()
        if predicate():
            return
        QTest.qWait(25)
    raise RuntimeError("Local smoke test timed out")


def save_document_view(document, filename):
    # The crop is restricted to our own synthetic document window.
    image, _ = capture_region(document.geometry())
    image.save(filename)


def run_lifecycle(application, frame):
    """Use QApplication.exec(), not just processEvents, to catch auto-quit."""
    class MemorySecrets(SecretStore):
        def get(self, identity):
            return self._session.get(identity, "")
        def set(self, identity, key):
            self._session[identity] = key
            return True

    original_secrets = frame.secrets
    original_settings = frame.settings
    frame.secrets = MemorySecrets()
    cases = [(page, action) for page in ("api", "ocr", "appearance") for action in ("save", "cancel", "close", "escape")]
    cases.append(("appearance", "toggle_top"))
    state = {"passed": False, "cases": []}
    expected_geometry = frame.geometry()

    def verify(page, action):
        try:
            assert frame.isVisible() and frame._dialog is None and not frame._closing
            assert frame.windowOpacity() == 1 and frame.geometry() == expected_geometry
            state["cases"].append(page+":"+action)
            step()
        except Exception:
            state["error"] = traceback.format_exc()
            application.quit()

    def step():
        if not cases:
            state["passed"] = True
            application.quit()
            return
        page, action = cases.pop(0)
        try:
            frame.preferences(page)
            dialog = frame._dialog
            if page == "api":
                dialog.url.setText("https://gateway.example/v1")
                dialog.key.setText("synthetic-local-test-key")
                dialog.model.setEditText("local-test-model")
            if action == "toggle_top":
                dialog.on_top.setChecked(not dialog.on_top.isChecked())
            def finish():
                try:
                    if action in ("save", "toggle_top"):
                        QTest.mouseClick(dialog.save_button, Qt.MouseButton.LeftButton)
                    elif action == "cancel":
                        button = next(b for b in dialog.findChildren(QPushButton) if b.text() == "取消")
                        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
                    elif action == "escape":
                        QTest.keyClick(dialog, Qt.Key.Key_Escape)
                    else:
                        dialog.close()
                    QTimer.singleShot(120, lambda: verify(page, action))
                except Exception:
                    state["error"] = traceback.format_exc()
                    application.quit()
            QTimer.singleShot(100, finish)
        except Exception:
            state["error"] = traceback.format_exc()
            application.quit()

    watchdog = QTimer()
    watchdog.setSingleShot(True)
    watchdog.timeout.connect(application.quit)
    watchdog.start(15000)
    QTimer.singleShot(0, step)
    application.exec()
    watchdog.stop()
    frame.secrets = original_secrets
    frame.apply_settings(original_settings)
    return state


def run(application, directory):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    report = {"passed": False, "model": "localhost fixture (not a live translation provider)"}
    document = None
    frame = None
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockModel)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/v1"
        client = ModelClient(Connection("custom", url, "openai", ""))
        try:
            assert client.models() == ["local-test-model"]
        finally:
            client.close()
        document = Document()
        document.show()
        document.raise_()
        document.activateWindow()
        QTest.qWait(200)
        settings = Settings(provider="custom", base_url=url, model="local-test-model", font_size=22)
        frame = RecognitionFrame(settings, test_mode=True)
        hide_requests = []
        original_opacity = frame.setWindowOpacity
        def opacity(value):
            if value == 0:
                hide_requests.append(value)
            original_opacity(value)
        frame.setWindowOpacity = opacity
        frame._hint = False
        frame.setGeometry(document.x()+42, document.y()+88, 930, 430)
        frame.show()
        frame.raise_()
        QTest.qWait(200)
        report["capture_exclusion"] = frame._excluded
        report["ocr_languages"] = frame.ocr.languages()
        frame.scan(force=True)
        wait_until(application, lambda: not frame._busy and not frame._capture_pending)
        assert frame._regions, frame._last_status
        assert frame._last_translation, frame._last_status
        assert 4 <= len(frame._regions) <= 8, "Test document was obscured by another window"
        assert "technology" in frame._last_source.lower() and "rhythm" in frame._last_source.lower(), "Synthetic document is not fully visible"
        report["regions"] = len(frame._regions)
        report["recognized_source"] = frame._last_source
        report["overlay_bounds"] = [[round(i.source.x,2), round(i.source.y,2), round(i.source.width,2), round(i.source.height,2)] for i in frame._regions]
        QTest.qWait(220)
        # Capture visual evidence with exclusion temporarily disabled.
        frame.view_timer.stop()
        frame._menu_open = True
        if frame._excluded:
            import ctypes
            ctypes.windll.user32.SetWindowDisplayAffinity(int(frame.winId()), 0)
        QTest.qWait(100)
        save_document_view(document, directory/"overlay.png")
        menu = QMenu(frame)
        frame._populate_menu(menu)
        menu.popup(document.mapToGlobal(QPoint(document.width()-290, 100)))
        QTest.qWait(100)
        save_document_view(document, directory/"context-menu.png")
        menu.close()
        if frame._excluded:
            frame._refresh_capture_exclusion()
        frame._menu_open = False
        if frame._excluded:
            frame.view_timer.start()
        # Validate a second scan never OCRs our own Chinese masks.
        calls = MockModel.calls
        frame.scan(force=True)
        wait_until(application, lambda: not frame._busy and not frame._capture_pending)
        assert "technology" in frame._last_source.lower() or "select" in frame._last_source.lower(), frame._last_source
        assert MockModel.calls == calls, "Unchanged frame did not reuse translation cache"
        report["self_capture_excluded"] = True
        report["unchanged_frame_cache"] = True
        if frame._excluded:
            # Observe several actual periodic timer ticks on a static document.
            # Neither the worker nor SetWindowRgn should be restarted.
            calls_before = MockModel.calls
            mask_changes = []
            busy_changes = []
            original_mask = frame.setMask
            original_busy = frame._set_busy
            frame.setMask = lambda mask:(mask_changes.append(1),original_mask(mask))[-1]
            frame._set_busy = lambda busy:(busy_changes.append(busy),original_busy(busy))[-1]
            frame.set_auto(True)
            QTest.qWait(4700)
            frame.set_auto(False)
            frame.setMask = original_mask
            frame._set_busy = original_busy
            assert not mask_changes and not any(busy_changes) and MockModel.calls == calls_before
            assert frame._regions and not frame.animation_timer.isActive()
            report["static_timer_mask_changes"] = len(mask_changes)
            report["static_timer_worker_starts"] = sum(bool(value) for value in busy_changes)
            # The enlarged band is hit-testable well away from the center grip.
            assert frame.mask().contains(QPoint(80,18))
            before_move = frame.pos()
            QTest.mousePress(frame,Qt.MouseButton.LeftButton,pos=QPoint(80,18))
            QTest.mouseMove(frame,QPoint(110,38))
            QTest.mouseRelease(frame,Qt.MouseButton.LeftButton,pos=QPoint(110,38))
            assert frame.pos() == before_move+QPoint(30,20)
            frame.move(before_move)
            frame.scan(force=True)
            wait_until(application,lambda:not frame._busy and not frame._capture_pending)
            assert frame._regions,frame._last_status
            report["wide_drag_band"] = True
        if frame._excluded:
            # Test real native wheel forwarding through an occupied text mask.
            first = frame._regions[0].source
            local = frame.content_rect().topLeft()+QPoint(round(first.x/frame._image_scale+18),round(first.y/frame._image_scale+10))
            global_point = frame.mapToGlobal(local)
            QCursor.setPos(global_point)
            wheel = QWheelEvent(QPointF(local),QPointF(global_point),QPoint(),QPoint(0,-120),Qt.MouseButton.NoButton,
                                Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.ScrollUpdate,False)
            QApplication.sendEvent(frame,wheel)
            assert not frame._regions, "Wheel kept stale masks visible"
            wait_until(application,lambda:document.scroll_offset>0,timeout=3)
            report["wheel_forwarded"] = True
            document.scroll_offset = 0
            document.repaint()
            frame.scan(force=True)
            wait_until(application,lambda:not frame._busy and not frame._capture_pending)
            assert frame._regions, frame._last_status
            started = time.monotonic()
            document.scroll_offset = 50
            document.repaint()
            wait_until(application,lambda:not frame._regions,timeout=2)
            report["scroll_clear_ms"] = round((time.monotonic()-started)*1000)
            document.scroll_offset = 0
            document.repaint()
            frame.scan(force=True)
            wait_until(application,lambda:not frame._busy and not frame._capture_pending)
            assert frame._regions,frame._last_status
        original = frame.size()
        QTest.mousePress(frame, Qt.MouseButton.LeftButton, pos=QPoint(frame.width()-2, frame.height()-2))
        QTest.mouseMove(frame, QPoint(original.width()-102, original.height()-62))
        QTest.mouseRelease(frame, Qt.MouseButton.LeftButton, pos=QPoint(frame.width()-2, frame.height()-2))
        assert frame.width() == original.width()-100 and frame.height() == original.height()-60
        assert not frame._regions
        report["drag_resize"] = [frame.width(), frame.height()]
        frame.scan(force=True)
        wait_until(application, lambda: not frame._busy and not frame._capture_pending)
        assert frame._regions, frame._last_status
        report["rescan_after_resize"] = True
        if frame._excluded:
            import ctypes
            frame.view_timer.stop()
            frame._menu_open = True
            ctypes.windll.user32.SetWindowDisplayAffinity(int(frame.winId()), 0)
        QTest.qWait(200)
        save_document_view(document, directory/"resized.png")
        if frame._excluded:
            frame._refresh_capture_exclusion()
        frame._menu_open = False
        frame.preferences("api")
        QTest.qWait(100)
        frame._dialog.grab().save(str(directory/"api-settings.png"))
        frame._dialog.close()
        application.processEvents()
        report["settings"] = True
        report["timings_ms"] = dict(frame._metrics)
        report["capture_hide_requests"] = len(hide_requests)
        if sys.platform == "win32":
            assert frame._excluded and not hide_requests, "Windows capture hid the frame"
        import uuid
        identity = "self-test-"+uuid.uuid4().hex
        secrets = SecretStore()
        try:
            durable = secrets.set(identity, "local-self-test-not-a-real-api-key")
            report["credentials_persistent"] = durable
            if durable:
                assert SecretStore().get(identity) == "local-self-test-not-a-real-api-key"
        finally:
            secrets.set(identity, "")
        # Keep the diagnostic settings separate from the user's existing config.
        import os
        old_config_dir = os.environ.get("FLOATTRANSLATE_CONFIG_DIR")
        os.environ["FLOATTRANSLATE_CONFIG_DIR"] = str(directory/"lifecycle-config")
        document.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        try:
            report["lifecycle"] = run_lifecycle(application, frame)
            assert report["lifecycle"]["passed"], report["lifecycle"]
        finally:
            if old_config_dir is None:
                os.environ.pop("FLOATTRANSLATE_CONFIG_DIR", None)
            else:
                os.environ["FLOATTRANSLATE_CONFIG_DIR"] = old_config_dir
        report["passed"] = True
    except Exception:
        report["error"] = traceback.format_exc()
    finally:
        if frame:
            frame.close()
            wait_until(application, lambda: not frame.worker_pool.activeThreadCount() and not frame.preferences_pool.activeThreadCount())
            application.processEvents()
            frame.close()
        if document:
            document.close()
        server.shutdown()
        server.server_close()
        (directory/"report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    return 0 if report["passed"] else 1
