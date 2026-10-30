"""macOS refraction ribbon: native glass backing, Qt controls and contour."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QConicalGradient, QFont, QLinearGradient, QPainterPath, QPen
from PySide6.QtWidgets import QApplication

RIBBON_HEIGHT = 184


def is_dark():
    return QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark


def ribbon_action(point):
    if QRect(5, 6, 38, 39).contains(point):
        return "toggle"
    if QRect(5, 47, 38, 34).contains(point):
        return "translate"
    if QRect(5, 126, 38, 34).contains(point):
        return "original"
    return "move"


def ribbon_status(owner):
    if owner._paused:
        return "已暂停", QColor("#8795aa")
    if owner._busy or owner._capture_pending:
        return "翻译中", QColor("#388dff")
    if owner._last_status.startswith("错误"):
        return "需处理", QColor("#d26e7d")
    if owner._regions:
        return "已完成", QColor("#299b79")
    return ("就绪" if owner.working else "待机"), QColor("#7a91af")


def paint_ribbon(p, widget):
    owner = widget.owner
    dark = is_dark()
    ink = QColor("#e4efff" if dark else "#294464")
    body = QRectF(4, 2, 40, RIBBON_HEIGHT-4)
    p.setBrush(Qt.BrushStyle.NoBrush)
    if not widget._native_glass:
        material = QLinearGradient(body.topLeft(), body.bottomRight())
        material.setColorAt(0, QColor("#d7e8ff" if not dark else "#455f81"))
        material.setColorAt(.22, QColor("#f5f9ff" if not dark else "#263c59"))
        material.setColorAt(1, QColor("#d8e7f7" if not dark else "#344e6e"))
        p.setBrush(material)
    p.setPen(QPen(QColor(255, 255, 255, 135 if not dark else 65), 1))
    p.drawRoundedRect(body, 20, 20)
    # Crisp optical edge rather than several expanding external rings.
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(96, 137, 190, 45), .8))
    p.drawRoundedRect(body.adjusted(1, 1, -1, -1), 19, 19)
    action = ribbon_action(widget.mapFromGlobal(widget.cursor().pos())) if widget._hover else ""
    if action in ("toggle", "translate", "original"):
        top = {"toggle": 8, "translate": 48, "original": 126}[action]
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(71, 143, 255, 28))
        p.drawRoundedRect(QRectF(9, top, 30, 32), 13, 13)
    font = QFont(QApplication.font())
    font.setPixelSize(20)
    font.setWeight(QFont.Weight.Medium)
    p.setFont(font)
    p.setPen(ink)
    p.drawText(QRect(4, 9, 40, 31), Qt.AlignmentFlag.AlignCenter, "译")
    p.setPen(QPen(QColor(96, 137, 190, 40), .8))
    p.drawLine(QPointF(15, 43), QPointF(33, 43))
    # Refresh, plus a short arrowhead (drawn locally, no font/icon dependency).
    p.setPen(QPen(ink, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(17, 57, 14, 14), 45*16, 285*16)
    arrow = QPainterPath(QPointF(30, 54))
    arrow.lineTo(30, 60)
    arrow.lineTo(24, 60)
    p.drawPath(arrow)
    label, color = ribbon_status(owner)
    p.setPen(color)
    font.setPixelSize(10)
    p.setFont(font)
    p.drawText(QRect(4, 85, 40, 18), Qt.AlignmentFlag.AlignCenter, label)
    active = owner._busy and not owner.settings.reduce_motion
    p.setPen(QPen(color, 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for index, x in enumerate((17, 24, 31)):
        height = 3+8*(.5+.5*math.sin(math.radians(owner._phase*2+index*65))) if active else 4
        p.drawLine(QPointF(x, 113-height/2), QPointF(x, 113+height/2))
    # Eye restores the original page without issuing another capture.
    p.setPen(QPen(ink if owner._regions else QColor(ink.red(), ink.green(), ink.blue(), 100), 1.4,
                  Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    eye = QPainterPath(QPointF(15, 143))
    eye.cubicTo(20, 135, 28, 135, 33, 143)
    eye.cubicTo(28, 151, 20, 151, 15, 143)
    p.drawPath(eye)
    p.drawEllipse(QPointF(24, 143), 2.4, 2.4)
    p.setPen(QPen(QColor(ink.red(), ink.green(), ink.blue(), 90), 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for x in (20, 24, 28):
        p.drawPoint(QPointF(x, 169))


def paint_contour(p, rect, *, phase, busy, paused, error, reduce_motion, border_width):
    """Stable geometry with a moving, refracted highlight; no content fade."""
    rect = QRectF(rect)
    p.setBrush(Qt.BrushStyle.NoBrush)
    if busy and not paused:
        gradient = QConicalGradient(rect.center(), 35 if reduce_motion else phase)
        for at, color in ((0, "#7399c8"), (.12, "#729fe3"), (.23, "#418cff"),
                          (.27, "#a4efff"), (.29, "#f0fcff"), (.32, "#6cbcff"),
                          (.4, "#759fd7"), (.68, "#7399c8"), (.82, "#a4b6ff"), (1, "#7399c8")):
            gradient.setColorAt(at, QColor(color))
        # A single compact outer highlight with a fixed radius.
        p.save()
        clip = QPainterPath()
        clip.addRect(QRectF(p.viewport()))
        inside = QPainterPath()
        inside.addRoundedRect(rect.adjusted(1, 1, -1, -1), 13, 13)
        p.setClipPath(clip.subtracted(inside))
        p.setPen(QPen(QColor(69, 145, 255, 42), 5))
        p.drawRoundedRect(rect, 14, 14)
        p.restore()
        p.setPen(QPen(QColor(255, 255, 255, 130), .8))
        p.drawRoundedRect(rect.adjusted(-1.3, -1.3, 1.3, 1.3), 15, 15)
        p.setPen(QPen(gradient, max(1.8, min(3, border_width))))
    else:
        color = "#9aa5b6" if paused else "#c67d89" if error else "#91acca"
        p.setPen(QPen(QColor(color), max(1, min(1.5, border_width*.65))))
    p.drawRoundedRect(rect, 14, 14)
