"""Slow local translation + selected menu + measured stage regression."""
import json
import time
from pathlib import Path

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMenu

from . import bookmark_diagnostics, diagnostics
from .bookmark import BookmarkFrame
from .catalog import ModelList,save_catalog,save_enabled
from .capture import capture_region
from .scene import Scene,changed


def run(application,directory):
    directory=Path(directory).resolve()
    directory.mkdir(parents=True,exist_ok=True)
    original_post=diagnostics.MockModel.do_POST
    original_frame=bookmark_diagnostics.BookmarkFrame
    class ProbeFrame(BookmarkFrame):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            self._tested_experience=False
        def _completed(self,payload):
            super()._completed(payload)
            if self._tested_experience or not self._regions or payload[2]:
                return
            self._tested_experience=True
            clean,_=self.watch_capture()
            desktop,_=capture_region(self.capture_rect())
            assert not changed(self._pending_scene,Scene.capture(clean)), 'Overlay changed its own source capture'
            assert changed(Scene.capture(clean),Scene.capture(desktop)), 'Visible-overlay regression not exercised'
            assert self._metrics['run']==1, self._metrics
            connection=self._connection()
            save_catalog(connection,ModelList([self.settings.model]+[f'candidate-{i}' for i in range(13)]))
            save_enabled(connection,[self.settings.model,'candidate-7'],self.settings.model)
            menu=QMenu(self)
            self._populate_menu(menu)
            submenu=next(a.menu() for a in menu.actions() if a.text()=='选择模型')
            enabled=[a.text() for a in submenu.actions() if a.isCheckable()]
            assert enabled==[self.settings.model,'candidate-7'],enabled
            menu.ensurePolished()
            menu.adjustSize()
            menu.grab().save(str(directory/'compact-menu.png'))
            assert self._metrics['api_ms']>=2300,self._metrics
            assert self._metrics['queue_ms']>=0 and self._metrics['capture_ms']>=0
            assert self._metrics['ocr_ms']>=0 and self._metrics['client_init_ms']>=0
            assert self._metrics['first_content_ms'] is not None
            assert self._metrics['end_to_end_ms']>=self._metrics['api_ms']
            self.show_timings()
            QTest.qWait(100)
            self._dialog.grab().save(str(directory/'timings.png'))
            self._dialog.close()
            application.processEvents()
            report={k:v for k,v in self._metrics.items() if not k.startswith('_')}
            (directory/'single-run-timings.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    def slow_post(server):
        time.sleep(2.6)
        original_post(server)
    diagnostics.MockModel.do_POST=slow_post
    bookmark_diagnostics.BookmarkFrame=ProbeFrame
    try:
        result=bookmark_diagnostics.run(application,directory)
        report=json.loads((directory/'report.json').read_text('utf-8'))
        assert (directory/'single-run-timings.json').exists(),'No stable translation + stage timings produced'
        report['slow_translation_stays_visible']=bool(report.get('passed'))
        report['only_checked_models_in_menu']=True
        report['measured_stage_dialog']=True
        report['visible_overlay_not_in_source_capture']=True
        report['actual_attempt_numbers_start_at_one']=True
        (directory/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
        return result
    finally:
        diagnostics.MockModel.do_POST=original_post
        bookmark_diagnostics.BookmarkFrame=original_frame
