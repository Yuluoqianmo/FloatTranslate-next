"""Shared native dialog styling; the recognition frame paints its own surface."""

STYLESHEET = """
QDialog { background: #ffffff; color: #202535; }
QWidget { font-family: 'Segoe UI', 'PingFang SC', 'Microsoft YaHei UI'; font-size: 13px; }
QLabel { color: #202535; background: transparent; }
QLabel[role='title'] { font-size: 23px; font-weight: 600; }
QLabel[role='muted'] { color: #7b8293; font-size: 12px; }
QLabel[role='error'] { color: #b54b57; font-size: 12px; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    min-height: 32px; padding: 4px 10px; border: 1px solid #dfe3ec;
    border-radius: 7px; background: #ffffff; color: #202535;
    selection-background-color: #e5eaff; selection-color: #244acb;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 1px solid #5674f0; }
QComboBox::drop-down { border: 0; width: 24px; }
QComboBox QAbstractItemView { background: #ffffff; color: #202535; selection-background-color: #e9edff; selection-color: #3556d7; }
QPushButton { padding: 9px 18px; border: 1px solid #dfe3ec; border-radius: 7px; background: #f8f9fc; color: #293145; }
QPushButton:hover { background: #eef1fa; border-color: #c4cee8; }
QPushButton:pressed { background: #e3e8f5; }
QPushButton[primary='true'] { background: #4567ed; color: #ffffff; border-color: #4567ed; }
QPushButton[primary='true']:hover { background: #3657d8; }
QPushButton:disabled { background: #eef0f5; color: #979eaf; border-color: #e7eaf0; }
QCheckBox { spacing: 8px; color: #344057; padding: 4px 0; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #c9d0df; border-radius: 4px; background: #ffffff; }
QCheckBox::indicator:checked { background: #4567ed; border: 1px solid #4567ed; }
QMenu { padding: 7px; border: 1px solid #dbe0ec; border-radius: 9px; background: #fcfdff; color: #252d40; }
QMenu::item { padding: 8px 30px 8px 24px; border-radius: 5px; }
QMenu::item:selected { background: #e9edff; color: #385bda; }
QMenu::item:disabled { color: #9198aa; }
QMenu::separator { height: 1px; background: #e6e9f0; margin: 5px 8px; }
QListWidget {border:1px solid #dfe3ec; border-radius:7px; background:white; color:#202535;}
QListWidget::item {padding:7px 10px;}
QListWidget::item:selected {background:#e9edff; color:#3556d7;}
QToolTip { background: #242d40; color: white; border: none; padding: 8px; }
"""

# Only semantic text roles are styled on macOS; AppKit / Qt's macOS style
# owns control geometry, menu appearance and the light/dark palette.
MAC_STYLESHEET = """
QLabel[role='title'] { font-size: 23px; font-weight: 600; }
QLabel[role='muted'] { color: palette(placeholder-text); }
QLabel[role='error'] { color: #c84a50; }
"""
