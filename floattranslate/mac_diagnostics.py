"""Packaged macOS runtime check using synthetic text, no screen/API access."""
import json
import platform
import sys
import traceback
from pathlib import Path


def run(application, filename):
    report = {"platform": platform.platform(), "architecture": platform.machine(), "passed": False}
    try:
        if sys.platform != "darwin":
            raise RuntimeError("This diagnostic requires macOS")
        import AppKit
        import Quartz
        from PIL import Image, ImageDraw, ImageFont
        from .ocr import MacOCR
        from . import __version__
        report["version"] = __version__
        report["appkit_available"] = hasattr(AppKit.NSEvent, "addGlobalMonitorForEventsMatchingMask_handler_")
        report["screen_permission_api"] = hasattr(Quartz, "CGPreflightScreenCaptureAccess")
        image = Image.new("RGB", (1100, 220), "white")
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 64)
        ImageDraw.Draw(image).text((40, 60), "FloatTranslate test 123", fill="black", font=font)
        engine = MacOCR()
        report["ocr_languages"] = engine.languages()
        regions = engine.regions(image, "en-US")
        report["synthetic_ocr_text"] = " ".join(region.text for region in regions)
        report["ocr_passed"] = "test 123" in report["synthetic_ocr_text"].lower()
        from PySide6.QtCore import QEventLoop, QThreadPool, QTimer
        from .tasks import Task
        from .pipeline import Pipeline
        from .providers import Connection
        pool = QThreadPool()
        pool.setMaxThreadCount(1)
        report['worker_checks'] = []
        for language in ('', 'en-US'):
            loop = QEventLoop()
            outcome = []
            def work():
                class SyntheticClient:
                    def __init__(self, connection): pass
                    def translate_blocks(self, model, texts, target, **kwargs):
                        return ['本地模拟译文' for text in texts]
                    def close(self): pass
                pipeline = Pipeline(engine, client_factory=SyntheticClient)
                try:
                    return pipeline.overlay(Connection('custom','https://example.invalid/v1','openai','synthetic'),
                                            'synthetic-model','简体中文',image,language)
                finally:
                    pipeline.close()
            task = Task(language, work)
            def finished(payload):
                outcome.append(payload)
                loop.quit()
            task.signals.finished.connect(finished)
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(loop.quit)
            timer.start(40000)
            pool.start(task)
            loop.exec()
            timer.stop()
            if not outcome:
                raise RuntimeError('Qt worker OCR timed out')
            _, overlays, error = outcome[0]
            if error:
                raise RuntimeError(error)
            passed = bool(overlays) and all(item.translation == '本地模拟译文' for item in overlays)
            report['worker_checks'].append({'language': language or 'auto', 'passed': passed,
                                           'paragraphs': len(overlays), 'translation': 'local mock; no API request'})
        pool.waitForDone()
        report["passed"] = (report["appkit_available"] and report["screen_permission_api"] and report["ocr_passed"]
                            and all(item['passed'] for item in report['worker_checks']))
    except Exception:
        report["error"] = traceback.format_exc()
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    return 0 if report["passed"] else 1
