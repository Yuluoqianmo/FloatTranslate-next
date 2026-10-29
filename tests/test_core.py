import json
from dataclasses import replace

import httpx
import pytest
from PIL import Image

from floattranslate.layout import TextRegion, merge_lines
from floattranslate.pipeline import Pipeline, LRU
from floattranslate.providers import Connection, ModelClient, ProviderError, identify, resolve
from floattranslate.settings import Settings, SecretStore, validate_base_url


@pytest.mark.parametrize("url,pid", [
    ("https://api.deepseek.com/v1", "deepseek"),
    ("https://api.siliconflow.cn/v1", "siliconflow"),
    ("https://openrouter.ai/api/v1", "openrouter"),
    ("https://api.siliconflow.cn.attacker.example/v1", "custom"),
    ("https://gateway.example/anthropic", "custom"),
])
def test_identification_uses_exact_hostname(url, pid):
    assert identify(url).id == pid


def test_unknown_key_does_not_guess_a_vendor():
    assert identify("", "sk-unknown").id == "custom"
    assert identify("", "sk-ant-example").id == "anthropic"
    with pytest.raises(ValueError):
        resolve("auto", "", "sk-unknown")


@pytest.mark.parametrize("url", ["http://remote.example/v1", "https://x.example/v1?key=secret", "https://user:pass@x.example", "file:///tmp/api"])
def test_invalid_urls(url):
    with pytest.raises(ValueError):
        validate_base_url(url)


def test_local_ollama_does_not_require_key():
    assert resolve("auto", "http://localhost:11434/v1", "").key == ""


def test_settings_are_atomic_and_secret_free(tmp_path):
    Settings(model="example-model").save(tmp_path)
    data = json.loads((tmp_path/"settings.json").read_text("utf-8"))
    assert "key" not in data and "api_keys" not in data
    assert Settings.load(tmp_path).model == "example-model"
    assert not (tmp_path/"settings.json.tmp").exists()
    (tmp_path/"settings.json").write_text('{"interval_ms": -1, "font_size": 999, "target": null}')
    loaded = Settings.load(tmp_path)
    assert loaded.interval_ms == 700 and loaded.font_size == 28 and loaded.target == "简体中文"


def test_secret_identity_includes_gateway_path():
    assert SecretStore.identity("custom", "https://x/a") != SecretStore.identity("custom", "https://x/b")
    assert SecretStore.identity("custom", "https://x/a/") == SecretStore.identity("custom", "https://x/a")


@pytest.mark.parametrize("protocol", ["openai", "anthropic", "google"])
def test_provider_protocol_and_structured_translation(protocol):
    requests = []
    def handler(request):
        requests.append(request)
        if request.method == "GET":
            if protocol == "google":
                return httpx.Response(200, json={"models": [{"name": "models/example", "supportedGenerationMethods": ["generateContent"]}]})
            return httpx.Response(200, json={"data": [{"id": "example"}]})
        result = '["你好", "世界"]'
        if protocol == "anthropic":
            return httpx.Response(200, json={"content": [{"type": "text", "text": result}]})
        if protocol == "google":
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": result}]}}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": result}}]})
    client = ModelClient(Connection("custom", "https://test.example/v1", protocol, "test-key"), httpx.MockTransport(handler))
    try:
        assert client.models() == ["example"]
        assert client.translate_blocks("example", ["Hello", "World"], "中文") == ["你好", "世界"]
        assert "test-key" not in str(requests[0].url)
        if protocol == "anthropic":
            assert requests[0].headers["x-api-key"] == "test-key"
        elif protocol == "google":
            assert requests[0].headers["x-goog-api-key"] == "test-key"
        else:
            assert requests[0].headers["authorization"] == "Bearer test-key"
    finally:
        client.close()


def test_models_pagination():
    def handler(request):
        if "pageToken" in request.url.params:
            return httpx.Response(200, json={"models": [{"name": "models/b", "supportedGenerationMethods": ["generateContent"]}]})
        return httpx.Response(200, json={"models": [{"name": "models/a", "supportedGenerationMethods": ["generateContent"]}], "nextPageToken": "two"})
    client = ModelClient(Connection("google", "https://test.example", "google", "x"), httpx.MockTransport(handler))
    try:
        assert client.models() == ["a", "b"]
    finally:
        client.close()


def test_bad_provider_body_is_not_exposed():
    client = ModelClient(Connection("custom", "https://test.example", "openai", "do-not-leak"),
                         httpx.MockTransport(lambda request: httpx.Response(500, text="do-not-leak")))
    try:
        with pytest.raises(ProviderError) as error:
            client.models()
        assert "do-not-leak" not in str(error.value)
    finally:
        client.close()


def test_malformed_translation_array_rejected():
    client = ModelClient(Connection("custom", "https://test.example", "openai", "x"),
                         httpx.MockTransport(lambda request: httpx.Response(200, json={"choices": [{"message": {"content": '["only one"]'}}]})))
    try:
        with pytest.raises(ProviderError):
            client.translate_blocks("model", ["a", "b"], "中文")
    finally:
        client.close()


def test_lru_evicts_only_oldest():
    cache = LRU(2)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("a") == 1
    cache.put("c", 3)
    assert cache.get("b") is None and cache.get("a") == 1


def test_merging_preserves_columns_and_headings():
    lines = [TextRegion("Heading", 10, 0, 300, 36),
             TextRegion("First", 10, 65, 150, 20), TextRegion("Column", 350, 65, 150, 20),
             TextRegion("Second", 10, 90, 150, 20), TextRegion("Other", 350, 90, 150, 20)]
    merged = merge_lines(lines)
    assert [r.text for r in merged] == ["Heading", "First\nSecond", "Column\nOther"]
    assert merged[1].height == 45 and merged[1].width == 150


def test_overlay_cache_retries_failure_and_invalidates_context():
    class OCR:
        calls = 0
        def regions(self, image, language):
            self.calls += 1
            return [TextRegion("Hello", 10, 10, 100, 30)]
    class Client:
        calls = 0
        fail = True
        def __init__(self, connection):
            pass
        def close(self):
            pass
        def translate_blocks(self, model, texts, target):
            Client.calls += 1
            if Client.fail:
                Client.fail = False
                raise ProviderError("retry")
            return ["你好"]
    ocr = OCR()
    pipeline = Pipeline(ocr, Client)
    connection = Connection("custom", "https://test.example/v1", "openai", "x")
    image = Image.new("RGB", (200, 100), "white")
    with pytest.raises(ProviderError):
        pipeline.overlay(connection, "model", "中文", image)
    result = pipeline.overlay(connection, "model", "中文", image)
    assert result[0].translation == "你好" and Client.calls == 2 and ocr.calls == 1
    pipeline.overlay(connection, "model", "中文", image)
    assert Client.calls == 2
    pipeline.overlay(connection, "other-model", "中文", image)
    assert Client.calls == 3
    pipeline.overlay(connection, "other-model", "中文", image, "en-US")
    assert ocr.calls == 2
    pipeline.close()
