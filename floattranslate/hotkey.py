"""Desktop toggle shortcut. Windows uses RegisterHotKey; macOS uses NSEvent."""
from __future__ import annotations

import sys
from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtGui import QKeySequence, QShortcut


def shortcut_parts(text,*,allow_enter=False):
    sequence = QKeySequence(text)
    if sequence.count() != 1:
        raise ValueError("请设置一个组合键，例如 Alt+T")
    combination = sequence[0]
    key = combination.key()
    mods = combination.keyboardModifiers()
    if not mods & (Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier):
        raise ValueError("快捷键须包含 Alt、Ctrl 或 Meta")
    if not (Qt.Key.Key_A <= key <= Qt.Key.Key_Z or Qt.Key.Key_0 <= key <= Qt.Key.Key_9 or Qt.Key.Key_F1 <= key <= Qt.Key.Key_F12 or allow_enter and key in (Qt.Key.Key_Return,Qt.Key.Key_Enter)):
        raise ValueError("请使用字母、数字或 F1–F12")
    return key, mods


class ToggleHotkey(QObject):
    activated = Signal()
    ID = 0x4654

    def __init__(self, window,*,hotkey_id=None,allow_enter=False):
        super().__init__(window)
        self.window = window
        self.ID=hotkey_id or self.ID
        self.allow_enter=allow_enter
        self.registered = False
        self.text = ""
        self.monitors = []
        self.local = None

    def install(self, text):
        key, mods = shortcut_parts(text,allow_enter=self.allow_enter)
        previous = self.text
        self.close()
        if sys.platform == "win32":
            import ctypes
            flags = 0x4000  # MOD_NOREPEAT
            for qt, native in ((Qt.KeyboardModifier.AltModifier,1), (Qt.KeyboardModifier.ControlModifier,2),
                               (Qt.KeyboardModifier.ShiftModifier,4), (Qt.KeyboardModifier.MetaModifier,8)):
                if mods & qt:
                    flags |= native
            vk = 0x0D if key in (Qt.Key.Key_Return,Qt.Key.Key_Enter) else int(key) if key <= Qt.Key.Key_Z else 0x70+int(key)-int(Qt.Key.Key_F1)
            if not ctypes.windll.user32.RegisterHotKey(int(self.window.winId()), self.ID, flags, vk):
                if previous and previous != text:
                    self.install(previous)
                raise ValueError("该快捷键已被其他软件占用，请换一个组合键")
            self.registered = True
        elif sys.platform == "darwin":
            from AppKit import NSEvent, NSEventMaskKeyDown
            expected = mac_modifier_flags(mods)
            # NSEvent global monitoring needs Accessibility permission for keys.
            # Local monitoring still works when the user has not granted it.
            label = QKeySequence(int(key)).toString().lower()
            function_codes = {122:1,120:2,99:3,118:4,96:5,97:6,98:7,100:8,101:9,109:10,103:11,111:12}
            def matches(event):
                character = str(event.charactersIgnoringModifiers() or "").lower()
                if key in (Qt.Key.Key_Return,Qt.Key.Key_Enter):
                    character='return' if event.keyCode() in (36,76) else ''
                    expected_label='return'
                else:
                    expected_label=label
                if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F12:
                    character = 'f'+str(function_codes.get(event.keyCode(), 0))
                return not event.isARepeat() and event.modifierFlags() & 0x1e0000 == expected and character == expected_label
            def globally(event):
                if matches(event):
                    self.activated.emit()
            def locally(event):
                if matches(event):
                    self.activated.emit()
                    return None
                return event
            self._handlers = (globally, locally)
            self.monitors = [NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(NSEventMaskKeyDown, globally),
                             NSEvent.addLocalMonitorForEventsMatchingMask_handler_(NSEventMaskKeyDown, locally)]
        else:
            self.local = QShortcut(QKeySequence(text), self.window)
            self.local.setContext(Qt.ShortcutContext.ApplicationShortcut)
            self.local.activated.connect(self.activated)
        self.text = text

    def close(self):
        if self.registered:
            import ctypes
            ctypes.windll.user32.UnregisterHotKey(int(self.window.winId()), self.ID)
            self.registered = False
        if self.monitors:
            from AppKit import NSEvent
            for monitor in self.monitors:
                if monitor:
                    NSEvent.removeMonitor_(monitor)
            self.monitors = []
        if self.local:
            self.local.setEnabled(False)
            self.local.deleteLater()
            self.local = None


def mac_modifier_flags(mods):
    # Qt Control means Command on macOS; Qt Meta means the physical Control key.
    flags = 0
    for qt, native in ((Qt.KeyboardModifier.ShiftModifier, 1 << 17),
                       (Qt.KeyboardModifier.MetaModifier, 1 << 18),
                       (Qt.KeyboardModifier.AltModifier, 1 << 19),
                       (Qt.KeyboardModifier.ControlModifier, 1 << 20)):
        if mods & qt:
            flags |= native
    return flags
