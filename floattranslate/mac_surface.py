"""Public AppKit bridges for persistent desktop tools and glass materials.

Qt owns its NSView throughout: the glass is a sibling underneath it, never a
replacement content view. No desktop capture, privacy permission, or polling
is needed to keep a tool visible while another application has focus.
"""
from __future__ import annotations

import logging
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

log = logging.getLogger(__name__)


def keep_tool_visible(widget):
    if sys.platform == "darwin":
        # Qt.Tool normally disappears when the application becomes inactive.
        # Set this BEFORE creating the platform window as well as after resets.
        widget.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)


def native_view(widget):
    if sys.platform != "darwin" or QGuiApplication.platformName() != "cocoa":
        return None
    import objc
    return objc.objc_object(c_void_p=int(widget.winId()))


def configure_tool(widget, always_on_top):
    """Reapply after showing or changing flags, which may recreate NSPanel."""
    keep_tool_visible(widget)
    view = native_view(widget)
    if view is None or view.window() is None:
        return False
    import AppKit
    window = view.window()
    window.setHidesOnDeactivate_(False)
    window.setHasShadow_(False)
    behavior = int(window.collectionBehavior())
    # Join all Spaces rather than migrating to one active Space. Clear the
    # mutually exclusive Stage Manager classifications before joining apps.
    behavior &= ~int(AppKit.NSWindowCollectionBehaviorMoveToActiveSpace)
    for name in ("NSWindowCollectionBehaviorPrimary", "NSWindowCollectionBehaviorAuxiliary"):
        behavior &= ~int(getattr(AppKit, name, 0))
    behavior |= (AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
                 | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
                 | getattr(AppKit, "NSWindowCollectionBehaviorCanJoinAllApplications", 0))
    window.setCollectionBehavior_(behavior)
    # Qt may use its higher tool-panel level for WindowStaysOnTopHint.
    # Preserve that valid floating level instead of fighting later Qt updates.
    level = max(int(window.level()), AppKit.NSFloatingWindowLevel) if always_on_top else AppKit.NSNormalWindowLevel
    window.setLevel_(level)
    return True


def release_glass(widget):
    previous = getattr(widget, "_mac_glass", None)
    if previous is not None:
        previous[1].removeFromSuperview()
        widget._mac_glass = None


def update_glass(widget, rect, radius=20):
    """Install native glass underneath the transparent Qt drawing surface.

    macOS 26+ uses NSGlassEffectView; macOS 14/15 uses NSVisualEffectView.
    Offscreen rendering and reduced-transparency displays use the Qt fallback.
    """
    view = native_view(widget)
    if view is None or view.superview() is None:
        return False
    import AppKit
    import objc
    if AppKit.NSWorkspace.sharedWorkspace().accessibilityDisplayShouldReduceTransparency():
        release_glass(widget)
        return False
    previous = getattr(widget, "_mac_glass", None)
    parent = view.superview()
    if previous is not None and (previous[0] != int(widget.winId()) or previous[1].superview() != parent):
        release_glass(widget)
        previous = None
    if previous is None:
        try:
            glass_type = objc.lookUpClass("NSGlassEffectView")
        except objc.nosuchclass_error:
            glass_type = None
        if glass_type is not None:
            effect = glass_type.alloc().initWithFrame_(view.frame())
            effect.setStyle_(getattr(AppKit, "NSGlassEffectViewStyleRegular", 0))
            effect.setCornerRadius_(radius)
        else:
            effect = AppKit.NSVisualEffectView.alloc().initWithFrame_(view.frame())
            effect.setMaterial_(AppKit.NSVisualEffectMaterialHUDWindow)
            effect.setBlendingMode_(AppKit.NSVisualEffectBlendingModeBehindWindow)
            effect.setState_(AppKit.NSVisualEffectStateActive)
            effect.setWantsLayer_(True)
            effect.layer().setCornerRadius_(radius)
            effect.layer().setMasksToBounds_(True)
        parent.addSubview_positioned_relativeTo_(effect, AppKit.NSWindowBelow, view)
        widget._mac_glass = (int(widget.winId()), effect)
    else:
        effect = previous[1]
    y = rect.y() if view.isFlipped() else widget.height()-rect.y()-rect.height()
    frame = view.convertRect_toView_(((rect.x(), y), (rect.width(), rect.height())), parent)
    effect.setFrame_(frame)
    return True


def refresh_surface(widget, *, glass_rect=None):
    """Keep optional native styling from preventing the core tools starting."""
    try:
        owner = getattr(widget, "owner", widget)
        configure_tool(widget, owner.settings.always_on_top)
        return glass_rect is not None and update_glass(widget, glass_rect)
    except Exception:
        # Log native integration failures for diagnostics, keep a readable Qt
        # fallback, and avoid repeatedly logging the same window's failure.
        if not getattr(widget, "_mac_surface_failed", False):
            log.exception("Could not apply the macOS desktop surface")
            widget._mac_surface_failed = True
        return False
