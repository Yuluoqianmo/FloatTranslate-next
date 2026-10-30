"""Display Qt actions in an AppKit context menu on macOS.

QMenu.exec() paints a Qt popup even on Cocoa. Keep the existing QAction model
(including submenus and checks), but let NSMenu own layout, material and focus.
No private Qt pointers or replacement event handlers are needed.
"""
from __future__ import annotations

import logging
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QKeySequence

log = logging.getLogger(__name__)
_target_type = None


def native_menu_available():
    return sys.platform == 'darwin' and QGuiApplication.platformName() == 'cocoa'


def _selection_target():
    global _target_type
    if _target_type is None:
        import AppKit

        class FloatTranslateMenuTarget(AppKit.NSObject):
            def selectAction_(self, sender):
                # Dispatch only after AppKit has dismissed the menu. Settings
                # can then safely hide the scope that originally opened it.
                self.selected = int(sender.tag())

        _target_type = FloatTranslateMenuTarget
    target = _target_type.alloc().init()
    target.selected = None
    return target


def _shortcut(text):
    from .hotkey import mac_modifier_flags
    sequence = QKeySequence(text)
    if sequence.isEmpty():
        return '', 0
    key = sequence[0].key()
    if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
        character = '\r'
    elif Qt.Key.Key_F1 <= key <= Qt.Key.Key_F12:
        character = chr(0xf704 + int(key) - int(Qt.Key.Key_F1))
    else:
        character = QKeySequence(int(key)).toString().lower()
    return character, mac_modifier_flags(sequence[0].keyboardModifiers())


def build_native_menu(menu):
    """Return NSMenu, its retained target, and selected-tag -> QAction map."""
    import AppKit
    target = _selection_target()
    actions = {}

    def build(source):
        native = AppKit.NSMenu.alloc().initWithTitle_(source.title())
        native.setAutoenablesItems_(False)
        for action in source.actions():
            if not action.isVisible():
                continue
            if action.isSeparator():
                native.addItem_(AppKit.NSMenuItem.separatorItem())
                continue
            item = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(action.text(), None, '')
            item.setEnabled_(action.isEnabled())
            if action.menu() is not None:
                item.setSubmenu_(build(action.menu()))
            else:
                tag = len(actions)
                actions[tag] = action
                item.setTag_(tag)
                item.setTarget_(target)
                item.setAction_('selectAction:')
                if action.isCheckable():
                    item.setState_(AppKit.NSControlStateValueOn if action.isChecked() else AppKit.NSControlStateValueOff)
                shortcut = action.property('menuShortcut')
                if shortcut:
                    character, modifiers = _shortcut(shortcut)
                    item.setKeyEquivalent_(character)
                    item.setKeyEquivalentModifierMask_(modifiers)
            native.addItem_(item)
        return native

    return build(menu), target, actions


def exec_native_menu(menu, position):
    """Return False for non-Cocoa or failed native setup so Qt can fall back."""
    if not native_menu_available():
        return False
    try:
        import AppKit
        native, target, actions = build_native_menu(menu)
        # Qt's global origin is the top-left of the primary display; AppKit's
        # is its bottom-left. This also handles displays with negative origins.
        from PySide6.QtWidgets import QApplication
        from .mac_surface import native_view
        widget = QApplication.topLevelAt(position)
        event = AppKit.NSApplication.sharedApplication().currentEvent()
        view = native_view(widget) if widget is not None else None
        if event is not None and view is not None:
            AppKit.NSMenu.popUpContextMenu_withEvent_forView_(native, event, view)
        else:
            top = AppKit.NSScreen.screens()[0].frame().size.height
            native.popUpMenuPositioningItem_atLocation_inView_(None, (position.x(), top-position.y()), None)
    except Exception:
        log.exception('Could not show the macOS context menu')
        return False
    action = actions.get(target.selected)
    if action is not None:
        action.trigger()
    return True
