"""Exercise the real application event loop in a child process.

processEvents-only widget tests cannot catch Qt's automatic application quit.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("page,operation", [
    ("api", "save"), ("ocr", "save"), ("appearance", "save"),
    ("appearance", "toggle_top"),
    ("api", "cancel"), ("ocr", "cancel"), ("appearance", "cancel"),
    ("api", "close"), ("ocr", "close"), ("appearance", "close"),
    ("api", "escape"), ("appearance", "escape"),
])
def test_preferences_finish_does_not_quit_tool_window(tmp_path, page, operation):
    script = r'''
import json,sys
from PySide6.QtCore import QTimer,Qt
from PySide6.QtWidgets import QApplication,QPushButton
from PySide6.QtTest import QTest
from floattranslate.__main__ import configure_application
from floattranslate.frame import RecognitionFrame
from floattranslate.settings import SecretStore

class MemorySecrets(SecretStore):
    def get(self,identity): return self._session.get(identity,'')
    def set(self,identity,key): self._session[identity]=key; return True

app=QApplication([])
configure_application(app)
frame=RecognitionFrame(test_mode=True)
frame.secrets=MemorySecrets()
frame.setGeometry(100,100,700,380)
frame.show()
state={'alive_after_dialog':False}
page,operation=sys.argv[1:]

def opened():
    frame.preferences(page)
    dialog=frame._dialog
    if page=='api':
        dialog.url.setText('https://gateway.example/v1')
        dialog.key.setText('synthetic-local-test-key')
        dialog.model.setEditText('test-model')
    if operation=='toggle_top':
        dialog.on_top.setChecked(not dialog.on_top.isChecked())
    def finish():
        if operation in ('save','toggle_top'):
            QTest.mouseClick(dialog.save_button,Qt.MouseButton.LeftButton)
        elif operation=='cancel':
            button=next(b for b in dialog.findChildren(QPushButton) if b.text()=='取消')
            QTest.mouseClick(button,Qt.MouseButton.LeftButton)
        elif operation=='escape':
            QTest.keyClick(dialog,Qt.Key.Key_Escape)
        else:
            dialog.close()
    QTimer.singleShot(100,finish)

def verify():
    state.update(alive_after_dialog=True,visible=frame.isVisible(),
                 dialog_closed=frame._dialog is None,closing=frame._closing,
                 opacity=frame.windowOpacity(),geometry=[frame.x(),frame.y(),frame.width(),frame.height()])
    if operation in ('save','toggle_top'):
        from floattranslate.settings import Settings
        loaded=Settings.load()
        state['persisted']=(loaded.model=='test-model') if page=='api' else loaded==frame.settings
    frame.close()
    QTimer.singleShot(150,app.quit)

QTimer.singleShot(0,opened)
QTimer.singleShot(800,verify)
QTimer.singleShot(5000,app.quit)
app.exec()
print(json.dumps(state))
'''
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", FLOATTRANSLATE_CONFIG_DIR=str(tmp_path/"settings"))
    result = subprocess.run([sys.executable, "-c", script, page, operation],
                            cwd=Path(__file__).resolve().parents[1], env=env,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    state = json.loads(result.stdout.strip())
    assert state.get("alive_after_dialog"), state
    assert state["visible"] and state["dialog_closed"] and not state["closing"], state
    assert state["opacity"] == 1 and state["geometry"] == [100,100,700,380], state
    if operation in ("save", "toggle_top"):
        assert state["persisted"], state
