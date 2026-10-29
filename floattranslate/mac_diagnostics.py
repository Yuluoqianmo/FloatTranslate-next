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
        report["passed"] = report["appkit_available"] and report["screen_permission_api"] and report["ocr_passed"]
    except Exception:
        report["error"] = traceback.format_exc()
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    return 0 if report["passed"] else 1
