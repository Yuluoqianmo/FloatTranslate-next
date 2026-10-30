"""Native Cocoa check, opt-in so headless CI never displays desktop tools.

Run on a Mac with FLOATTRANSLATE_NATIVE_WINDOWS=1. Uses synthetic OCR and no
screen capture, network request, global key monitor, or privacy authorization.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.skipif(sys.platform != 'darwin' or os.environ.get('FLOATTRANSLATE_NATIVE_WINDOWS') != '1',
                    reason='opt-in native Cocoa desktop test')
def test_glass_and_desktop_presence_survive_deactivation_and_flag_recreation(tmp_path):
    script = r'''
import json
from dataclasses import replace
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from floattranslate.bookmark import BookmarkFrame
from floattranslate.hotkey import ToggleHotkey
from floattranslate.mac_surface import native_view
import AppKit
app = QApplication([])
app.setQuitOnLastWindowClosed(False)
ToggleHotkey.install = lambda *args: None
class Pipeline:
    def close(self): pass
frame = BookmarkFrame(ocr=object(), pipeline=Pipeline(), test_mode=True)
state = {'reduced_transparency': bool(AppKit.NSWorkspace.sharedWorkspace().accessibilityDisplayShouldReduceTransparency())}
def inspect(label):
    native = native_view(frame.bookmark).window()
    state[label] = dict(visible=bool(native.isVisible()), hides=bool(native.hidesOnDeactivate()),
                        behavior=int(native.collectionBehavior()), level=int(native.level()),
                        material=str(frame.bookmark._mac_glass[1].className()) if frame.bookmark._mac_glass else 'solid')
def inactive():
    AppKit.NSApplication.sharedApplication().deactivate()
    QTimer.singleShot(180, after_inactive)
def after_inactive():
    inspect('inactive')
    frame.apply_settings(replace(frame.settings, always_on_top=False))
    QTimer.singleShot(100, normal)
def normal():
    inspect('normal')
    frame.apply_settings(replace(frame.settings, always_on_top=True))
    frame.set_working(True, animate=False, scan=False)
    QTimer.singleShot(100, finish)
def finish():
    inspect('restored')
    for widget in (frame, frame.bookmark):
        native = native_view(widget).window()
        assert not native.hidesOnDeactivate()
    state['overlay_visible'] = bool(native_view(frame).window().isVisible())
    print(json.dumps(state), flush=True)
    frame.close()
    QTimer.singleShot(100, app.quit)
QTimer.singleShot(100, inactive)
QTimer.singleShot(10000, app.quit)
app.exec()
'''
    env = dict(os.environ, QT_QPA_PLATFORM='cocoa', FLOATTRANSLATE_CONFIG_DIR=str(tmp_path))
    result = subprocess.run([sys.executable, '-c', script], cwd=Path(__file__).resolve().parents[1],
                            env=env, text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout.strip().splitlines()[-1])
    assert data['overlay_visible']
    for phase in ('inactive', 'normal', 'restored'):
        row = data[phase]
        assert row['visible'] and not row['hides'], data
        assert row['behavior'] & 1  # CanJoinAllSpaces
        assert row['behavior'] & 256  # FullScreenAuxiliary
        assert row['material'] in ('NSGlassEffectView', 'NSVisualEffectView', 'solid')
        if not data['reduced_transparency']:
            assert row['material'] != 'solid', data
    assert data['inactive']['level'] >= 3, data
    assert data['restored']['level'] >= 3, data
    assert data['normal']['level'] == 0
