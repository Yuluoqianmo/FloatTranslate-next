"""Native keyboard delivery test, no live OCR / API credentials used."""
import ctypes
import json
import traceback
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QPoint,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog,QLineEdit,QVBoxLayout,QWidget

from .bookmark import BookmarkFrame
from .diagnostics import wait_until
from .layout import OverlayRegion,TextRegion
from .settings import Settings


class CountingPipeline:
    calls=0
    metrics={}
    def overlay(self,*args,**kwargs):
        self.calls+=1
        return [OverlayRegion(TextRegion('hello',20,20,160,30),'你好')]
    def close(self):
        pass


def run(application,directory):
    directory=Path(directory).resolve()
    directory.mkdir(parents=True,exist_ok=True)
    report={'passed':False,'input':'native Windows keyboard events; synthetic pipeline'}
    user=ctypes.windll.user32
    user.GetForegroundWindow.restype=ctypes.c_void_p
    def enter(extended=False):
        user.keybd_event(13,28,1 if extended else 0,0)
        user.keybd_event(13,28,3 if extended else 2,0)
    def global_enter():
        for key,flag in ((17,0),(18,0),(16,0),(13,0),(13,2),(16,2),(18,2),(17,2)):
            user.keybd_event(key,0,flag,0)
    document=QWidget()
    document.setWindowTitle('FloatTranslate keyboard fixture')
    document.setGeometry(80,65,1100,750)
    layout=QVBoxLayout(document)
    field=QLineEdit('Enter stays in this synthetic source application')
    layout.addWidget(field)
    returns=[]
    field.returnPressed.connect(lambda:returns.append(1))
    frame=None
    dialog=None
    try:
        document.show()
        document.activateWindow()
        pipeline=CountingPipeline()
        frame=BookmarkFrame(Settings(provider='custom',base_url='http://localhost:1234/v1',model='synthetic',reduce_motion=True,
            toggle_shortcut='Ctrl+Alt+Shift+F11',translate_shortcut='Ctrl+Alt+Shift+Return'),pipeline=pipeline,test_mode=True)
        frame.scan_capture=lambda:(Image.new('RGB',(400,250),'white'),1)
        frame.move_bookmark(document.pos()+QPoint(20,120))
        assert frame.translate_hotkey.registered,'Translation shortcut registration failed'
        frame.toggle_working()
        QTest.qWait(200)
        assert user.GetForegroundWindow()==int(frame.bookmark.winId()),'Bookmark did not receive real native focus'
        assert pipeline.calls==0
        enter()
        wait_until(application,lambda:pipeline.calls==1 and not frame._busy)
        report['bookmark_plain_enter']=True
        enter(extended=True)
        wait_until(application,lambda:pipeline.calls==2 and not frame._busy)
        report['numpad_enter']=True
        document.activateWindow()
        field.setFocus()
        QTest.qWait(150)
        assert user.GetForegroundWindow()==int(document.winId())
        enter()
        QTest.qWait(250)
        assert len(returns)==1 and pipeline.calls==2
        report['ordinary_enter_not_intercepted_in_other_window']=True
        frame.set_working(False,animate=False)
        document.activateWindow()
        field.setFocus()
        QTest.qWait(100)
        global_enter()
        wait_until(application,lambda:pipeline.calls==3 and not frame._busy)
        assert frame.working and len(returns)==1
        assert user.GetForegroundWindow()==int(document.winId()),'Global translation stole source focus'
        report['global_modified_enter_from_standby']=True
        dialog=QDialog(frame.bookmark)
        box=QVBoxLayout(dialog)
        edit=QLineEdit('Synthetic settings field')
        box.addWidget(edit)
        frame._dialog=dialog
        dialog.show()
        dialog.activateWindow()
        edit.setFocus()
        QTest.qWait(150)
        enter()
        global_enter()
        QTest.qWait(350)
        assert pipeline.calls==3
        report['settings_inputs_do_not_translate']=True
        dialog.close()
        frame._dialog=None
        report['passed']=True
    except Exception:
        report['error']=traceback.format_exc()
    finally:
        if dialog:
            dialog.close()
        if frame:
            frame._dialog=None
            frame.close()
            wait_until(application,lambda:not frame.worker_pool.activeThreadCount())
            frame.close()
        document.close()
        (directory/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    return 0 if report['passed'] else 1
