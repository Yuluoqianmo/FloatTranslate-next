import hashlib
from dataclasses import replace

import httpx
import pytest

from floattranslate import updates


REPO = "example/FloatTranslate-next"
BASE = f"https://github.com/{REPO}/releases/download/v0.3.10/"
DATA = b"MZ" + b"test executable" * 100


def fixture_release(v="0.3.10"):
    return {"tag_name": "v" + v, "assets": [
        {"name": updates.MANIFEST, "browser_download_url": BASE + updates.MANIFEST},
        {"name": "FloatTranslateNext-0.3.10.exe", "size": len(DATA), "browser_download_url": BASE + "FloatTranslateNext-0.3.10.exe"},
    ], "body": "release notes"}


def manifest():
    return {"product": updates.PRODUCT, "schema": 1, "version": "0.3.10", "assets": {"windows-x64": {
        "name": "FloatTranslateNext-0.3.10.exe", "size": len(DATA), "sha256": hashlib.sha256(DATA).hexdigest()}}}


def connection(releases=None, metadata=None, data=DATA):
    def respond(request):
        assert "authorization" not in request.headers
        if request.url.host == "api.github.com":
            return httpx.Response(200, json=[fixture_release()] if releases is None else releases)
        if request.url.path.endswith(updates.MANIFEST):
            return httpx.Response(200, json=manifest() if metadata is None else metadata)
        return httpx.Response(200, content=data)
    return httpx.Client(transport=httpx.MockTransport(respond))


@pytest.mark.parametrize("value", [REPO, "https://github.com/"+REPO, "https://github.com/"+REPO+".git/"])
def test_repository(value):
    assert updates.repository(value) == REPO


@pytest.mark.parametrize("value", ["FloatTranslate-next", "https://github.com.evil/a/b", "https://user@github.com/a/b", "https://github.com/a/b?x=1", "a/b/c", "a/..", "http://github.com/a/b"])
def test_bad_repository(value):
    with pytest.raises(ValueError):
        updates.repository(value)


def test_semantic_versions_and_product():
    with connection(releases=[fixture_release("0.3.9"), fixture_release()]) as http:
        release = updates.check(REPO, "0.3.9", http=http, target="windows-x64")
    assert release.version == "0.3.10"
    assert updates.version("v0.10.0") > updates.version("0.9.99")
    other = manifest()
    other["product"] = "upstream-overlay"
    with connection(metadata=other) as http:
        assert updates.check(REPO, "0.3.8", http=http, target="windows-x64") is None


@pytest.mark.parametrize("kind", ["draft", "prerelease", "missing_manifest", "old", "other_platform"])
def test_incompatible_releases_ignored(kind):
    release = fixture_release()
    target = "windows-x64"
    if kind in ("draft", "prerelease"):
        release[kind] = True
    if kind == "missing_manifest":
        release["assets"] = []
    if kind == "old":
        release["tag_name"] = "v0.3.7"
    if kind == "other_platform":
        target = "macos-arm64"
    with connection(releases=[release]) as http:
        assert updates.check(REPO, "0.3.8", http=http, target=target) is None


@pytest.mark.parametrize("kind", ["hash", "size", "version", "url", "name"])
def test_malformed_release_rejected(kind):
    metadata = manifest()
    release = fixture_release()
    entry = metadata["assets"]["windows-x64"]
    if kind == "hash": entry["sha256"] = "oops"
    if kind == "size": entry["size"] += 1
    if kind == "version": metadata["version"] = "9.9.9"
    if kind == "url": release["assets"][1]["browser_download_url"] = "https://example.com/file.exe"
    if kind == "name": entry["name"] = "../../danger.exe"
    with connection(releases=[release], metadata=metadata) as http, pytest.raises(ValueError):
        updates.check(REPO, "0.3.8", http=http, target="windows-x64")


def test_download_and_verification(tmp_path):
    progress = []
    with connection() as http:
        release = updates.check(REPO, "0.3.8", http=http, target="windows-x64")
        path = updates.download(release, tmp_path, http=http, progress=progress.append)
    assert path.read_bytes() == DATA
    assert progress[-1] == 100


@pytest.mark.parametrize("data", [DATA[:-1], DATA+b"extra", b"MZ"+b"x"*(len(DATA)-2)])
def test_broken_download_removed(tmp_path, data):
    with connection(data=data) as http:
        release = updates.check(REPO, "0.3.8", http=http, target="windows-x64")
        with pytest.raises(ValueError):
            updates.download(release, tmp_path, http=http)
    assert not list(tmp_path.rglob("*.exe"))
    assert not list(tmp_path.rglob("*.part"))


@pytest.mark.parametrize("code", [403, 404, 429, 500])
def test_http_errors(code):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(code))) as http:
        with pytest.raises((ValueError, httpx.HTTPError)):
            updates.check(REPO, "0.3.8", http=http)


def test_about_lifecycle_and_no_translation(monkeypatch):
    from PySide6.QtWidgets import QApplication, QMenu
    from floattranslate.bookmark import BookmarkFrame
    from floattranslate.hotkey import ToggleHotkey
    application = QApplication.instance() or QApplication([])
    application.setQuitOnLastWindowClosed(False)
    monkeypatch.setattr(ToggleHotkey, "install", lambda *args: None)
    frame = BookmarkFrame(test_mode=True)
    calls = []
    monkeypatch.setattr(frame, "scan", lambda *args, **kwargs: calls.append(True))
    frame.show_about()
    dialog = frame._dialog
    assert dialog.isVisible()
    dialog.repo.setText(REPO)
    assert dialog.save()
    assert frame.settings.update_repo == REPO
    menu = QMenu()
    frame._populate_menu(menu)
    assert any("关于" in action.text() for action in menu.actions())
    dialog.close()
    application.processEvents()
    assert frame._dialog is None and frame.bookmark.isVisible()
    assert not calls
    frame.close()
    application.processEvents()


def test_background_check_and_download_survive_dialog_close(monkeypatch, tmp_path):
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from floattranslate.bookmark import BookmarkFrame
    from floattranslate.hotkey import ToggleHotkey
    from floattranslate import about
    application = QApplication.instance() or QApplication([])
    application.setQuitOnLastWindowClosed(False)
    monkeypatch.setattr(ToggleHotkey, "install", lambda *args: None)
    monkeypatch.setattr(about, "config_dir", lambda: tmp_path)
    # Retain the real functions while replacing only their network transport.
    real_check, real_download = updates.check, updates.download
    def do_check(repo, current):
        with connection() as http:
            return real_check(repo, current, http=http, target="windows-x64")
    def do_download(release, directory, progress):
        with connection() as http:
            return real_download(release, directory, http=http, progress=progress)
    monkeypatch.setattr(updates, "check", do_check)
    monkeypatch.setattr(updates, "download", do_download)
    frame = BookmarkFrame(test_mode=True)
    frame.settings = replace(frame.settings, update_repo=REPO)
    frame.show_about()
    frame.updater.check()
    frame._dialog.close()
    for _ in range(100):
        QTest.qWait(10)
        if not frame.updater.busy: break
    assert frame.updater.release.version == "0.3.10"
    frame.updater.download()
    for _ in range(100):
        QTest.qWait(10)
        if not frame.updater.busy: break
    assert frame.updater.downloaded.read_bytes() == DATA
    assert frame.updater.progress == 100
    frame.show_about()
    assert "校验完成" in frame._dialog.status.text()
    frame._dialog.close()
    frame.close()
    application.processEvents()
