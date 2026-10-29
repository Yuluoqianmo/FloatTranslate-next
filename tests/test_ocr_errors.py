import pytest

from PIL import Image
from floattranslate.pipeline import Pipeline
from floattranslate.providers import Connection


def test_local_ocr_error_cannot_be_reported_as_api_authentication_failure():
    class BrokenOCR:
        def regions(self, image, language):
            raise ValueError('NSInvalidArgumentException - key does not exist')
    calls = []
    pipeline = Pipeline(BrokenOCR(), client_factory=lambda connection: calls.append(connection))
    connection = Connection('custom', 'https://example.com/v1', 'openai', 'synthetic')
    with pytest.raises(RuntimeError, match='本机 OCR 文字识别失败'):
        pipeline.overlay(connection, 'model', '简体中文', Image.new('RGB', (200,100)))
    assert not calls
    assert pipeline.metrics['failed_stage'] == 'ocr'
    assert pipeline.metrics['api_ms'] == 0
    assert not pipeline.recognitions.items
