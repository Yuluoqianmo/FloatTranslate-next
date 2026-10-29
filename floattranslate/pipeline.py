from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass

from PIL import Image

from .providers import Connection, ModelClient, Cancelled
from .layout import OverlayRegion


class LRU:
    def __init__(self, capacity=256):
        self.capacity = capacity
        self.items = OrderedDict()

    def get(self, key):
        if key not in self.items:
            return None
        self.items.move_to_end(key)
        return self.items[key]

    def put(self, key, value):
        self.items[key] = value
        self.items.move_to_end(key)
        while len(self.items) > self.capacity:
            self.items.popitem(last=False)


@dataclass
class Result:
    source: str
    translation: str
    elapsed_ms: int
    cached: bool = False
    unchanged: bool = False


class Pipeline:
    """One serialized worker owns OCR, its bounded caches, and a pooled HTTP client."""

    def __init__(self, ocr, client_factory=ModelClient):
        self.ocr = ocr
        self.client_factory = client_factory
        self.client = None
        self.connection = None
        self.translations = LRU(256)
        self.recognitions = LRU(16)
        self.last_success = None
        self.metrics = {}

    def overlay(self, connection: Connection, model: str, target: str, image: Image.Image, language: str = "", *, on_progress=None, cancelled=None) -> list[OverlayRegion]:
        started=time.monotonic()
        try:
            return self._overlay(connection,model,target,image,language,on_progress=on_progress,cancelled=cancelled)
        finally:
            self.metrics['total_ms']=round((time.monotonic()-started)*1000)

    def _overlay(self, connection: Connection, model: str, target: str, image: Image.Image, language: str = "", *, on_progress=None, cancelled=None) -> list[OverlayRegion]:
        started = time.monotonic()
        self.metrics = {"ocr_ms":0,"api_ms":0,"cache_hits":0,"paragraphs":0,"total_ms":0,"hash_ms":0,"cache_ms":0,"format_ms":0,"first_content_ms":None,"batches":0,"ocr_cached":False,"client_init_ms":0}
        if cancelled and cancelled():
            raise Cancelled("画面已变化")
        digest = hashlib.blake2b(image.tobytes(), digest_size=16).digest()
        image_key = ("regions", image.size, image.mode, digest, language)
        self.metrics['hash_ms']=round((time.monotonic()-started)*1000)
        ocr_started=time.monotonic()
        regions = self.recognitions.get(image_key)
        self.metrics['ocr_cached']=regions is not None
        if regions is None:
            try:
                regions = self.ocr.regions(image, language)
            except Exception as error:
                self.metrics['failed_stage'] = 'ocr'
                raise RuntimeError('本机 OCR 文字识别失败：' + str(error)) from error
            finally:
                self.metrics['ocr_ms'] = round((time.monotonic()-ocr_started)*1000)
            self.recognitions.put(image_key, regions)
        self.metrics["ocr_ms"] = round((time.monotonic()-ocr_started)*1000)
        self.metrics['ocr_backend'] = getattr(self.ocr, 'last_backend', '')
        self.metrics["paragraphs"] = len(regions)
        if not regions:
            return []
        texts = tuple(r.text for r in regions)
        if sum(len(text) for text in texts) > 60000:
            raise ValueError("当前识别范围文字过多，请缩小识别框后重试")
        cache_started=time.monotonic()
        translations = [self.translations.get((connection,model,target,text)) for text in texts]
        self.metrics["cache_hits"] = sum(t is not None for t in translations)
        pending = list(dict.fromkeys(text for text,value in zip(texts,translations) if value is None))
        self.metrics['cache_ms']=round((time.monotonic()-cache_started)*1000)
        def publish():
            if on_progress and not (cancelled and cancelled()):
                on_progress([OverlayRegion(region,value) for region,value in zip(regions,translations) if value is not None])
        publish()
        if pending:
            if connection != self.connection or self.client is None:
                client_started=time.monotonic()
                self.close()
                self.client = self.client_factory(connection)
                self.connection = connection
                self.metrics["client_init_ms"]=round((time.monotonic()-client_started)*1000)
            # Bound one request, and cache by paragraph so overlapping scrolls
            # only translate new text. Render completed JSON elements as SSE arrives.
            batches = []
            batch = []
            length = 0
            for text in pending:
                if batch and (len(batch)>=12 or length+len(text)>6000):
                    batches.append(batch)
                    batch,length = [],0
                batch.append(text)
                length += len(text)
            if batch:
                batches.append(batch)
            api_started = time.monotonic()
            try:
                self.metrics['batches']=len(batches)
                for batch in batches:
                    if cancelled and cancelled():
                        raise Cancelled("画面已变化")
                    def partial(values):
                        by_text = dict(zip(batch, values))
                        for index, text in enumerate(texts):
                            if text in by_text:
                                translations[index] = by_text[text]
                        publish()
                    if on_progress or cancelled:
                        values = self.client.translate_blocks(model,batch,target,on_partial=partial,cancelled=cancelled)
                    else:
                        values = self.client.translate_blocks(model,batch,target)
                    client_metrics=getattr(self.client,'metrics',{})
                    self.metrics['format_ms']+=client_metrics.get('format_ms',0)
                    if self.metrics['first_content_ms'] is None and client_metrics.get('first_content_ms') is not None:
                        self.metrics['first_content_ms']=client_metrics['first_content_ms']
                    for text,value in zip(batch,values):
                        self.translations.put((connection,model,target,text),value)
                        for index,original in enumerate(texts):
                            if original == text:
                                translations[index] = value
                    publish()
            finally:
                self.metrics["api_ms"] = round((time.monotonic()-api_started)*1000)
        self.metrics["total_ms"] = round((time.monotonic()-started)*1000)
        return [OverlayRegion(region, translated) for region, translated in zip(regions, translations)]

    def close(self):
        if self.client:
            self.client.close()
            self.client = None

    def translate(self, connection: Connection, model: str, target: str,
                  *, image: Image.Image | None = None, text: str = "", language: str = "", force=False) -> Result:
        started = time.monotonic()
        if image is not None:
            # Lossless digest: do not miss tiny text changes via fuzzy thumbnail hashing.
            digest = hashlib.blake2b(image.tobytes(), digest_size=16).digest()
            image_key = (image.size, image.mode, digest, language)
            recognized = self.recognitions.get(image_key)
            if recognized is None:
                recognized = self.ocr.recognize(image, language).strip()
                self.recognitions.put(image_key, recognized)
            text = recognized
        text = text.strip()
        if not text:
            return Result("", "", int((time.monotonic() - started) * 1000))
        # A key rotation invalidates cached authentication context, without persisting secrets.
        identity = (connection, model, target, text)
        if identity == self.last_success and not force:
            return Result(text, "", 0, unchanged=True)
        cached = self.translations.get(identity)
        if cached is not None:
            self.last_success = identity
            return Result(text, cached, int((time.monotonic() - started) * 1000), cached=True)
        if connection != self.connection:
            self.close()
            self.client = self.client_factory(connection)
            self.connection = connection
        translated = self.client.translate(model, text, target)
        # Commit only after success. Failed requests remain retryable on identical frames.
        self.translations.put(identity, translated)
        self.last_success = identity
        return Result(text, translated, int((time.monotonic() - started) * 1000))
