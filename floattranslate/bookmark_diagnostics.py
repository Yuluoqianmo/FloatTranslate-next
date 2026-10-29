"""Real desktop smoke test using only synthetic content and a localhost model."""
import json
import os
import threading
import traceback
from dataclasses import replace
from http.server import ThreadingHTTPServer
from pathlib import Path

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest

from .bookmark import BookmarkFrame
from .diagnostics import Document, MockModel, wait_until, save_document_view
from .settings import Settings


def run(application, directory):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True,exist_ok=True)
    report = {'passed':False,'model':'localhost fixture; no live credentials'}
    server = ThreadingHTTPServer(('127.0.0.1',0),MockModel)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    document = Document()
    frame = None
    try:
        document.show()
        document.raise_()
        document.activateWindow()
        QTest.qWait(250)
        settings = Settings(provider='custom',base_url=f'http://127.0.0.1:{server.server_port}/v1',model='local-test-model',toggle_shortcut='Ctrl+Alt+Shift+F11')
        frame = BookmarkFrame(settings,test_mode=True)
        frame._preferred_size.setWidth(940)
        frame._preferred_size.setHeight(470)
        frame.move_bookmark(document.pos()+QPoint(10,90))
        frame.show()
        QTest.qWait(150)
        assert not frame.isVisible() and frame.bookmark.isVisible()
        report['standby'] = True
        calls_before_open=MockModel.calls
        anchor = frame.bookmark.pos()
        QTest.mouseClick(frame.bookmark,Qt.MouseButton.LeftButton,pos=QPoint(20,40))
        QTest.qWait(180)
        assert frame._transitioning and 0 < frame.transition.progress < 1
        box = frame.content_rect()
        alpha = frame.transition.snapshot.toImage().pixelColor(box.center().x(),box.top()).alpha()
        assert alpha > 100, 'Animation snapshot lost its border'
        frame.transition.grab().save(str(directory/'open-mid.png'))
        report['animation_snapshot_border_alpha'] = alpha
        wait_until(application,lambda:not frame._transitioning)
        QTest.qWait(350)
        assert not frame._regions and not frame._busy and MockModel.calls==calls_before_open
        report['opening_does_not_translate']=True
        frame.scan(force=True)
        wait_until(application,lambda:not frame._busy and not frame._capture_pending and bool(frame._regions))
        assert frame._independent_capture_available, 'Source window capture must remain available'
        assert 'technology' in frame._last_source.lower(), frame._last_source
        assert frame.bookmark.pos() == anchor
        report['ocr_regions'] = len(frame._regions)
        report['capture_backend'] = 'source-window PrintWindow'
        report['capture_exclusion'] = frame._excluded
        report['open_animation'] = True
        frame.view_timer.stop()
        frame.scan_timer.stop()
        # Only the synthetic document is captured for screenshots.
        import ctypes
        ctypes.windll.user32.SetWindowDisplayAffinity(int(frame.winId()),0)
        frame._menu_open = True
        QTest.qWait(100)
        save_document_view(document,directory/'translated.png')
        frame._refresh_capture_exclusion()
        frame._menu_open = False
        frame._set_busy(True)
        QTest.qWait(700)
        assert frame.halo.isVisible()
        frame.halo.grab().save(str(directory/'halo.png'))
        frame._set_busy(False)
        assert not frame.halo.isVisible()
        report['outer_halo'] = True
        # Static scene must not restart worker or native region on timer ticks.
        calls, masks = MockModel.calls, []
        original_mask = frame.setMask
        frame.setMask = lambda mask:(masks.append(1),original_mask(mask))[-1]
        frame.set_auto(True)
        QTest.qWait(3300)
        frame.set_auto(False)
        frame.setMask = original_mask
        assert not masks and MockModel.calls == calls and not frame._busy
        report['static_mask_changes'] = len(masks)
        # Automatic translation must follow real scrolling, without detecting
        # its own rendered text as a second page change.
        frame.set_auto(True)
        document.scroll_offset=50
        document.repaint()
        frame._watch_view()
        assert not frame._regions, 'Real source scroll did not clear stale translation'
        wait_until(application,lambda:not frame._busy and bool(frame._regions))
        assert frame._metrics.get('trigger')=='auto',frame._metrics
        document.scroll_offset=0
        document.repaint()
        frame._watch_view()
        assert not frame._regions
        wait_until(application,lambda:not frame._busy and bool(frame._regions))
        frame.set_auto(False)
        report['real_scroll_detected_by_source_capture']=True
        report['automatic_translation_after_scroll']=True
        # Windows global hotkey, sent as actual input while our document has focus.
        document.activateWindow()
        QTest.qWait(100)
        import ctypes
        for vk, flag in ((0x11,0),(0x12,0),(0x10,0),(0x7A,0),(0x7A,2),(0x10,2),(0x12,2),(0x11,2)):
            ctypes.windll.user32.keybd_event(vk,0,flag,0)
        QTest.qWait(180)
        assert frame._transitioning and 0 < frame.transition.progress < 1
        frame.transition.grab().save(str(directory/'close-mid.png'))
        QTest.qWait(350)
        assert not frame.working and frame.bookmark.isVisible() and not frame.isVisible()
        report['close_animation_and_global_hotkey'] = True
        screen = frame.bookmark.screen().availableGeometry()
        frame.move_bookmark(QPoint(screen.right()-75,screen.top()+120))
        anchor = frame.bookmark.pos()
        frame.set_working(True,animate=False,scan=False)
        assert frame._leftward and frame.capture_rect().right() < anchor.x()
        assert frame.bookmark.pos() == anchor
        assert frame.handle_rect().center().x() < frame.width()/2
        frame.view_timer.stop()
        before = frame.capture_rect()
        handle = frame.handle_rect().center()
        QTest.mousePress(frame,Qt.MouseButton.LeftButton,pos=handle)
        QTest.mouseMove(frame,handle+QPoint(60,-30))
        QTest.mouseRelease(frame,Qt.MouseButton.LeftButton,pos=handle)
        assert frame.capture_rect().width() == before.width()-60
        assert frame.capture_rect().right() == before.right() and frame.bookmark.pos() == anchor
        report['right_anchor_left_handle_resize'] = True
        frame.set_working(False,animate=False)
        # Preferences save must retain the bookmark and original standby mode.
        for page in ('api','ocr','appearance'):
            frame.preferences(page)
            QTest.qWait(120)
            dialog = frame._dialog
            if page == 'api':
                dialog.key.setText('')
            QTest.mouseClick(dialog.save_button,Qt.MouseButton.LeftButton)
            QTest.qWait(150)
            assert frame._dialog is None and frame.bookmark.isVisible() and not frame.isVisible(), {'page':page,'dialog':frame._dialog is not None,'message':dialog.message.text() if frame._dialog else 'closed','working':frame.working,'visible':frame.isVisible(),'bookmark':frame.bookmark.isVisible()}
        report['standby_settings_save'] = True
        frame.set_working(True,animate=True,scan=False)
        QTest.qWait(120)
        progress = frame.transition.progress
        frame.toggle_working()
        assert abs(frame.transition.progress-progress)<.05
        QTest.qWait(500)
        assert not frame.working and not frame._transitioning and not frame.isVisible()
        report['rapid_reverse'] = True
        report['passed'] = True
    except Exception:
        report['error'] = traceback.format_exc()
    finally:
        if frame:
            frame.close()
            wait_until(application,lambda:not frame.worker_pool.activeThreadCount() and not frame.preferences_pool.activeThreadCount())
            frame.close()
        document.close()
        server.shutdown()
        server.server_close()
        (directory/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    return 0 if report['passed'] else 1
