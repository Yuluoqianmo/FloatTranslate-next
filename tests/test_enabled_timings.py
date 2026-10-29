from dataclasses import replace
import json
import time

import httpx
from PIL import Image
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QMenu

from floattranslate.catalog import load_enabled,save_enabled,save_catalog,ModelList
from floattranslate.model_picker import ModelPicker
from floattranslate.providers import Connection,ModelClient
from floattranslate.bookmark import BookmarkFrame
from floattranslate.hotkey import ToggleHotkey
from floattranslate.layout import TextRegion,OverlayRegion
from floattranslate.pipeline import Pipeline
from floattranslate.settings import Settings


def test_fetched_catalog_does_not_auto_enable_models(tmp_path,monkeypatch):
    monkeypatch.setenv('FLOATTRANSLATE_CONFIG_DIR',str(tmp_path))
    connection=Connection('custom','http://localhost:1234/v1','openai','test')
    save_catalog(connection,ModelList(['a','b','c']))
    assert load_enabled(connection,'a')==['a']
    save_enabled(connection,['a','c'],'a')
    save_catalog(connection,ModelList(['a','b','c','d']))
    assert load_enabled(connection,'a')==['a','c']
    assert load_enabled(replace(connection,key='other'),'b')==['b']


def test_checkbox_selection_survives_search_and_manual_add():
    app=QApplication.instance() or QApplication([])
    picker=ModelPicker(['a','b','c'],'a',enabled=['a'])
    picker.list.item(2).setCheckState(Qt.CheckState.Checked)
    picker.search.setText('b')
    assert picker.enabled_ids()==['a','c']
    picker.list.item(0).setCheckState(Qt.CheckState.Checked)
    picker.search.setText('')
    assert picker.list.item(1).checkState()==Qt.CheckState.Checked
    picker.selected.setText('manual/id')
    picker.add_manual()
    assert picker.enabled_ids()==['a','b','c','manual/id']
    picker.only_current()
    assert picker.enabled_ids()==['manual/id']
    picker.close()


def test_primary_menu_only_contains_enabled_and_settings_are_grouped(tmp_path,monkeypatch):
    monkeypatch.setenv('FLOATTRANSLATE_CONFIG_DIR',str(tmp_path))
    monkeypatch.setattr(ToggleHotkey,'install',lambda self,text:None)
    app=QApplication.instance() or QApplication([])
    frame=BookmarkFrame(Settings(provider='custom',base_url='http://localhost:1234/v1',model='a'),test_mode=True)
    connection=frame._connection()
    save_catalog(connection,ModelList(['a','b','c']))
    save_enabled(connection,['a','c'],'a')
    menu=QMenu()
    frame._populate_menu(menu)
    root=[a.text() for a in menu.actions()]
    models=next(a.menu() for a in menu.actions() if a.text()=='选择模型')
    assert [a.text() for a in models.actions() if a.isCheckable()]==['a','c']
    assert '设置' in root and 'API 与供应商…' not in root
    assert len([a for a in menu.actions() if not a.isSeparator()])<=10
    frame.close()


def test_wrapped_valid_translation_array_is_accepted():
    client=ModelClient(Connection('custom','https://example.test/v1','openai','x'),httpx.MockTransport(lambda r:httpx.Response(200,json={'choices':[{'message':{'content':'翻译如下：\n["你好", "世界"]\n完成。'}}]})))
    try:
        assert client.translate_blocks('model',['hello','world'],'中文')==['你好','世界']
        assert client.metrics['first_content_ms'] is not None
    finally:
        client.close()


def test_progress_is_kept_on_current_revision_failure(monkeypatch):
    monkeypatch.setattr(ToggleHotkey,'install',lambda self,text:None)
    app=QApplication.instance() or QApplication([])
    frame=BookmarkFrame(test_mode=True)
    frame._auto=False
    frame.set_working(True,animate=False,scan=False)
    revision=frame._revision
    frame._regions=[OverlayRegion(TextRegion('Hello',20,30,100,25),'你好')]
    frame._completed(((revision,1),None,'后续段落格式错误'))
    assert frame._regions and frame._last_translation=='你好'
    frame.close()


def test_timer_ticks_do_not_queue_forced_rescan(monkeypatch):
    monkeypatch.setattr(ToggleHotkey,'install',lambda self,text:None)
    app=QApplication.instance() or QApplication([])
    frame=BookmarkFrame(test_mode=True)
    frame.set_working(True,animate=False,scan=False)
    frame._jobs[1]=object()
    frame._rescan_needed=False
    frame.scan()
    assert not frame._rescan_needed
    frame.scan(force=True)
    assert frame._rescan_needed
    frame._jobs.clear()
    frame.close()


def test_diagnostic_attempt_count_is_not_revision_or_background_checks(monkeypatch):
    monkeypatch.setattr(ToggleHotkey,'install',lambda self,text:None)
    app=QApplication.instance() or QApplication([])
    frame=BookmarkFrame(test_mode=True)
    frame._revision=395
    for _ in range(200):
        frame._revision+=1
    assert frame._run_counts['total']==0
    frame._run_records[frame._revision]={'run':frame._revision,'started':time.monotonic(),'trigger':'manual','model':'test','target':'中文'}
    frame._record_metrics(frame._revision,'完成')
    assert frame._metrics['run']==1 and frame._run_counts=={'total':1,'manual':1,'auto':0}
    frame._run_records[frame._revision+1]={'run':frame._revision+1,'started':time.monotonic(),'trigger':'auto'}
    frame._record_metrics(frame._revision+1,'已取消：画面或模式变化')
    assert frame._metrics['run']==2 and frame._run_counts['auto']==1
    frame.show_timings()
    dialog=frame._dialog
    assert '翻译 #2' in dialog.runs.itemText(0) and '596' not in dialog.runs.itemText(0)
    assert dialog.table.rowCount()==6
    dialog.details.setChecked(True)
    assert dialog.table.rowCount()>6
    dialog.close()
    app.processEvents()
    frame.close()


def test_unreliable_desktop_is_not_used_to_cancel_translation(monkeypatch):
    monkeypatch.setattr(ToggleHotkey,'install',lambda self,text:None)
    app=QApplication.instance() or QApplication([])
    frame=BookmarkFrame(test_mode=True)
    frame._auto=False
    frame.set_working(True,animate=False,scan=False)
    frame._independent_capture_available=False
    frame._regions=[OverlayRegion(TextRegion('hello',20,20,120,30),'你好')]
    monkeypatch.setattr(frame,'_underlay',lambda:None)
    frame._watch_view()
    assert frame._regions and not frame._view_unstable
    frame.close()


def test_auto_monitor_uses_source_capture_without_affinity(monkeypatch):
    import sys
    if sys.platform != 'win32':
        import pytest
        pytest.skip('Independent underlying-window capture is a Windows backend')
    monkeypatch.setattr(ToggleHotkey,'install',lambda self,text:None)
    app=QApplication.instance() or QApplication([])
    frame=BookmarkFrame(test_mode=True)
    frame._auto=False
    frame.set_working(True,animate=False,scan=False)
    frame._excluded=False
    frame._independent_capture_available=True
    frame.view_timer.stop()
    frame.set_auto(True)
    assert frame.view_timer.isActive()
    frame.close()
