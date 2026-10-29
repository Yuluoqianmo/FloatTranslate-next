"""Native corner hit targets and fixed opposite edges; no live API calls."""
import ctypes
from ctypes import wintypes
import json
import traceback
from pathlib import Path

from PySide6.QtCore import QPoint,QSize,Qt
from PySide6.QtGui import QCursor,QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from .bookmark import BookmarkFrame
from .settings import Settings


def run(application,directory):
    directory=Path(directory).resolve()
    directory.mkdir(parents=True,exist_ok=True)
    report={'passed':False,'cases':[]}
    frame=None
    document=QWidget()
    bounds=QGuiApplication.primaryScreen().availableGeometry()
    document.setWindowTitle('FloatTranslate synthetic resize fixture')
    document.setGeometry(bounds.adjusted(10,10,-10,-10))
    user=ctypes.windll.user32
    user.WindowFromPoint.argtypes=[wintypes.POINT]
    user.WindowFromPoint.restype=wintypes.HWND
    original_cursor=QCursor.pos()
    try:
        document.show()
        document.raise_()
        frame=BookmarkFrame(Settings(reduce_motion=True,toggle_shortcut='Ctrl+Alt+Shift+F11',translate_shortcut='Ctrl+Alt+Shift+Return'),test_mode=True)
        for right,up in ((False,False),(True,False),(False,True),(True,True)):
            frame.set_working(False,animate=False)
            frame._preferred_size=QSize(min(400,bounds.width()//3),min(260,bounds.height()//3))
            anchor=QPoint(bounds.right()-70 if right else bounds.left()+30,bounds.bottom()-95 if up else bounds.top()+100)
            frame.move_bookmark(anchor)
            frame.set_working(True,animate=False,scan=False)
            QTest.qWait(150)
            expected=('t' if up else 'b')+('l' if right else 'r')
            assert frame.resize_corner()==expected
            handle=frame.handle_rect().center()
            QCursor.setPos(frame.mapToGlobal(handle))
            point=wintypes.POINT()
            user.GetCursorPos(ctypes.byref(point))
            assert user.WindowFromPoint(point)==int(frame.winId()),'Corner is not natively clickable'
            before=frame.capture_rect()
            QTest.mousePress(frame,Qt.MouseButton.LeftButton,pos=handle)
            QTest.mouseMove(frame,handle+QPoint(-50 if right else 50,-80 if up else 80))
            QTest.mouseRelease(frame,Qt.MouseButton.LeftButton,pos=handle)
            after=frame.capture_rect()
            assert after.width()==before.width()+50 and after.height()==before.height()+80
            assert (after.right()==before.right() if right else after.left()==before.left())
            assert (after.bottom()==before.bottom() if up else after.top()==before.top())
            assert frame.bookmark.pos()==anchor and bounds.contains(after)
            report['cases'].append({'corner':expected,'native_hit':True,'width_delta':50,'height_delta':80,'opposite_edges_fixed':True,'bookmark_fixed':True})
            frame.grab().save(str(directory/(expected+'.png')))
        assert frame._run_counts['total']==0
        report['no_translation_triggered']=True
        report['passed']=True
    except Exception:
        report['error']=traceback.format_exc()
    finally:
        if frame:
            frame.close()
        document.close()
        QCursor.setPos(original_cursor)
        (directory/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    return 0 if report['passed'] else 1
