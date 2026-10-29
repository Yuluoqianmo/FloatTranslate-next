from __future__ import annotations

import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from .frame import app_icon
from .bookmark import BookmarkFrame
from .style import STYLESHEET


def configure_application(application):
    # The sole main surface is a Qt.Tool overlay, which Qt excludes from its
    # "last primary window" count. Closing a settings dialog must not quit the
    # app while that overlay (or its tray icon) is still in use. The frame's
    # explicit Exit action / closeEvent owns application shutdown instead.
    application.setQuitOnLastWindowClosed(False)
    application.setApplicationName("FloatTranslate Next")
    application.setOrganizationName("FloatTranslate")
    application.setWindowIcon(app_icon())
    application.setFont(QFont("PingFang SC" if sys.platform == "darwin" else "Microsoft YaHei UI", 10))
    application.setStyle("Fusion")
    application.setStyleSheet(STYLESHEET)


def main():
    application = QApplication(sys.argv)
    configure_application(application)
    if len(sys.argv) == 3 and sys.argv[1] == "--mac-self-test":
        from .mac_diagnostics import run
        return run(application, sys.argv[2])
    if len(sys.argv) == 3 and sys.argv[1] == "--about-self-test":
        from .about_diagnostics import run
        return run(application, sys.argv[2])
    if len(sys.argv) == 3 and sys.argv[1] == "--update-health-check":
        import json
        from pathlib import Path
        from . import __version__
        from .updates import PRODUCT, platform_key
        Path(sys.argv[2]).write_text(json.dumps({"product": PRODUCT, "version": __version__,
                                              "platform": platform_key(), "passed": True}), "utf-8")
        return 0
    if len(sys.argv) == 3 and sys.argv[1] == "--resize-self-test":
        from .resize_diagnostics import run
        return run(application, sys.argv[2])
    if len(sys.argv) == 3 and sys.argv[1] == "--keyboard-self-test":
        from .keyboard_diagnostics import run
        return run(application, sys.argv[2])
    if len(sys.argv) == 3 and sys.argv[1] == "--experience-self-test":
        from .experience_diagnostics import run
        return run(application, sys.argv[2])
    if len(sys.argv) == 3 and sys.argv[1] == "--catalog-self-test":
        from .catalog_diagnostics import run
        return run(application, sys.argv[2])
    if len(sys.argv) == 3 and sys.argv[1] == "--bookmark-self-test":
        from .bookmark_diagnostics import run
        return run(application, sys.argv[2])
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        from .diagnostics import run
        return run(application, sys.argv[2])
    frame = BookmarkFrame()
    frame.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
