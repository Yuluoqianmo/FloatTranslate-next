from dataclasses import replace

import pytest
from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage
from PIL import Image

from floattranslate.bookmark import BookmarkFrame, scope_geometry
from floattranslate.hotkey import ToggleHotkey, shortcut_parts


@pytest.fixture
def bookmark(monkeypatch):
    application = QApplication.instance() or QApplication([])
    application.setQuitOnLastWindowClosed(False)
    monkeypatch.setattr(ToggleHotkey,'install',lambda self,text:setattr(self,'text',text))
    frame = BookmarkFrame(test_mode=True)
    frame._auto = False
    frame.scan = lambda *args,**kwargs:None
    frame.show()
    application.processEvents()
    yield frame
    frame.close()
    application.processEvents()


def test_scope_side_and_vertical_avoidance():
    bounds = QRect(-1920,0,1920,1080)
    left, side = scope_geometry(QPoint(-1850,100),QSize(720,400),bounds)
    assert not side and left.left() > -1850 and bounds.contains(left)
    right, side = scope_geometry(QPoint(-70,950),QSize(720,400),bounds)
    assert side and right.right() < -70 and right.bottom() < bounds.bottom()


def test_standby_click_and_bidirectional_animation(bookmark):
    assert bookmark.bookmark.isVisible() and not bookmark.isVisible()
    anchor = bookmark.bookmark.pos()
    QTest.mouseClick(bookmark.bookmark,Qt.MouseButton.LeftButton,pos=QPoint(20,40))
    QTest.qWait(180)
    assert bookmark.working and bookmark._transitioning
    assert 0 < bookmark.transition.progress < 1
    QTest.qWait(400)
    assert bookmark.isVisible() and not bookmark._transitioning
    assert bookmark.bookmark.pos() == anchor
    bookmark.toggle_working()
    QTest.qWait(180)
    assert 0 < bookmark.transition.progress < 1
    QTest.qWait(400)
    assert not bookmark.isVisible() and bookmark.bookmark.isVisible()
    assert not bookmark._busy and not bookmark.halo.isVisible()


def test_right_anchor_and_left_resize(bookmark):
    screen = bookmark.bookmark.screen().availableGeometry()
    bookmark.move_bookmark(QPoint(screen.right()-70,screen.top()+100))
    anchor = bookmark.bookmark.pos()
    bookmark.set_working(True,animate=False,scan=False)
    assert bookmark._leftward and bookmark.bookmark.pos() == anchor
    assert bookmark.capture_rect().right() < anchor.x()
    assert bookmark.handle_rect().center().x() < bookmark.width()/2
    start = bookmark.capture_rect()
    handle = bookmark.handle_rect().center()
    QTest.mousePress(bookmark,Qt.MouseButton.LeftButton,pos=handle)
    QTest.mouseMove(bookmark,handle+QPoint(50,-20))
    QTest.mouseRelease(bookmark,Qt.MouseButton.LeftButton,pos=handle)
    assert bookmark.capture_rect().width() == start.width()-50
    assert bookmark.capture_rect().right() == start.right()
    assert bookmark.bookmark.pos() == anchor


def test_busy_indicator_stays_in_bookmark_and_preferences_preserve_standby(bookmark):
    bookmark.set_working(True,animate=False,scan=False)
    bookmark._set_busy(True)
    assert not bookmark.halo.isVisible()
    assert bookmark.animation_timer.isActive()
    bookmark.set_working(False,animate=False)
    assert not bookmark.halo.isVisible() and not bookmark.animation_timer.isActive()
    bookmark.apply_settings(replace(bookmark.settings,always_on_top=not bookmark.settings.always_on_top))
    bookmark._restore_after_preferences()
    assert not bookmark.isVisible() and bookmark.bookmark.isVisible()
    assert bookmark.settings.toggle_shortcut == 'Alt+T'


def test_mask_is_stable_and_has_no_white_drag_band(bookmark):
    bookmark.set_working(True,animate=False,scan=False)
    if not bookmark._shaped:
        return
    old = bookmark.mask()
    bookmark._update_native_mask()
    assert old == bookmark.mask()
    assert not old.contains(bookmark.content_rect().center())
    assert not old.contains(QPoint(100,5))


def test_shortcut_validation():
    shortcut_parts('Ctrl+Shift+Y')
    shortcut_parts('Alt+F8')
    with pytest.raises(ValueError):
        shortcut_parts('T')


@pytest.mark.parametrize('right',[False,True])
def test_animation_contains_complete_border_and_growing_pixels(bookmark,right):
    bounds = bookmark.bookmark.screen().availableGeometry()
    bookmark.move_bookmark(QPoint(bounds.right()-70 if right else bounds.left()+25,bounds.top()+90))
    bookmark.set_working(True,scan=False)
    bookmark.transition.animation.pause()
    snapshot = bookmark.transition.snapshot.toImage()
    box = bookmark.content_rect()
    assert snapshot.pixelColor(box.center().x(),box.top()).alpha() > 100
    def visible_bounds(progress):
        bookmark.transition._tick(progress)
        image = bookmark.transition.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
        pixels = Image.frombytes('RGBA',(image.width(),image.height()),bytes(image.constBits()),'raw','RGBA',image.bytesPerLine())
        return pixels.getchannel('A').getbbox()
    small,large = visible_bounds(.25),visible_bounds(.75)
    assert small and large
    assert large[2]-large[0] > (small[2]-small[0])*2
    assert large[3]-large[1] > (small[3]-small[1])*1.6


@pytest.mark.parametrize('right',[False,True])
def test_bottom_placement_uses_upper_corner_and_keeps_bottom_fixed(bookmark,right):
    screen=bookmark.bookmark.screen().availableGeometry()
    bookmark._preferred_size=QSize(min(360,screen.width()//2),220)
    bookmark.move_bookmark(QPoint(screen.right()-70 if right else screen.left()+30,screen.bottom()-95))
    anchor=bookmark.bookmark.pos()
    bookmark.set_working(True,animate=False,scan=False)
    assert bookmark._upward
    assert bookmark.resize_corner()==('tl' if right else 'tr')
    handle=bookmark.handle_rect().center()
    assert handle.y()<bookmark.height()/2
    before=bookmark.capture_rect()
    QTest.mousePress(bookmark,Qt.MouseButton.LeftButton,pos=handle)
    QTest.mouseMove(bookmark,handle+QPoint(0,-70))
    QTest.mouseRelease(bookmark,Qt.MouseButton.LeftButton,pos=handle)
    after=bookmark.capture_rect()
    assert after.height()==before.height()+70
    assert after.top()==before.top()-70 and after.bottom()==before.bottom()
    assert bookmark.bookmark.pos()==anchor
    assert screen.contains(after)
    # Reopening remembers the resized dimensions without moving the bookmark.
    bookmark.set_working(False,animate=False)
    bookmark.set_working(True,animate=False,scan=False)
    assert bookmark.capture_rect().size()==after.size()
    assert bookmark.bookmark.pos()==anchor


def test_downward_resize_reaching_bottom_offers_top_corner(bookmark):
    screen=bookmark.bookmark.screen().availableGeometry()
    bookmark._preferred_size=QSize(min(300,screen.width()//2),160)
    bookmark.move_bookmark(QPoint(screen.left()+30,screen.top()+60))
    bookmark.set_working(True,animate=False,scan=False)
    assert not bookmark._upward
    handle=bookmark.handle_rect().center()
    QTest.mousePress(bookmark,Qt.MouseButton.LeftButton,pos=handle)
    QTest.mouseMove(bookmark,handle+QPoint(0,screen.height()))
    QTest.mouseRelease(bookmark,Qt.MouseButton.LeftButton,pos=handle)
    assert bookmark._upward and bookmark.resize_corner()=='tr'
    size=bookmark.capture_rect().size()
    bookmark.set_working(False,animate=False)
    bookmark.set_working(True,animate=False,scan=False)
    assert bookmark.capture_rect().size()==size
