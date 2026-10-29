"""Native About UI smoke check; no network, credentials or translation requests."""
import json
from pathlib import Path

from PySide6.QtCore import QTimer

from . import __version__
from .bookmark import BookmarkFrame


def run(application, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    frame = BookmarkFrame(test_mode=True)
    calls = []
    frame.scan = lambda *args, **kwargs: calls.append(True)
    frame.show()
    frame.show_about()
    def verify():
        dialog = frame._dialog
        dialog.grab().save(str(folder / "about.png"))
        result = {"version": __version__, "about_visible": dialog.isVisible(), "auto_check_default": dialog.auto.isChecked()}
        dialog.close()
        def finish():
            result.update({"bookmark_survives_close": frame.bookmark.isVisible(), "no_translation_triggered": not calls})
            result["passed"] = all(result[key] for key in ("about_visible", "bookmark_survives_close", "no_translation_triggered"))
            (folder / "report.json").write_text(json.dumps(result, indent=2), "utf-8")
            frame.close()
            application.exit(0 if result["passed"] else 1)
        QTimer.singleShot(250, finish)
    QTimer.singleShot(400, verify)
    return application.exec()
