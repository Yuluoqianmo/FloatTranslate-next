"""Synthetic widget tests must not request desktop privacy permissions."""
import pytest


@pytest.fixture(autouse=True)
def synthetic_capture_permissions(monkeypatch):
    # These tests supply synthetic screenshots / OCR. Real macOS Vision is
    # exercised separately by the packaged --mac-self-test CI step.
    monkeypatch.setattr("floattranslate.frame.screen_permission", lambda request=False: True)
