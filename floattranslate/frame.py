from __future__ import annotations

import json
import math
import sys
import time
import hashlib
import threading
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve, QPoint, QRect, QRectF, Qt, QThreadPool, QTimer, Property,
    QPropertyAnimation, Slot,
)
from PySide6.QtGui import (
    QAction, QColor, QConicalGradient, QCursor, QFont, QFontMetrics,
    QGuiApplication, QIcon, QPainter, QPainterPath, QPen, QPixmap, QRegion,
)
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QToolTip, QWidget

from .capture import capture_region, exclude_from_capture
from .mac_surface import keep_tool_visible, refresh_surface
from .dialogs import Preferences
from .ocr import create_ocr, screen_permission
from .pipeline import Pipeline
from .providers import BY_ID, identify, resolve
from .settings import Settings, SecretStore, config_dir
from .tasks import Task
from .interaction import forward_wheel
from .scene import Scene, changed as scene_changed
from .catalog import load_catalog, load_enabled, save_enabled
from .model_picker import ModelPicker

MARGIN = 14
DRAG_BAR_HEIGHT = 28
CORNER_TARGET = 24
RESIZE_EDGE = 6
MIN_WIDTH, MIN_HEIGHT = 140, 90


def edge_at(point: QPoint, width: int, height: int, margin: int = MARGIN) -> str:
    vertical = "t" if point.y() < margin else "b" if point.y() >= height-margin else ""
    horizontal = "l" if point.x() < margin else "r" if point.x() >= width-margin else ""
    return vertical + horizontal


def interaction_at(point: QPoint,width: int,height: int) -> str:
    """24px resize corners, 6px outer resize edges, wide inner move bands."""
    x,y = point.x(),point.y()
    vertical = "t" if y<CORNER_TARGET else "b" if y>=height-CORNER_TARGET else ""
    horizontal = "l" if x<CORNER_TARGET else "r" if x>=width-CORNER_TARGET else ""
    if vertical and horizontal:
        return vertical+horizontal
    return edge_at(point,width,height,RESIZE_EDGE)


def resized_rect(start: QRect, edge: str, delta: QPoint) -> QRect:
    left, top = start.left(), start.top()
    right, bottom = left + start.width(), top + start.height()
    if "l" in edge:
        left = min(right-MIN_WIDTH, left+delta.x())
    if "r" in edge:
        right = max(left+MIN_WIDTH, right+delta.x())
    if "t" in edge:
        top = min(bottom-MIN_HEIGHT, top+delta.y())
    if "b" in edge:
        bottom = max(top+MIN_HEIGHT, bottom+delta.y())
    return QRect(left, top, right-left, bottom-top)


def app_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#4567ed"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(QRectF(4, 4, 56, 56), 14, 14)
    painter.setPen(QPen(Qt.GlobalColor.white, 3.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for x, y, dx, dy in [(18,18,1,1), (46,18,-1,1), (18,46,1,-1), (46,46,-1,-1)]:
        painter.drawLine(x, y, x+dx*9, y)
        painter.drawLine(x, y, x, y+dy*9)
    painter.end()
    return QIcon(pixmap)


class RecognitionFrame(QWidget):
    def __init__(self, settings: Settings | None = None, *, ocr=None, pipeline=None, test_mode=False):
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.NoDropShadowWindowHint
        self.settings = settings or Settings.load()
        if self.settings.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        super().__init__(None, flags)
        keep_tool_visible(self)
        self.setWindowTitle("FloatTranslate Next")
        self.setWindowIcon(app_icon())
        # Per-pixel layered windows reject Windows capture exclusion (error 8).
        # A shaped opaque HWND has real holes instead and supports exclusion.
        self._shaped = sys.platform == "win32"
        if not self._shaped:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setMinimumSize(MIN_WIDTH, MIN_HEIGHT)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.test_mode = test_mode
        self.secrets = SecretStore()
        self.ocr = ocr or create_ocr()
        self.pipeline = pipeline or Pipeline(self.ocr)
        self.worker_pool = QThreadPool(self)
        self.worker_pool.setMaxThreadCount(1)
        self.preferences_pool = QThreadPool(self)
        self.preferences_pool.setMaxThreadCount(2)
        self._jobs = {}
        self._revision = 0
        self._busy = False
        self._capture_pending = False
        self._capturing = False
        self._auto = False
        self._paused = False
        self._pass_through = False
        self._closing = False
        self._menu_open = False
        self._dialog = None
        self._drag_edge = None
        self._drag_origin = None
        self._drag_geometry = None
        self._excluded = False
        self._phase = 0.0
        self._alpha = 1.0
        self._regions = []
        self._image_scale = 1.0
        self._last_status = "就绪"
        self._last_source = ""
        self._last_translation = ""
        self._hint = True
        self._backoff_until = 0.0
        self._failures = 0
        self._models = []
        self._observed_frame = None
        self._observed_scene = None
        self._rendered_scene = None
        self._rendered_context = None
        self._pending_scene = None
        self._pending_context = None
        self._view_unstable = False
        self._last_view_change = 0.0
        self._rescan_needed = False
        self._cancel_scan = threading.Event()
        self._metrics = {}
        self._metrics_history = []
        self._run_records = {}
        self._attempt_counter = 0
        self._run_counts = {"total":0,"manual":0,"auto":0}
        self._capture_ms = 0
        self.view_timer = QTimer(self)
        self.view_timer.setInterval(180)
        self.view_timer.timeout.connect(self._watch_view)
        self.animation_timer = QTimer(self)
        self.animation_timer.setInterval(33)
        self.animation_timer.timeout.connect(self._animate)
        self.scan_timer = QTimer(self)
        self.scan_timer.setInterval(self.settings.interval_ms)
        self.scan_timer.timeout.connect(self._automatic_scan)
        self.fade = QPropertyAnimation(self, b"overlayOpacity", self)
        self.fade.setDuration(160)
        self.fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.setGeometry(self._load_geometry())
        self.tray = None
        if not test_mode and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(app_icon(), self)
            self.tray.setToolTip("FloatTranslate · 右键打开菜单")
            self._tray_menu = QMenu(self)
            self._tray_menu.aboutToShow.connect(lambda: self._populate_menu(self._tray_menu, tray=True))
            self.tray.setContextMenu(self._tray_menu)
            self.tray.activated.connect(self._tray_activated)
            self.tray.show()
        QTimer.singleShot(0, self._refresh_capture_exclusion)
        QTimer.singleShot(9000, self._hide_hint)

    def showEvent(self, event):
        super().showEvent(event)
        if sys.platform == "darwin":
            self._refresh_native_surface()
            QTimer.singleShot(0, self._refresh_native_surface)

    def _refresh_native_surface(self):
        if self.isVisible() and not self._closing:
            refresh_surface(self)

    def _load_geometry(self):
        screen = QGuiApplication.primaryScreen().availableGeometry()
        default = QRect(screen.center().x()-360, screen.center().y()-200, 720, 400)
        if self.test_mode:
            return default
        try:
            values = json.loads((config_dir()/"geometry.json").read_text("utf-8"))
            if len(values) != 4 or not all(type(v) is int for v in values):
                return default
            rect = QRect(*values)
            if rect.width() < MIN_WIDTH or rect.height() < MIN_HEIGHT or rect.width() > 10000 or rect.height() > 10000:
                return default
            if any(rect.intersected(s.availableGeometry()).width() >= 80 and rect.intersected(s.availableGeometry()).height() >= 60 for s in QGuiApplication.screens()):
                return rect
        except (OSError, ValueError, TypeError):
            pass
        return default

    def _save_geometry(self):
        if self.test_mode:
            return
        directory = config_dir()
        directory.mkdir(parents=True, exist_ok=True)
        rect = self.geometry()
        temporary = directory/"geometry.json.tmp"
        temporary.write_text(json.dumps([rect.x(), rect.y(), rect.width(), rect.height()]), "utf-8")
        temporary.replace(directory/"geometry.json")

    @Slot()
    def _refresh_capture_exclusion(self):
        self._update_native_mask()
        self._excluded = exclude_from_capture(self)

    def _region_box(self, item):
        source = item.source
        content = self.content_rect()
        box = QRectF(source.x/self._image_scale-8, source.y/self._image_scale-4,
                     source.width/self._image_scale+16, source.height/self._image_scale+8)
        return box.intersected(QRectF(0, 0, content.width(), content.height()))

    def _update_native_mask(self):
        if not self._shaped:
            return
        outer = QPainterPath()
        outer.addRoundedRect(QRectF(self.rect()).adjusted(3,3,-3,-3), 9,9)
        inner = QPainterPath()
        inner.addRoundedRect(QRectF(self.rect()).adjusted(MARGIN,MARGIN,-MARGIN,-MARGIN), 6,6)
        mask = QRegion(outer.toFillPolygon().toPolygon())-QRegion(inner.toFillPolygon().toPolygon())
        for x,y in [(0,0),(self.width()-CORNER_TARGET,0),(0,self.height()-CORNER_TARGET),(self.width()-CORNER_TARGET,self.height()-CORNER_TARGET)]:
            mask |= QRegion(QRect(x,y,CORNER_TARGET,CORNER_TARGET))
        mask |= QRegion(QRect(3,3,self.width()-6,DRAG_BAR_HEIGHT-3))
        for item in self._regions:
            mask |= QRegion(self._region_box(item).translated(self.content_rect().topLeft()).toAlignedRect())
        if self._hint and not self._regions:
            width = min(410, self.width()-28)
            mask |= QRegion(QRect((self.width()-width)//2, self.height()//2-12, width,24))
        # SetWindowRgn redraws a native window even when the region is identical.
        # Do not keep resetting an unchanged mask on the periodic scan timer.
        if self.mask() != mask:
            self.setMask(mask)

    @staticmethod
    def _fingerprint(image):
        return (image.size, hashlib.blake2b(image.tobytes(), digest_size=16).digest())

    def _invalidate_view(self):
        self._cancel_scan.set()
        for record in self._run_records.values():
            record["cancel_reason"]="页面内容变化（如滚动或切换页面）"
        self._revision += 1
        self.fade.stop()
        self._regions = []
        self._rendered_scene = None
        self._view_unstable = True
        self._last_view_change = time.monotonic()
        self._rescan_needed = self._auto
        self._update_native_mask()
        self.update()

    @Slot()
    def _watch_view(self):
        if self._closing or self._capturing or self._capture_pending or self._drag_origin is not None or self._dialog is not None or self._menu_open or QApplication.activePopupWidget() is not None or QToolTip.isVisible():
            return
        if not self.visible_capture_available():
            return  # Never hide the overlay on a monitoring tick.
        if not (self._regions or self._busy or self._auto or self._view_unstable):
            self.view_timer.stop()
            return
        try:
            image, _ = self.watch_capture()
            current_scene = Scene.capture(image)
            signature = current_scene.fingerprint
        except Exception:
            return
        if self._observed_scene is not None:
            meaningful_change = scene_changed(self._observed_scene,current_scene)
        else:
            meaningful_change = self._observed_frame is not None and signature != self._observed_frame
        if meaningful_change:
            self._invalidate_view()
        if meaningful_change or self._observed_scene is None:
            self._observed_scene = current_scene
            self._observed_frame = signature
        if self._view_unstable and time.monotonic()-self._last_view_change >= 0.4:
            self._view_unstable = False
            if self._auto:
                self._rescan_needed = True
                self._automatic_scan()

    def wheelEvent(self, event):
        # Reveal the page BEFORE forwarding, so it cannot remain covered by a
        # stale translation while a slow request is still in flight.
        self._invalidate_view()
        self._hint = False
        self._update_native_mask()
        self.repaint()
        horizontal = event.angleDelta().y() == 0
        delta = event.angleDelta().x() if horizontal else event.angleDelta().y()
        if forward_wheel(delta, horizontal, exclude_hwnd=int(self.winId())):
            event.accept()
        else:
            event.ignore()
        if self.visible_capture_available():
            self.view_timer.start()

    def _get_alpha(self):
        return self._alpha

    def _set_alpha(self, value):
        self._alpha = value
        self.update()

    overlayOpacity = Property(float, _get_alpha, _set_alpha)

    @Slot()
    def _hide_hint(self):
        if not self._hint:
            return
        self._hint = False
        self._update_native_mask()
        self.update()

    def content_rect(self):
        return self.rect().adjusted(MARGIN,DRAG_BAR_HEIGHT if self._shaped else MARGIN,-MARGIN,-MARGIN)

    def capture_rect(self):
        rect = self.content_rect()
        return QRect(self.mapToGlobal(rect.topLeft()), rect.size())

    def visible_capture_available(self):
        return self._excluded

    def scan_capture(self):
        return capture_region(self.capture_rect())

    def watch_capture(self):
        return capture_region(self.capture_rect())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Alpha 1 keeps right-click interaction in otherwise transparent pixels.
        # The user can explicitly opt into full input pass-through via the menu.
        painter.fillRect(self.rect(), QColor(255, 255, 255, 255 if self._shaped else 1))
        content = self.content_rect()
        painter.save()
        painter.setClipRect(content)
        painter.translate(content.topLeft())
        painter.setOpacity(self._alpha)
        for item in self._regions if event.region().intersects(content) else ():
            source = item.source
            # OCR engines often omit tiny punctuation at the glyph bounds.
            # A small safety margin masks those remnants without changing anchors.
            box = self._region_box(item)
            if box.width() <= 1 or box.height() <= 1:
                continue
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 255 if self._shaped else round(255*self.settings.mask_opacity/100)))
            painter.drawRoundedRect(box, 3, 3)
            painter.setPen(QColor("#202433"))
            text_box = box.adjusted(3, 1, -3, -1)
            font = QFont(QApplication.font())
            source_line_height = source.height / max(1, source.text.count("\n")+1) / self._image_scale
            if source_line_height >= 28:
                font.setWeight(QFont.Weight.DemiBold)
            flags = Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            maximum = min(self.settings.font_size, max(10, round(source_line_height*0.9)))
            # Native text layout fits each translation to its actual OCR bounds.
            for size in range(maximum, 5, -1):
                font.setPixelSize(size)
                metrics = QFontMetrics(font)
                measured = metrics.boundingRect(text_box.toRect(), int(flags), item.translation)
                if measured.height() <= text_box.height() and measured.width() <= text_box.width():
                    break
            painter.setFont(font)
            painter.save()
            painter.setClipRect(text_box)
            painter.drawText(text_box, int(flags), item.translation)
            painter.restore()
        painter.restore()
        border = QRectF(self.rect()).adjusted(4.5, 4.5, -4.5, -4.5)
        if self._paused:
            brush = QColor("#a2aabb")
        elif self._last_status.startswith("错误"):
            brush = QColor("#c47487")
        else:
            gradient = QConicalGradient(border.center(), self._phase if self._busy else 30)
            gradient.setColorAt(0, QColor("#6384f3"))
            gradient.setColorAt(0.25, QColor("#9274ed"))
            gradient.setColorAt(0.47, QColor("#6f87ee"))
            gradient.setColorAt(0.5, QColor("#b9eaff") if self._busy else QColor("#6c9cf4"))
            gradient.setColorAt(0.55, QColor("#5079ee"))
            gradient.setColorAt(1, QColor("#6384f3"))
            brush = gradient
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(brush, self.settings.border_width))
        painter.drawRoundedRect(border, 8, 8)
        if self._shaped:
            painter.setPen(QPen(QColor("#7d8ff2"), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            for x in (-5,0,5):
                for y in (12,17):
                    painter.drawPoint(self.width()//2+x,y)
        # Four understated corner handles make free resizing discoverable.
        painter.setPen(QPen(QColor("#d8e8ff"), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for x, y, dx, dy in [(5,5,1,1), (self.width()-5,5,-1,1), (5,self.height()-5,1,-1), (self.width()-5,self.height()-5,-1,-1)]:
            painter.drawLine(x, y, x+dx*10, y)
            painter.drawLine(x, y, x, y+dy*10)
        if self._hint and not self._regions:
            painter.setFont(QFont(QApplication.font().family(), 10))
            painter.setPen(QColor("#718098"))
            text = "拖动顶部整条区域移动 · 四角缩放 · 右键设置" if self._shaped else "拖动边角缩放 · 拖动内部移动 · 右键开始"
            if self.width() < 400:
                text = "右键开始 · 拖动边角缩放"
            painter.drawText(self.content_rect(), Qt.AlignmentFlag.AlignCenter, text)
        painter.end()

    @Slot()
    def _animate(self):
        self._phase = (self._phase+5) % 360
        self._update_border()

    def _update_border(self):
        self.update(QRegion(self.rect())-QRegion(self.content_rect()))

    def _set_busy(self, busy):
        self._busy = busy
        if busy and not self.settings.reduce_motion:
            self.animation_timer.start()
        else:
            self.animation_timer.stop()
        self._update_border()

    def _cursor_for_edge(self, edge):
        if edge in ("tl", "br"):
            return Qt.CursorShape.SizeFDiagCursor
        if edge in ("tr", "bl"):
            return Qt.CursorShape.SizeBDiagCursor
        if edge in ("l", "r"):
            return Qt.CursorShape.SizeHorCursor
        if edge in ("t", "b"):
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.SizeAllCursor

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.globalPosition().toPoint()
            self._drag_geometry = self.geometry()
            self._drag_edge = interaction_at(event.position().toPoint(),self.width(),self.height())
            self.fade.stop()
            self._regions = []
            self._cancel_scan.set()
            self._revision += 1
            self._update_native_mask()
            self.update()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_origin is not None:
            delta = event.globalPosition().toPoint()-self._drag_origin
            if self._drag_edge:
                self.setGeometry(resized_rect(self._drag_geometry, self._drag_edge, delta))
            else:
                self.move(self._drag_geometry.topLeft()+delta)
            event.accept()
        else:
            self.setCursor(self._cursor_for_edge(interaction_at(event.position().toPoint(),self.width(),self.height())))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._drag_origin is not None:
            self._drag_origin = None
            self._drag_edge = None
            self._revision += 1
            if self._auto:
                QTimer.singleShot(350, self._automatic_scan)
            event.accept()

    def resizeEvent(self, event):
        if hasattr(self, "_revision"):
            self._revision += 1
            self._regions = []
            self._cancel_scan.set()
            self._update_native_mask()
        super().resizeEvent(event)

    def moveEvent(self, event):
        if hasattr(self, "_revision"):
            self._revision += 1
            self._regions = []
            self._cancel_scan.set()
            self._observed_frame = None
            self._observed_scene = None
            self._update_native_mask()
        super().moveEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.clear_translation()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.scan(force=True)
        else:
            super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        self._populate_menu(menu)
        self._menu_open = True
        menu.exec(event.globalPos())
        self._menu_open = False
        menu.deleteLater()

    def _action(self, menu, text, callback, *, check=None, enabled=True):
        action = menu.addAction(text)
        if check is not None:
            action.setCheckable(True)
            action.setChecked(check)
        action.setEnabled(enabled)
        action.triggered.connect(callback)
        return action

    def _populate_menu(self, menu, tray=False):
        menu.clear()
        if tray:
            self._action(menu, "显示并恢复交互", self.restore_interaction)
        self._action(menu, "立即翻译", lambda: QTimer.singleShot(120, lambda: self.scan(force=True)), enabled=not self._busy)
        self._action(menu, "自动翻译", self.set_auto, check=self._auto)
        menu.addSeparator()
        models = menu.addMenu("选择模型")
        try:
            self._models = load_catalog(self._connection()) or self._models
        except (ValueError,RuntimeError):
            pass
        try:
            choices=load_enabled(self._connection(),self.settings.model)
        except (ValueError,RuntimeError):
            choices=[self.settings.model] if self.settings.model else []
        for model in choices:
            self._action(models, model, lambda checked=False, name=model: self.select_model(name), check=model == self.settings.model)
        models.addSeparator()
        self._action(models, "勾选 / 管理模型…", self.choose_model)
        self._action(models, "获取 / 配置模型…", lambda: self.preferences("api"))
        self._action(menu, "API 与供应商…", lambda: self.preferences("api"))
        self._action(menu, "OCR 与语言…", lambda: self.preferences("ocr"))
        menu.addSeparator()
        self._action(menu, "边框与动效…", lambda: self.preferences("appearance"))
        self._action(menu, "鼠标穿透（从托盘恢复）", self.set_pass_through, check=self._pass_through, enabled=self.tray is not None)
        self._action(menu, "暂停识别", self.set_paused, check=self._paused)
        self._action(menu, "清除译文 / 显示原文", self.clear_translation, enabled=bool(self._regions))
        self._action(menu, "复制全部译文", lambda: QApplication.clipboard().setText(self._last_translation), enabled=bool(self._last_translation))
        menu.addSeparator()
        status = self._last_status
        if len(status) > 34:
            status = status[:34]+"…"
        self._action(menu, status, lambda: None, enabled=False)
        self._action(menu, "本次识别与接口耗时…", self.show_timings, enabled=bool(self._metrics))
        self._action(menu, "操作说明", self.show_help)
        self._action(menu, "退出", self.close)

    def notify(self, message):
        if not self.test_mode:
            QToolTip.showText(QCursor.pos(), message, self, self.rect(), 6500)

    def show_help(self):
        self.notify("顶部整条抓握带 / 内侧边框 / 译文区域：移动\n四个 24px 角区 / 最外侧边缘：缩放\n右键边框 / 译文 / 托盘：设置\n滚动时显示原文，停稳后自动更新\nEnter：翻译；Esc：清除译文")

    def show_timings(self):
        from .timings import TimingsDialog
        if self._dialog is not None:
            self._dialog.raise_()
            return
        dialog=TimingsDialog(self._metrics_history or [self._metrics],self,counts=self._run_counts)
        self._dialog=dialog
        dialog.finished.connect(self._dialog_finished)
        dialog.show()

    def clear_translation(self):
        self._revision += 1
        self._cancel_scan.set()
        self.fade.stop()
        self._regions = []
        self._update_native_mask()
        self.update()

    @Slot(bool)
    def set_auto(self, enabled):
        self._auto = enabled
        if enabled:
            self._paused = False
            self.scan_timer.start()
            if self.visible_capture_available():
                self.view_timer.start()
            QTimer.singleShot(120, self._automatic_scan)
        else:
            self.scan_timer.stop()

    @Slot(bool)
    def set_paused(self, paused):
        self._paused = paused
        self._revision += 1
        self._cancel_scan.set()
        self._last_status = "已暂停" if paused else "就绪"
        self.update()

    @Slot(bool)
    def set_pass_through(self, enabled):
        if enabled and self.tray is None:
            self.notify("系统托盘不可用，无法开启全窗口鼠标穿透。")
            return
        self._pass_through = enabled
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, enabled)
        self.show()
        self._refresh_capture_exclusion()
        if enabled:
            self.tray.showMessage("FloatTranslate", "已开启鼠标穿透，右键托盘图标可恢复。", QSystemTrayIcon.MessageIcon.Information, 3000)

    def restore_interaction(self):
        self.set_pass_through(False)
        self.raise_()
        self.activateWindow()

    @Slot(object)
    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.restore_interaction()

    def preferences(self, page):
        if self._dialog is not None:
            self._dialog.raise_()
            self._dialog.activateWindow()
            return
        self._revision += 1
        self._dialog = Preferences(page, self.settings, self.secrets, self.preferences_pool, self.ocr, self)
        self._dialog.saved.connect(self._saved)
        self._dialog.finished.connect(self._dialog_finished)
        self._dialog.show()

    @Slot(int)
    def _dialog_finished(self, code):
        self._dialog = None
        # Window flag changes can recreate the native window while settings are
        # being applied. Restore only after the dialog's close event completes.
        QTimer.singleShot(0, self._restore_after_preferences)

    @Slot()
    def _restore_after_preferences(self):
        if self._closing:
            return
        if not self._capturing:
            self.setWindowOpacity(1)
        self.show()
        if not self._pass_through:
            self.raise_()
        self._refresh_capture_exclusion()
        self.update()

    @Slot(object)
    def _saved(self, payload):
        settings, models = payload
        self.apply_settings(settings)
        self._models = models

    def apply_settings(self, settings):
        old = self.settings
        if (old.provider,old.base_url,old.api_protocol,old.auth_mode)!=(settings.provider,settings.base_url,settings.api_protocol,settings.auth_mode):
            self._models=[]
        self.settings = settings
        self._cancel_scan.set()
        self._revision += 1
        self._failures = 0
        self._backoff_until = 0
        self._regions = []
        self._observed_frame = None
        self._observed_scene = None
        self._rendered_scene = None
        self.fade.stop()
        self.scan_timer.setInterval(settings.interval_ms)
        if old.always_on_top != settings.always_on_top:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, settings.always_on_top)
            self.show()
            self._refresh_capture_exclusion()
        self._set_busy(self._busy)
        self._update_native_mask()
        self.update()

    def choose_model(self):
        if self._dialog is not None:
            self._dialog.raise_()
            return
        try:
            connection=self._connection()
            self._models=load_catalog(connection) or self._models
            enabled=load_enabled(connection,self.settings.model)
        except (ValueError,RuntimeError):
            self.preferences('api')
            return
        picker=ModelPicker(self._models,self.settings.model,self,enabled=enabled)
        picker.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._dialog=picker
        def finished(code):
            if code==picker.DialogCode.Accepted:
                try:
                    save_enabled(connection,picker.enabled_ids(),picker.model_id())
                    self.select_model(picker.model_id())
                except OSError as error:
                    self.notify('模型勾选未能保存：'+str(error))
            self._dialog_finished(code)
        picker.finished.connect(finished)
        picker.show()

    def select_model(self, model):
        from dataclasses import replace
        settings = replace(self.settings, model=model)
        try:
            settings.save()
        except OSError as error:
            self.notify(str(error))
            return
        self.apply_settings(settings)

    def _connection(self):
        settings = self.settings
        preset = identify(settings.base_url) if settings.provider == "auto" else BY_ID.get(settings.provider, BY_ID["custom"])
        url = settings.base_url or preset.url
        key = self.secrets.get(SecretStore.identity(preset.id, url))
        connection = resolve(settings.provider, url, key, fast_mode=settings.fast_mode, protocol=settings.api_protocol,auth_mode=settings.auth_mode)
        if not settings.model:
            raise ValueError("请在右键菜单的 API 与供应商中选择模型")
        return connection

    @Slot()
    def _automatic_scan(self):
        import time
        if self._view_unstable:
            return
        if self._auto and time.monotonic() >= self._backoff_until:
            self.scan()

    def scan(self, force=False):
        if self._busy or self._capture_pending or self._drag_origin is not None or self._closing or self._menu_open or self._dialog is not None or QApplication.activePopupWidget() is not None or QToolTip.isVisible():
            return
        if self._paused and not force:
            return
        # A fallback capture hides the translated window before it can compare
        # scenes. Repeating that on a timer flashes even an unchanged page.
        # Preserve completed text until an explicit refresh or invalidation.
        if not force and self._regions and not self.visible_capture_available():
            return
        try:
            connection = self._connection()
            if not screen_permission(request=force):
                self.set_auto(False)
                raise ValueError("请在 macOS 系统设置 → 隐私与安全性 → 屏幕与系统音频录制中授权，然后重新启动软件。")
        except (ValueError, RuntimeError, ImportError) as error:
            revision=self._revision+1
            self._run_records[revision]={"run":revision,"model":self.settings.model,"target":self.settings.target,"started":time.monotonic()}
            self._record_metrics(revision,"连接配置失败",str(error))
            self._last_status = "错误："+str(error)
            self.update()
            if force:
                self.notify(str(error))
            else:
                self.set_auto(False)
            return
        self._hint = False
        self._update_native_mask()
        self._capture_pending = True
        self._revision += 1
        revision = self._revision
        settings = self.settings
        self._run_records[revision]={"run":revision,"model":settings.model,"target":settings.target,"started":time.monotonic(),"trigger":"manual" if force else "auto","capture_ms":0,"scene_ms":0,"queue_ms":0,"render_ms":0}
        # On macOS or old Windows, briefly remove the overlay before capture.
        # Windows capture exclusion avoids flicker when the OS supports it.
        if not self.visible_capture_available():
            self._capturing = True
            self.setWindowOpacity(0)
        QTimer.singleShot(0 if self.visible_capture_available() else 90,
                          lambda: self._capture_and_submit(revision, connection, settings,force))

    def _capture_and_submit(self, revision, connection, settings, force=False):
        try:
            if self._closing or revision != self._revision:
                self._record_metrics(revision,'已取消：画面或模式变化')
                return
            capture_started = time.monotonic()
            image, scale = self.scan_capture()
            self._capture_ms = round((time.monotonic()-capture_started)*1000)
            record=self._run_records.get(revision,{})
            record['capture_ms']=self._capture_ms
            record['capture_backend']=getattr(self,'_capture_backend','桌面截图')
            scene_started=time.monotonic()
            current_scene = Scene.capture(image)
            record['scene_ms']=round((time.monotonic()-scene_started)*1000)
            context = (connection,settings.model,settings.target,settings.ocr_language,
                       tuple(self.capture_rect().getRect()),scale)
            if not force and self._regions and context == self._rendered_context and not scene_changed(self._rendered_scene,current_scene):
                self._run_records.pop(revision,None)
                return
            self._observed_frame = current_scene.fingerprint
            self._observed_scene = current_scene
            self._pending_scene = current_scene
            self._pending_context = context
        except Exception as error:
            self._record_metrics(revision,"截图失败",str(error))
            self._last_status = "错误："+str(error)
            self.notify(str(error))
            self.update()
            return
        finally:
            self._capture_pending = False
            if self._capturing:
                self.setWindowOpacity(1)
                self._capturing = False
        self._set_busy(True)
        self._rescan_needed = False
        self._cancel_scan = threading.Event()
        cancel_event = self._cancel_scan
        if self.visible_capture_available():
            self.view_timer.start()
        self._last_status = "正在识别并翻译…"
        queued=time.monotonic()
        def work():
            record=self._run_records.get(revision)
            if record is not None:
                record['queue_ms']=round((time.monotonic()-queued)*1000)
                record['_worker']=True
            return self.pipeline.overlay(connection,settings.model,settings.target,image,settings.ocr_language,
                on_progress=lambda regions:task.signals.progress.emit(((revision,scale),regions)),cancelled=cancel_event.is_set)
        task=Task((revision,scale),work)
        self._jobs[revision] = task
        task.signals.finished.connect(self._completed)
        task.signals.progress.connect(self._progress)
        self.worker_pool.start(task)

    @Slot(object)
    def _progress(self, payload):
        (revision, scale), regions = payload
        if revision != self._revision or self._closing or self._paused:
            return
        if self._regions == regions and self._image_scale == scale:
            return
        self._regions = regions
        self._image_scale = scale
        self._alpha = 1
        paint_started=time.monotonic()
        self._update_native_mask()
        self.repaint()
        record=self._run_records.get(revision)
        if record is not None:
            record["render_ms"]=record.get("render_ms",0)+round((time.monotonic()-paint_started)*1000)

    @Slot(object)
    def _completed(self, payload):
        import time
        identity, regions, error = payload
        revision, scale = identity
        self._jobs.pop(revision, None)
        self._set_busy(False)
        stale=self._closing or revision != self._revision
        self._record_metrics(revision,'已取消：画面或模式变化' if stale else '部分完成' if error and self._regions else '失败' if error else '完成',error or '')
        if stale:
            if self._rescan_needed and not self._view_unstable and not self._closing:
                QTimer.singleShot(0, self._automatic_scan)
            return
        if error:
            # Valid completed stream paragraphs belong to this same revision.
            # Keep them when a later batch / response fails; stale revisions
            # have already returned above and are never restored.
            self._last_source="\n\n".join(item.source.text for item in self._regions)
            self._last_translation="\n\n".join(item.translation for item in self._regions)
            self._update_native_mask()
            self._last_status = "错误："+error
            self._failures += 1
            self._backoff_until = time.monotonic()+min(60, 2**min(self._failures, 6))
            self.notify(error)
            self.update()
            return
        self._failures = 0
        self._backoff_until = 0
        self._rendered_scene = self._pending_scene
        self._rendered_context = self._pending_context
        changed = regions != self._regions or scale != self._image_scale
        self._regions = regions
        self._image_scale = scale
        self._last_source = "\n\n".join(item.source.text for item in regions)
        self._last_translation = "\n\n".join(item.translation for item in regions)
        self._last_status = f"已覆盖 {len(regions)} 个段落" if regions else "未识别到文字"
        if changed:
            self._update_native_mask()
        if changed and regions and not self.settings.reduce_motion and not self._shaped:
            self.fade.stop()
            self.fade.setStartValue(0.0)
            self.fade.setEndValue(1.0)
            self.fade.start()
        else:
            self._alpha = 1
        if changed:
            self.update()
        paint_started=time.monotonic()
        self.repaint()
        if self._metrics.get('_revision')==revision:
            self._metrics['render_ms']=self._metrics.get('render_ms',0)+round((time.monotonic()-paint_started)*1000)
            self._metrics['end_to_end_ms']=round((time.monotonic()-self._metrics.pop('_started',time.monotonic()))*1000)

    def _record_metrics(self,revision,status,error=''):
        record=self._run_records.pop(revision,None)
        if record is None:
            return
        started=record.pop('started')
        metrics=dict(getattr(self.pipeline,'metrics',{})) if record.get('_worker') else {}
        self._attempt_counter+=1
        metrics.update(record)
        metrics['run']=self._attempt_counter
        metrics['_revision']=revision
        self._run_counts['total']+=1
        self._run_counts['auto' if record.get('trigger')=='auto' else 'manual']+=1
        if status.startswith('已取消'):
            status='已取消'
            error=record.get('cancel_reason') or '识别范围、页面或设置已改变，旧结果未覆盖。'
        metrics.update(status=status,error=error,end_to_end_ms=round((time.monotonic()-started)*1000),_started=started)
        self._metrics=metrics
        self._metrics_history.append(metrics)
        self._metrics_history=self._metrics_history[-20:]

    def closeEvent(self, event):
        self._closing = True
        self.scan_timer.stop()
        self.view_timer.stop()
        self._cancel_scan.set()
        self.animation_timer.stop()
        self.fade.stop()
        if self._dialog is not None:
            self._dialog.close()
        if self.worker_pool.activeThreadCount() or self.preferences_pool.activeThreadCount() or self._capture_pending:
            event.ignore()
            self.hide()
            QTimer.singleShot(150, self.close)
            return
        self.pipeline.close()
        if self.tray:
            self.tray.hide()
        try:
            self._save_geometry()
        except OSError:
            pass
        event.accept()
        if not self.test_mode:
            QApplication.quit()
