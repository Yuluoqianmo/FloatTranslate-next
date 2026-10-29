from dataclasses import replace

from PIL import Image
from PySide6.QtCore import QPoint,Qt
from PySide6.QtTest import QTest
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from floattranslate.bookmark import BookmarkFrame
from floattranslate.hotkey import ToggleHotkey
from floattranslate.layout import OverlayRegion,TextRegion
from floattranslate.settings import Settings


class CountingPipeline:
    def __init__(self):
        self.calls=0
        self.metrics={}
    def overlay(self,*args,**kwargs):
        self.calls+=1
        return [OverlayRegion(TextRegion('hello',20,20,120,30),'你好')]
    def close(self):
        pass


def test_only_explicit_or_enabled_auto_triggers_translation(monkeypatch):
    monkeypatch.setattr(ToggleHotkey,'install',lambda self,text:None)
    app=QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    pipeline=CountingPipeline()
    frame=BookmarkFrame(Settings(provider='custom',base_url='http://localhost:1234/v1',model='test',reduce_motion=True),pipeline=pipeline,test_mode=True)
    monkeypatch.setattr(frame,'scan_capture',lambda:(Image.new('RGB',(300,200),'white'),1))
    assert not frame._auto
    frame.set_working(True)
    frame.move_bookmark(frame.bookmark.pos()+QPoint(8,5))
    frame.apply_settings(replace(frame.settings,font_size=20))
    handle=frame.handle_rect().center()
    QTest.mousePress(frame,Qt.MouseButton.LeftButton,pos=handle)
    QTest.mouseMove(frame,handle+QPoint(-10,-10))
    QTest.mouseRelease(frame,Qt.MouseButton.LeftButton,pos=handle)
    QTest.qWait(450)
    assert pipeline.calls==0 and not frame._run_records
    frame.scan(force=True)
    QTest.qWait(350)
    assert pipeline.calls==1 and frame._regions
    frame.set_working(False,animate=False)
    frame.scan(force=True)
    QTest.qWait(400)
    assert pipeline.calls==2 and frame.working
    frame.clear_translation()
    frame.set_auto(True)
    QTest.qWait(400)
    assert pipeline.calls==3
    frame.set_auto(False)
    frame.clear_translation()
    frame.move_bookmark(frame.bookmark.pos()+QPoint(8,5))
    frame.apply_settings(replace(frame.settings,font_size=21))
    QTest.qWait(400)
    assert pipeline.calls==3
    # Turning auto off before a queued capture starts must cancel that attempt.
    frame._auto=True
    frame._automatic_scan()
    frame.set_auto(False)
    QTest.qWait(350)
    assert pipeline.calls==3 and not frame._regions
    frame.queue_manual_translation(150)
    frame.set_working(False,animate=False)
    frame.set_working(True,animate=False)
    QTest.qWait(300)
    assert pipeline.calls==3
    frame.close()
    app.processEvents()


def test_enter_from_bookmark_frame_and_during_opening(monkeypatch):
    monkeypatch.setattr(ToggleHotkey,'install',lambda self,text:None)
    app=QApplication.instance() or QApplication([])
    frame=BookmarkFrame(test_mode=True)
    calls=[]
    monkeypatch.setattr(frame,'scan',lambda force=False:calls.append(force))
    QTest.keyClick(frame.bookmark,Qt.Key.Key_Return)
    QTest.keyClick(frame,Qt.Key.Key_Enter)
    assert calls==[True,True]
    event=QKeyEvent(QKeyEvent.Type.KeyPress,Qt.Key.Key_Return,Qt.KeyboardModifier.NoModifier,'\r',True)
    frame.keyPressEvent(event)
    assert calls==[True,True]
    QTest.keyClick(frame.bookmark,Qt.Key.Key_Return,Qt.KeyboardModifier.ShiftModifier)
    assert calls==[True,True]
    frame._menu_open=True
    QTest.keyClick(frame.bookmark,Qt.Key.Key_Return)
    assert calls==[True,True]
    frame._menu_open=False
    frame.close()


def test_global_translation_hotkey_has_distinct_id_and_requires_modifier(monkeypatch):
    from floattranslate.hotkey import shortcut_parts
    import pytest
    shortcut_parts('Ctrl+Alt+Return',allow_enter=True)
    with pytest.raises(ValueError):
        shortcut_parts('Return',allow_enter=True)
    monkeypatch.setattr(ToggleHotkey,'install',lambda self,text:None)
    app=QApplication.instance() or QApplication([])
    frame=BookmarkFrame(test_mode=True)
    assert frame.hotkey.ID!=frame.translate_hotkey.ID
    assert frame.translate_hotkey.allow_enter
    frame.close()


def test_enter_during_open_animation_runs_once_after_opening(monkeypatch):
    monkeypatch.setattr(ToggleHotkey,'install',lambda self,text:None)
    app=QApplication.instance() or QApplication([])
    pipeline=CountingPipeline()
    frame=BookmarkFrame(Settings(provider='custom',base_url='http://localhost:1234/v1',model='test'),pipeline=pipeline,test_mode=True)
    monkeypatch.setattr(frame,'scan_capture',lambda:(Image.new('RGB',(300,200),'white'),1))
    frame.toggle_working()
    assert frame._transitioning and pipeline.calls==0
    QTest.keyClick(frame.bookmark,Qt.Key.Key_Return)
    assert frame._manual_on_open
    QTest.qWait(1000)
    assert pipeline.calls==1 and not frame._manual_on_open
    frame.close()
