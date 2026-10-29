"""Bookmark desktop surface, independent of OCR / provider implementation."""
from __future__ import annotations

import json
import math
import sys
import time
from dataclasses import replace

from PySide6.QtCore import QEasingCurve, QPoint, QRect, QRectF, Qt, QVariantAnimation, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPainterPath, QPen, QPixmap, QRegion
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QKeySequenceEdit, QLabel, QVBoxLayout, QWidget, QToolTip

from .frame import RecognitionFrame, MIN_WIDTH, MIN_HEIGHT, resized_rect
from .hotkey import ToggleHotkey
from .settings import config_dir
from .catalog import load_catalog, load_enabled
from .capture import capture_region
from .window_capture import capture_underlay

PAD = 26


def scope_geometry(anchor: QPoint, size, screen: QRect):
    """Place scope beside the bookmark, preserving its desktop position."""
    leftward = anchor.x()+18 > screen.center().x()
    available = anchor.x()-screen.left()-10 if leftward else screen.right()-anchor.x()-46
    width = max(60, min(size.width(), available))
    height = min(size.height(), screen.height()-24)
    x = anchor.x()-width-8 if leftward else anchor.x()+44
    y = max(screen.top()+12, min(anchor.y(), screen.bottom()-height-12))
    return QRect(x, y, width, height), leftward


def rounded_region(rect, radius=9):
    path = QPainterPath()
    path.addRoundedRect(QRectF(rect), radius, radius)
    return QRegion(path.toFillPolygon().toPolygon())


class AuxiliaryWindow(QWidget):
    def __init__(self, owner, *, interactive=False):
        flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint
        if owner.settings.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        if not interactive:
            flags |= Qt.WindowType.WindowTransparentForInput | Qt.WindowType.WindowDoesNotAcceptFocus
        super().__init__(None, flags)
        self.owner = owner
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)


class BookmarkWindow(AuxiliaryWindow):
    def __init__(self, owner):
        super().__init__(owner, interactive=True)
        self.setWindowTitle('FloatTranslate · 书签')
        self.resize(48, 90)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._origin = None
        self._moved = False
        self._hover = False
        self.setToolTip('点击展开 / 收起 · 拖动移动 · 右键设置')

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.moveTo(7, 2)
        path.lineTo(35, 2)
        path.quadTo(42, 2, 42, 9)
        path.lineTo(42, 72)
        path.lineTo(18, 72)
        path.lineTo(5, 82)
        path.lineTo(5, 9)
        path.quadTo(5, 2, 7, 2)
        p.setPen(Qt.PenStyle.NoPen)
        p.fillPath(path, QColor('#2775ff' if self._hover else '#1460ff'))
        p.setBrush(Qt.GlobalColor.white)
        if self.owner._busy:
            # Keep activity local to the bookmark; the selection stays still.
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(255, 255, 255, 210), 1.6,
                          Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            angle = 90 if self.owner.settings.reduce_motion else -self.owner._phase
            p.drawArc(QRectF(18, 12, 11, 11), round(angle*16), 260*16)
        else:
            p.setPen(Qt.PenStyle.NoPen)
            for x in (18,23,28):
                for y in (15,20):
                    p.drawEllipse(QPoint(x,y),1,1)
        p.setPen(Qt.GlobalColor.white)
        font = QFont(QApplication.font())
        font.setPixelSize(22)
        font.setBold(True)
        p.setFont(font)
        p.drawText(QRect(5,29,37,34),Qt.AlignmentFlag.AlignCenter,'译')
        p.end()

    def enterEvent(self, event):
        self._hover = True
        self.update()
        if self.owner.working:
            self.owner._handle_visible = True
            self.owner._update_native_mask()
            self.owner.update()

    def leaveEvent(self, event):
        self._hover = False
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.globalPosition().toPoint()
            self._start = self.pos()
            self._moved = False
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event):
        if self._origin is None:
            return
        delta = event.globalPosition().toPoint()-self._origin
        if delta.manhattanLength() < 5 and not self._moved:
            return
        if not self._moved:
            self.owner.clear_translation()
            self.owner._stop_transition()
        self._moved = True
        self.owner.move_bookmark(self._start+delta)

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self._origin is None:
            return
        moved = self._moved
        self._origin = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        if moved:
            self.owner._save_bookmark()
            if self.owner.working:
                QTimer.singleShot(200, self.owner._automatic_scan)
        else:
            self.owner.toggle_working()

    def contextMenuEvent(self, event):
        self.owner.contextMenuEvent(event)

    def nativeEvent(self, event_type, message):
        if sys.platform == 'win32':
            import ctypes
            from ctypes.wintypes import MSG
            msg = MSG.from_address(int(message))
            if msg.message == 0x0312 and msg.wParam == self.owner.hotkey.ID:
                self.owner.toggle_working()
                return True, 0
            if msg.message == 0x0312 and msg.wParam == self.owner.translate_hotkey.ID:
                self.owner.request_keyboard_translation()
                return True,0
        return super().nativeEvent(event_type, message)

    def keyPressEvent(self,event):
        self.owner.keyPressEvent(event)


class HaloWindow(AuxiliaryWindow):
    """Reserved auxiliary surface; activity now lives in the bookmark."""


class TransitionWindow(AuxiliaryWindow):
    def __init__(self, owner):
        super().__init__(owner)
        self.snapshot = QPixmap()
        self.progress = 0.0
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(460)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.valueChanged.connect(self._tick)
        self.animation.finished.connect(owner._transition_finished)

    def _tick(self, value):
        self.progress = float(value)
        self.update()

    def paintEvent(self, event):
        if self.snapshot.isNull():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        point = self.owner.bookmark.geometry().center()-self.pos()
        offset = self.owner.pos()-self.pos()
        sx, sy = .025+.975*self.progress, .12+.88*self.progress
        p.save()
        p.translate(point)
        p.scale(sx, sy)
        p.translate(-point)
        p.setOpacity(min(1,self.progress*3))
        p.drawPixmap(offset,self.snapshot)
        p.restore()
        # Keep the thin frame legible at small scales instead of downsampling
        # a 1px raster stroke out of existence. Contents still scale together.
        box = QRectF(self.owner.content_rect()).translated(offset)
        visible = QRectF(point.x()+(box.x()-point.x())*sx,
                         point.y()+(box.y()-point.y())*sy,
                         box.width()*sx,box.height()*sy)
        p.setOpacity(min(1,self.progress*3))
        p.setPen(QPen(QColor('#aac7f4'),1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(visible,min(9,visible.height()/4),min(9,visible.height()/4))
        p.end()



class BookmarkFrame(RecognitionFrame):
    def __init__(self, *args, **kwargs):
        self._ready = False
        self.working = False
        self._transitioning = False
        self._laying_out = False
        self._handle_visible = False
        self._settings_dirty = False
        self._mode_epoch = 0
        self._manual_on_open = False
        self._pending_manual = False
        self._independent_capture_available = False
        self._source_hwnd = None
        self._leftward = False
        self._upward = False
        super().__init__(*args, **kwargs)
        self._hint = False
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._preferred_size = self.content_rect().size()
        self.bookmark = BookmarkWindow(self)
        self.halo = HaloWindow(self)
        self.transition = TransitionWindow(self)
        self.hotkey = ToggleHotkey(self.bookmark)
        self.hotkey.activated.connect(self.toggle_working)
        self.translate_hotkey=ToggleHotkey(self.bookmark,hotkey_id=0x4655,allow_enter=True)
        self.translate_hotkey.activated.connect(self.request_keyboard_translation)
        self._ready = True
        self._auto = False
        self.view_timer.setInterval(350)
        self.bookmark.move(self._load_bookmark())
        self.move_bookmark(self.bookmark.pos())
        self.bookmark.show()
        from .about import UpdateController
        self.updater = UpdateController(self)
        for controller,text in ((self.hotkey,self.settings.toggle_shortcut),(self.translate_hotkey,self.settings.translate_shortcut)):
            try:
                controller.install(text)
            except (ValueError,ImportError) as error:
                QTimer.singleShot(500,lambda message=str(error):self.notify(message))

    def show(self):
        if not self._ready or self.working and not self._transitioning:
            super().show()
        if self._ready:
            self.bookmark.show()

    def _load_bookmark(self):
        default = QPoint(self.x()-44,self.y()+14)
        if not self.test_mode:
            try:
                data = json.loads((config_dir()/'bookmark.json').read_text('utf-8'))
                point = QPoint(int(data[0]),int(data[1]))
                if any(screen.availableGeometry().contains(point) for screen in QGuiApplication.screens()):
                    return point
            except (OSError, ValueError, TypeError, IndexError):
                pass
        return default

    def _save_bookmark(self):
        if self.test_mode:
            return
        try:
            config_dir().mkdir(parents=True,exist_ok=True)
            temporary = config_dir()/'bookmark.json.tmp'
            temporary.write_text(json.dumps([self.bookmark.x(),self.bookmark.y()]),'utf-8')
            temporary.replace(config_dir()/'bookmark.json')
        except OSError:
            pass

    def move_bookmark(self, point):
        screen = QGuiApplication.screenAt(point+QPoint(24,40)) or self.bookmark.screen()
        bounds = screen.availableGeometry()
        point.setX(max(bounds.left(),min(point.x(),bounds.right()-48)))
        point.setY(max(bounds.top(),min(point.y(),bounds.bottom()-90)))
        self.bookmark.move(point)
        scope,self._leftward = scope_geometry(point,self._preferred_size,bounds)
        self._upward=scope.top()<point.y()
        self._laying_out = True
        self.setGeometry(scope.adjusted(-14,-14,14,14))
        self._laying_out = False
        self._sync_halo()
        self._update_native_mask()
        self.update()

    def content_rect(self):
        return self.rect().adjusted(14,14,-14,-14)

    def resize_corner(self):
        return ('t' if self._upward else 'b')+('l' if self._leftward else 'r')

    def handle_rect(self):
        box = self.content_rect()
        return QRect(box.left()-7 if self._leftward else box.right()-7,
                     box.top()-7 if self._upward else box.bottom()-7,15,15)

    def _update_native_mask(self):
        if not getattr(self,'_ready',False):
            return
        if not self._shaped:
            return
        box = self.content_rect()
        mask = rounded_region(box.adjusted(-1,-1,1,1))-rounded_region(box.adjusted(1,1,-1,-1),8)
        if self._handle_visible:
            mask |= rounded_region(self.handle_rect(),4)
        for item in self._regions:
            mask |= QRegion(self._region_box(item).translated(box.topLeft()).toAlignedRect())
        if self.mask() != mask:
            self.setMask(mask)

    def paintEvent(self, event):
        if not self._ready:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.save()
        p.setClipRect(self.content_rect().adjusted(2,2,-2,-2))
        p.translate(self.content_rect().topLeft())
        p.setOpacity(self._alpha)
        from PySide6.QtGui import QFontMetrics
        for item in self._regions:
            source = item.source
            box = self._region_box(item)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255,255,255,255 if self._shaped else round(255*self.settings.mask_opacity/100)))
            p.drawRoundedRect(box,3,3)
            text_box = box.adjusted(3,1,-3,-1)
            font = QFont(QApplication.font())
            line_height = source.height/max(1,source.text.count('\n')+1)/self._image_scale
            if line_height >= 28:
                font.setWeight(QFont.Weight.DemiBold)
            flags = Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            for size in range(min(self.settings.font_size,max(10,round(line_height*.9))),5,-1):
                font.setPixelSize(size)
                measured = QFontMetrics(font).boundingRect(text_box.toRect(),int(flags),item.translation)
                if measured.height() <= text_box.height() and measured.width() <= text_box.width():
                    break
            p.setFont(font)
            p.setPen(QColor('#202433'))
            p.save()
            p.setClipRect(text_box)
            p.drawText(text_box,int(flags),item.translation)
            p.restore()
        p.restore()
        border = QRectF(self.content_rect())
        width = max(1,min(2,self.settings.border_width)*.75)
        color = QColor('#a2aabb' if self._paused else '#c47487' if self._last_status.startswith('错误') else '#8dadd5')
        p.setBrush(Qt.BrushStyle.NoBrush)
        if self._busy and not self._paused and not self._last_status.startswith('错误'):
            # A fixed-size contour gently brightens over 3.2 seconds. Never
            # expand the outline or fade the translated content with it.
            elapsed = time.monotonic()-self._breath_started
            strength = 0.5-0.5*math.cos(math.tau*elapsed/3.2)
            if self.settings.reduce_motion:
                strength = 0.5
            color = QColor('#4387ee')
            color.setAlpha(round(150+90*strength))
            if not self._shaped:
                # One compact glow, clipped outside the selection, with no
                # auxiliary window, concentric outlines or changing radius.
                p.save()
                outside = QRegion(self.rect())-QRegion(self.content_rect())
                p.setClipRegion(outside)
                p.setPen(QPen(QColor(70,135,245,round(8+12*strength)),5))
                p.drawRoundedRect(border,9,9)
                p.restore()
        p.setPen(QPen(color,width))
        p.drawRoundedRect(border,9,9)
        if self._handle_visible:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor('#1460ff'))
            p.drawRoundedRect(QRectF(self.handle_rect()),4,4)
        p.end()

    def _snapshot(self):
        pix = QPixmap(self.size())
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        # Explicit full source rect prevents Qt from rebasing the shaped
        # window mask to its bounding-box origin (which clipped the ring).
        self.render(painter,QPoint(),QRegion(self.rect()),
                    QWidget.RenderFlag.DrawChildren | QWidget.RenderFlag.IgnoreMask)
        painter.end()
        return pix

    def _stop_transition(self):
        if not self._ready:
            return
        self.transition.animation.stop()
        self.transition.hide()
        self._transitioning = False
        if self.working:
            super().show()
            self._refresh_capture_exclusion()

    def toggle_working(self):
        if self._dialog is not None:
            self._dialog.raise_()
            return
        self.set_working(not self.working)
        if self.working:
            self.bookmark.activateWindow()
            self.bookmark.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def set_working(self, working, *, animate=True, scan=True):
        if working == self.working and not self._transitioning:
            return
        # Reverse in-flight animation without jumping to either endpoint.
        progress = self.transition.progress if self._transitioning else (1.0 if self.working else 0.0)
        if self._transitioning:
            self.transition.animation.stop()
        self._mode_epoch+=1
        self.working = working
        if not working:
            self._manual_on_open=False
            self._pending_manual=False
            self._rescan_needed=False
        self._cancel_scan.set()
        self._revision += 1
        self._set_busy(False)
        self.scan_timer.stop()
        self.view_timer.stop()
        self.halo.hide()
        if working:
            self.move_bookmark(self.bookmark.pos())
        self._handle_visible = True
        self._update_native_mask()
        if animate and not self.settings.reduce_motion:
            if not self._transitioning:
                self.transition.snapshot = self._snapshot()
            self.transition.setGeometry(self.geometry().united(self.bookmark.geometry()).adjusted(-3,-3,3,3))
            self.transition.progress = progress
            self._transitioning = True
            self.hide()
            self.transition.show()
            self.transition.animation.setStartValue(progress)
            self.transition.animation.setEndValue(1.0 if working else 0.0)
            self.transition.animation.setDuration(max(100,round(460*abs((1 if working else 0)-progress))))
            self._scan_on_open = scan
            self.transition.animation.start()
        else:
            self._scan_on_open = scan
            self._transition_finished()
        self.bookmark.raise_()

    def _transition_finished(self):
        self.transition.hide()
        self._transitioning = False
        if self.working:
            super().show()
            self._refresh_capture_exclusion()
            if sys.platform=="win32":
                self._underlay()
            self.bookmark.raise_()
            if self._auto:
                self.scan_timer.start()
            if self.visible_capture_available():
                self.view_timer.start()
            if self._manual_on_open:
                self._manual_on_open=False
                self.queue_manual_translation(100)
            elif self._scan_on_open and self._auto:
                QTimer.singleShot(100,self._automatic_scan)
        else:
            self.hide()
            self._regions = []
            self._observed_scene = None
            self._observed_frame = None
            self._rendered_scene = None
            self.halo.hide()
        self._save_bookmark()

    def _sync_halo(self):
        if self._ready:
            self.halo.setGeometry(self.geometry().adjusted(-PAD,-PAD,PAD,PAD))

    def _set_busy(self, busy):
        if busy and not self._busy:
            self._breath_started = time.monotonic()
        super()._set_busy(busy)
        if self._ready:
            self._sync_halo()
            self.halo.hide()
            self.update()
            if busy:
                self.bookmark.raise_()
            self.bookmark.update()

    def _animate(self):
        self._phase = (self._phase+10) % 360
        if self._ready:
            # Update only the contour band, not the translated paragraphs.
            inner = self.content_rect().adjusted(3,3,-3,-3)
            self.update(QRegion(self.rect())-QRegion(inner))
            self.bookmark.update()

    def _refresh_capture_exclusion(self):
        self._update_native_mask()
        # Source-window capture does not need desktop affinity. Keeping the
        # overlay normally composited also avoids black borders in screenshots.
        if sys.platform=='win32':
            import ctypes
            ctypes.windll.user32.SetWindowDisplayAffinity.argtypes=[ctypes.c_void_p,ctypes.c_uint]
            ctypes.windll.user32.SetWindowDisplayAffinity(int(self.winId()),0)
        self._excluded=False

    def visible_capture_available(self):
        return self._independent_capture_available if sys.platform=='win32' else super().visible_capture_available()

    def _underlay(self):
        ignored=[int(window.winId()) for window in (self,self.bookmark,self.halo,self.transition)]
        result=capture_underlay(self.capture_rect(),ignored)
        self._independent_capture_available=result is not None
        if result is not None:
            image,scale,hwnd=result
            if self._source_hwnd is not None and self._source_hwnd!=hwnd and (self._regions or self._busy):
                self._invalidate_view()
            self._source_hwnd=hwnd
            self._capture_backend="源窗口直读（与译文分离）"
            return image,scale
        return None

    def watch_capture(self):
        if sys.platform=='win32':
            result=self._underlay()
            if result is None:
                # An affinity flag is not proof that a desktop capture contains
                # the underlay. Never cancel a translation using that capture.
                raise RuntimeError('当前窗口不支持独立画面监测')
            return result
        return super().watch_capture()

    def scan_capture(self):
        if sys.platform=='win32':
            result=self._underlay()
            if result is not None:
                return result
            self._capture_backend="兼容截图（暂停不可靠的后台画面监测）"
            # Explicit, clean one-shot fallback. Keep the bookmark available.
            was_visible=self.isVisible()
            self._capturing=True
            try:
                self.hide()
                QGuiApplication.sync()
                try:
                    import ctypes
                    ctypes.windll.dwmapi.DwmFlush()
                except (AttributeError,OSError):
                    pass
                return capture_region(self.capture_rect())
            finally:
                self._capturing=False
                if was_visible and self.working and not self._transitioning:
                    super().show()
                    self._refresh_capture_exclusion()
        return super().scan_capture()

    def request_keyboard_translation(self):
        if self._dialog is None and not self._menu_open and QApplication.activePopupWidget() is None:
            self.scan(force=True)

    def keyPressEvent(self,event):
        if event.key() in (Qt.Key.Key_Return,Qt.Key.Key_Enter):
            modifiers=event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
            if modifiers==Qt.KeyboardModifier.NoModifier:
                event.accept()
                if not event.isAutoRepeat():
                    self.request_keyboard_translation()
            else:
                event.ignore()
            return
        super().keyPressEvent(event)

    def queue_manual_translation(self,delay=0):
        epoch=self._mode_epoch
        QTimer.singleShot(delay,lambda:self.scan(force=True) if self._mode_epoch==epoch and not self._closing else None)

    def scan(self, force=False):
        if not self._ready or self.bookmark._origin is not None:
            return
        if not self.working:
            if force:
                self._manual_on_open=True
                self.set_working(True,scan=False)
            return
        if self._transitioning:
            if force:
                self._manual_on_open=True
            return
        if self._jobs:
            if force:
                self._pending_manual=True
                self._rescan_needed = True
            return
        super().scan(force=force)

    def _automatic_scan(self):
        if self.working and not self._transitioning:
            super()._automatic_scan()

    def _watch_view(self):
        if self.working and not self._transitioning and self.bookmark._origin is None:
            super()._watch_view()

    def set_auto(self, enabled):
        if not enabled:
            automatic=[record for record in self._run_records.values() if record.get('trigger')=='auto']
            if automatic:
                for record in automatic:
                    record['cancel_reason']='已关闭自动翻译'
                self._cancel_scan.set()
                self._revision+=1
                self._set_busy(False)
            self._rescan_needed=self._pending_manual
        if enabled and not self.working:
            self._auto = True
            self.set_working(True)
        else:
            super().set_auto(enabled)

    def _progress(self, payload):
        if self.working and not self._transitioning:
            super()._progress(payload)

    def _completed(self, payload):
        rescan = self._rescan_needed
        manual=self._pending_manual
        self._pending_manual=False
        # Own the one pending rescan here. The base stale-result handler must
        # not also schedule a second scan that cancels the replacement task.
        self._rescan_needed=False
        super()._completed(payload)
        if rescan and self.working and not self._jobs and not self._closing:
            if manual:
                self.queue_manual_translation(150)
            elif self._auto:
                if self._view_unstable:
                    self._rescan_needed=True
                else:
                    QTimer.singleShot(150,self._automatic_scan)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.activateWindow()
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        if self.handle_rect().adjusted(-7,-7,7,7).contains(event.position().toPoint()):
            self._drag_origin = event.globalPosition().toPoint()
            self._drag_geometry = self.geometry()
            self._drag_edge = self.resize_corner()
            self.clear_translation()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_origin is not None:
            delta = event.globalPosition().toPoint()-self._drag_origin
            rect = resized_rect(self._drag_geometry,self._drag_edge,delta)
            screen = self.bookmark.screen().availableGeometry().adjusted(2,12,-3,-12).adjusted(-14,-14,14,14)
            rect = rect.intersected(screen)
            if rect.width() >= MIN_WIDTH and rect.height() >= MIN_HEIGHT:
                self.setGeometry(rect)
                self._preferred_size = self.content_rect().size()
                self._sync_halo()
            event.accept()
        else:
            self._handle_visible = True
            self._update_native_mask()
            self.setCursor(self._cursor_for_edge(self.resize_corner()) if self.handle_rect().adjusted(-7,-7,7,7).contains(event.position().toPoint()) else Qt.CursorShape.ArrowCursor)
            self.update()

    def mouseReleaseEvent(self, event):
        if self._drag_origin is not None:
            self._drag_origin = None
            self._drag_edge = None
            box=self.capture_rect()
            bounds=self.bookmark.screen().availableGeometry()
            # Keep the pressed corner stable during the gesture. Once a bottom
            # edge reaches the work area, offer the upper corner for the next
            # gesture so users can continue growing upwards.
            if box.bottom()>=bounds.bottom()-13:
                self._upward=True
            elif box.top()<=bounds.top()+13:
                self._upward=False
            self._update_native_mask()
            self.update()
            if self.working:
                QTimer.singleShot(200,self._automatic_scan)

    def moveEvent(self, event):
        super().moveEvent(event)
        if self._ready:
            self._sync_halo()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._ready:
            self._sync_halo()

    def _populate_menu(self, menu, tray=False):
        menu.clear()
        if tray:
            self._action(menu,'显示并恢复交互',self.restore_interaction)
        self._action(menu,('收起，进入待机' if self.working else '展开翻译区域')+'  '+self.settings.toggle_shortcut,
                     lambda:QTimer.singleShot(0,self.toggle_working))
        self._action(menu,'立即翻译  '+self.settings.translate_shortcut.replace('Return','Enter'),lambda:self.queue_manual_translation(120),enabled=not self._busy)
        self._action(menu,'自动翻译',self.set_auto,check=self._auto)
        models=menu.addMenu('选择模型')
        try:
            connection=self._connection()
            self._models=load_catalog(connection) or self._models
            choices=load_enabled(connection,self.settings.model)
        except (ValueError,RuntimeError):
            choices=[self.settings.model] if self.settings.model else []
        for model in choices:
            self._action(models,model,lambda checked=False,name=model:self.select_model(name),check=model==self.settings.model)
        if choices:
            models.addSeparator()
        self._action(models,'勾选 / 管理模型…',self.choose_model)
        settings=menu.addMenu('设置')
        for title,page in [('API 与模型…','api'),('OCR 与语言…','ocr'),('外观与动效…','appearance')]:
            self._action(settings,title,lambda checked=False,p=page:self.preferences(p))
        self._action(settings,'快捷键…',self.shortcut_preferences)
        settings.addSeparator()
        self._action(settings,'暂停识别',self.set_paused,check=self._paused)
        self._action(settings,'鼠标穿透（从托盘恢复）',self.set_pass_through,check=self._pass_through,enabled=self.tray is not None)
        self._action(settings,'操作说明',self.show_help)
        self._action(menu,'显示原文',self.clear_translation,enabled=bool(self._regions))
        self._action(menu,'复制译文',lambda:QApplication.clipboard().setText(self._last_translation),enabled=bool(self._last_translation))
        self._action(menu,'翻译耗时与诊断…',self.show_timings,enabled=bool(self._metrics))
        if self._last_status.startswith('错误'):
            self._action(menu,self._last_status[:38],self.show_timings)
        menu.addSeparator()
        self._action(menu,'关于 / 检查更新…',self.show_about)
        self._action(menu,'退出',self.close)

    def show_about(self):
        from .about import show_about
        show_about(self)

    def shortcut_preferences(self):
        if self._dialog:
            self._dialog.raise_()
            return
        dialog = QDialog(self.bookmark)
        dialog.setWindowTitle('翻译与展开快捷键')
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel('展开 / 收起（全局）'))
        edit = QKeySequenceEdit(self.settings.toggle_shortcut,dialog)
        edit.setMaximumSequenceLength(1)
        layout.addWidget(edit)
        layout.addWidget(QLabel('立即翻译（全局）'))
        translate_edit=QKeySequenceEdit(self.settings.translate_shortcut,dialog)
        translate_edit.setMaximumSequenceLength(1)
        layout.addWidget(translate_edit)
        layout.addWidget(QLabel('普通 Enter：点击书签或边框后翻译。输入框中的 Enter 不会触发翻译。'))
        note = QLabel('使用 Alt / Ctrl / Meta 加字母、数字或 F1–F12；立即翻译键还支持 Enter。')
        note.setWordWrap(True)
        layout.addWidget(note)
        if sys.platform == 'darwin':
            layout.addWidget(QLabel('macOS 全局响应需要系统“辅助功能”权限。'))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(buttons)
        def save():
            text = edit.keySequence().toString()
            previous = self.settings.toggle_shortcut
            previous_translate=self.settings.translate_shortcut
            translate_text=translate_edit.keySequence().toString()
            try:
                self.hotkey.install(text)
                self.translate_hotkey.install(translate_text)
                settings = replace(self.settings,toggle_shortcut=text,translate_shortcut=translate_text)
                if not self.test_mode:
                    settings.save()
                self.settings = settings
                dialog.accept()
            except (ValueError,OSError,ImportError) as error:
                try:
                    self.hotkey.install(previous)
                    self.translate_hotkey.install(previous_translate)
                except (ValueError,ImportError):
                    pass
                note.setText(str(error))
        buttons.accepted.connect(save)
        buttons.rejected.connect(dialog.reject)
        self._dialog = dialog
        dialog.finished.connect(lambda code:setattr(self,'_dialog',None))
        dialog.show()

    def apply_settings(self, settings):
        visible = self.working
        self._settings_dirty = settings != self.settings
        top_changed = settings.always_on_top != self.settings.always_on_top
        if top_changed:
            self.hotkey.close()
            self.translate_hotkey.close()
        super().apply_settings(settings)
        for window in (self.bookmark,self.halo,self.transition):
            window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint,settings.always_on_top)
        self.bookmark.show()
        if top_changed:
            for controller,text in ((self.hotkey,settings.toggle_shortcut),(self.translate_hotkey,settings.translate_shortcut)):
                try:
                    controller.install(text)
                except (ValueError,ImportError) as error:
                    self.notify(str(error))
        if not visible:
            self.hide()
        self._sync_halo()
        if self._settings_dirty and self._dialog is None and self.working:
            self._settings_dirty=False
            QTimer.singleShot(160,self._automatic_scan)

    def _restore_after_preferences(self):
        if self._closing:
            return
        if self.working:
            super()._restore_after_preferences()
        else:
            self.hide()
        self.bookmark.show()
        self.bookmark.raise_()
        if self._settings_dirty:
            self._settings_dirty=False
            if self.working:
                QTimer.singleShot(160,self._automatic_scan)

    def restore_interaction(self):
        self.set_pass_through(False)
        if not self.working:
            self.set_working(True)
        self.bookmark.raise_()

    def show_help(self):
        self.notify('点击书签或 '+self.settings.toggle_shortcut+'：展开 / 收起\n拖动整块书签：移动\n蓝色角部触点：缩放（触底时移到上方）\n右键书签 / 边框 / 托盘：全部设置\nEnter（点选书签 / 边框后）：翻译；Esc：显示原文\n全局立即翻译：'+self.settings.translate_shortcut.replace('Return','Enter')+'\n翻译时外沿呼吸，完成后保持静止')

    def _save_geometry(self):
        if self._ready:
            self._save_bookmark()
        super()._save_geometry()

    def closeEvent(self, event):
        if self._ready:
            self.hotkey.close()
            self.translate_hotkey.close()
            self.transition.animation.stop()
            for window in (self.bookmark,self.halo,self.transition):
                window.hide()
        super().closeEvent(event)
