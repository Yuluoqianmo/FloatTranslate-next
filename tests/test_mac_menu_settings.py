"""Regressions for native menus and settings that obstruct the desktop scope."""
from dataclasses import replace
import sys

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu

from floattranslate.bookmark import BookmarkFrame
from floattranslate.hotkey import ToggleHotkey
from floattranslate.settings import SecretStore, Settings


class MemorySecrets(SecretStore):
    def get(self, identity):
        return self._session.get(identity, '')

    def set(self, identity, key):
        self._session[identity] = key
        return True


@pytest.fixture
def desktop(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    monkeypatch.setenv('FLOATTRANSLATE_CONFIG_DIR', str(tmp_path))
    monkeypatch.setattr(ToggleHotkey, 'install', lambda *args: None)
    frame = BookmarkFrame(settings=Settings(), test_mode=True)
    frame.secrets = MemorySecrets()
    frame._auto = False
    yield app, frame
    frame.close()
    app.processEvents()


@pytest.mark.skipif(sys.platform != 'darwin', reason='macOS settings behavior')
@pytest.mark.parametrize('page', ['api', 'picker', 'shortcuts'])
def test_settings_collapse_scope_and_do_not_reopen_on_close(desktop, monkeypatch, page):
    app, frame = desktop
    frame.set_working(True, scan=False)  # Opening while the scope is animating.
    assert frame.working and frame._transitioning
    if page == 'picker':
        monkeypatch.setattr(frame, '_connection', lambda: object())
        monkeypatch.setattr('floattranslate.frame.load_catalog', lambda _: ['example-model'])
        monkeypatch.setattr('floattranslate.frame.load_enabled', lambda *_: ['example-model'])
        frame.choose_model()
    elif page == 'shortcuts':
        frame.shortcut_preferences()
    else:
        frame.preferences(page)
    app.processEvents()
    dialog = frame._dialog
    assert dialog.isVisible() and not frame.working
    assert not frame.isVisible() and not frame.transition.isVisible()
    assert not frame.scan_timer.isActive() and not frame.view_timer.isActive()
    assert frame.bookmark.isVisible()
    dialog.reject()
    app.processEvents()
    assert frame._dialog is None and not frame.working and not frame.isVisible()
    assert frame.bookmark.isVisible()
    # The ribbon remains usable after dismissing the form.
    QTest.mouseClick(frame.bookmark, Qt.MouseButton.LeftButton, pos=QPoint(24, 24))
    assert frame.working


@pytest.mark.skipif(sys.platform != 'darwin', reason='macOS settings behavior')
def test_saving_window_level_while_settings_open_preserves_standby(desktop):
    app, frame = desktop
    frame.set_working(True, animate=False, scan=False)
    frame.preferences('appearance')
    dialog = frame._dialog
    dialog.on_top.setChecked(not frame.settings.always_on_top)
    dialog._save()
    app.processEvents()
    assert frame._dialog is None and not frame.isVisible() and not frame.working
    assert not frame.settings.always_on_top and frame.bookmark.isVisible()


def test_scope_can_be_collapsed_while_settings_remain_open(desktop):
    app, frame = desktop
    frame.preferences('api')
    dialog = frame._dialog
    frame.set_working(True, animate=False, scan=False)
    frame.settings = replace(frame.settings, reduce_motion=True)
    QTest.mouseClick(frame.bookmark, Qt.MouseButton.LeftButton, pos=QPoint(24, 24))
    assert not frame.working and not frame.isVisible()
    assert frame._dialog is dialog and dialog.isVisible()
    dialog.close()
    app.processEvents()
    assert not frame.working and not frame.isVisible()


@pytest.mark.skipif(sys.platform != 'darwin', reason='AppKit menu')
def test_native_menu_preserves_actions_checks_submenus_and_shortcuts(desktop):
    import AppKit
    from floattranslate.mac_menu import build_native_menu
    app, frame = desktop
    menu = QMenu(frame)
    frame._populate_menu(menu)
    original_auto = frame._auto
    native, target, actions = build_native_menu(menu)
    assert isinstance(native, AppKit.NSMenu)
    assert not native.autoenablesItems()
    assert native.itemAtIndex_(0).title() == '展开翻译区域'
    assert native.itemAtIndex_(0).keyEquivalent() == 't'
    assert native.itemAtIndex_(0).keyEquivalentModifierMask() == AppKit.NSEventModifierFlagOption
    assert native.itemAtIndex_(1).keyEquivalent() == '\r'
    assert native.itemAtIndex_(1).keyEquivalentModifierMask() == (
        AppKit.NSEventModifierFlagOption | AppKit.NSEventModifierFlagCommand)
    assert native.itemAtIndex_(2).state() == AppKit.NSControlStateValueOff
    assert native.itemAtIndex_(3).submenu().numberOfItems() >= 1
    assert not native.itemAtIndex_(5).isEnabled()  # No translation to reveal.
    assert native.itemAtIndex_(8).isSeparatorItem()
    if app.platformName() == "cocoa":
        native.performActionForItemAtIndex_(2)
    else:
        target.selectAction_(native.itemAtIndex_(2))
    # The target records selection; Qt dispatch waits until the popup closes.
    assert frame._auto == original_auto
    actions[target.selected].trigger()
    assert frame._auto != original_auto
    frame._auto = False
    frame.scan_timer.stop()
