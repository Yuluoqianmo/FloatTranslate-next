from __future__ import annotations

import asyncio
import io
import sys

from PIL import Image
from .layout import TextRegion, merge_lines


class WindowsOCR:
    def languages(self):
        from winrt.windows.media.ocr import OcrEngine
        return [lang.language_tag for lang in OcrEngine.available_recognizer_languages]

    def recognize(self, image: Image.Image, language: str = "") -> str:
        return "\n".join(r.text for r in self.regions(image, language))

    def regions(self, image: Image.Image, language: str = "") -> list[TextRegion]:
        return asyncio.run(self._recognize(image, language))

    async def _recognize(self, image, language):
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.globalization import Language
        from winrt.windows.graphics.imaging import BitmapDecoder
        from winrt.windows.storage.streams import InMemoryRandomAccessStream, DataWriter
        engine = (OcrEngine.try_create_from_language(Language(language)) if language
                  else OcrEngine.try_create_from_user_profile_languages())
        if engine is None:
            raise RuntimeError("此语言的 Windows OCR 不可用，请在系统设置中添加相应语言的 OCR 组件")
        maximum = OcrEngine.max_image_dimension
        original_width, original_height = image.size
        image = image.copy()
        image.thumbnail((maximum, maximum))
        sx, sy = original_width / image.width, original_height / image.height
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="PNG")
        stream = InMemoryRandomAccessStream()
        writer = DataWriter(stream.get_output_stream_at(0))
        try:
            writer.write_bytes(buffer.getvalue())
            await writer.store_async()
            await writer.flush_async()
            stream.seek(0)
            decoder = await BitmapDecoder.create_async(stream)
            bitmap = await decoder.get_software_bitmap_async()
            try:
                result = await engine.recognize_async(bitmap)
                lines = []
                for line in result.lines:
                    words = list(line.words)
                    if not words:
                        continue
                    left = min(word.bounding_rect.x for word in words)
                    top = min(word.bounding_rect.y for word in words)
                    right = max(word.bounding_rect.x + word.bounding_rect.width for word in words)
                    bottom = max(word.bounding_rect.y + word.bounding_rect.height for word in words)
                    lines.append(TextRegion(line.text, left * sx, top * sy, (right-left) * sx, (bottom-top) * sy))
                return merge_lines(lines)
            finally:
                bitmap.close()
        finally:
            writer.close()
            stream.close()


class MacOCR:
    """Apple Vision, imported only on macOS. No OCR model download."""

    def languages(self):
        import Vision
        import objc
        with objc.autorelease_pool():
            request = Vision.VNRecognizeTextRequest.alloc().init()
            request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
            languages, error = request.supportedRecognitionLanguagesAndReturnError_(None)
            if error:
                raise RuntimeError("无法获取 Apple Vision 支持的语言")
            return list(languages)

    def recognize(self, image: Image.Image, language: str = "") -> str:
        return "\n".join(r.text for r in self.regions(image, language))

    def regions(self, image: Image.Image, language: str = "") -> list[TextRegion]:
        import Vision
        import Foundation
        import Quartz
        import objc
        with objc.autorelease_pool():
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, format="PNG")
            data = Foundation.NSData.dataWithBytes_length_(buffer.getvalue(), len(buffer.getvalue()))
            request = Vision.VNRecognizeTextRequest.alloc().init()
            request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
            request.setUsesLanguageCorrection_(True)
            if language:
                request.setRecognitionLanguages_([language])
            elif hasattr(request, "setAutomaticallyDetectsLanguage_"):
                request.setAutomaticallyDetectsLanguage_(True)
            # Decode with ImageIO and pass a native CGImage. Vision 27's
            # encoded-data reader rejects this Python/PyObjC input path.
            source = Quartz.CGImageSourceCreateWithData(data, None)
            cg_image = Quartz.CGImageSourceCreateImageAtIndex(source, 0, None) if source else None
            if cg_image is None:
                raise RuntimeError('无法解码本机 OCR 截图')
            # Optional dictionary keys must return nil rather than KeyError.
            options = Foundation.NSDictionary.dictionary()
            handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg_image, options)
            ok, error = handler.performRequests_error_([request], None)
            if not ok or error:
                raise RuntimeError("Apple Vision 识别失败：" + str(error or '未返回识别结果'))
            lines = []
            for observation in request.results() or []:
                candidates = observation.topCandidates_(1)
                if candidates:
                    box = observation.boundingBox()
                    lines.append(TextRegion(str(candidates[0].string()), box.origin.x * image.width,
                                            (1 - box.origin.y - box.size.height) * image.height,
                                            box.size.width * image.width, box.size.height * image.height))
            return merge_lines(lines)


def create_ocr():
    if sys.platform == "win32":
        return WindowsOCR()
    if sys.platform == "darwin":
        # Register PyObjC framework metadata on the GUI thread before the
        # preferences/OCR pools can import it concurrently with Qt and GC.
        import AppKit
        import Foundation
        import Quartz
        import Vision
        return MacOCR()
    raise RuntimeError("当前支持 Windows 和 macOS；Linux OCR 后端尚未实现")


def screen_permission(request: bool = False) -> bool:
    if sys.platform != "darwin":
        return True
    import Quartz
    if Quartz.CGPreflightScreenCaptureAccess():
        return True
    if request:
        Quartz.CGRequestScreenCaptureAccess()
    return False
