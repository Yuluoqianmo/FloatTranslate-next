"""Build on the target OS: python build.py. macOS apps must be built on a Mac."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def main():
    # A developer shell may put unrelated PDF/image/video DLLs on PATH.
    # PyInstaller can otherwise collect their CRT/OpenSSL DLLs instead of the
    # Python/Qt dependencies, yielding an EXE that fails to import QtGui.
    # Limit DLL discovery in THIS process only; never edit the system PATH.
    if sys.platform == "win32":
        python_root = Path(sys.base_prefix)
        windows_root = Path(os.environ.get("SystemRoot", "C:/Windows"))
        os.environ["PATH"] = os.pathsep.join(str(p) for p in (
            python_root, python_root/"DLLs", windows_root/"System32", windows_root,
        ))
        for variable in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QML2_IMPORT_PATH"):
            os.environ.pop(variable, None)
    import PyInstaller.__main__
    root = Path(__file__).resolve().parent
    args = [str(root/"run.py"), "--noconfirm", "--clean", "--windowed", "--name", "FloatTranslateNext",
            "--distpath", str(root/"dist"), "--workpath", str(root/"build"), "--specpath", str(root),
            "--collect-all", "keyring", "--copy-metadata", "keyring",
            "--exclude-module", "PySide6.QtWebEngineCore", "--exclude-module", "PySide6.QtWebEngineWidgets",
            "--exclude-module", "tkinter", "--exclude-module", "pytest"]
    if sys.platform == "win32":
        args += ["--onefile", "--collect-all", "winrt", "--collect-all", "win32ctypes"]
    elif sys.platform == "darwin":
        args += ["--onedir", "--osx-bundle-identifier", "io.floattranslate.next",
                 "--hidden-import", "Vision", "--hidden-import", "Quartz", "--hidden-import", "Foundation",
                 "--hidden-import", "AppKit"]
        for source in (root/"LICENSE", root/"THIRD_PARTY_NOTICES.md", root/"licenses"):
            args += ["--add-data", f"{source}:licenses"]
    else:
        raise SystemExit("Build currently supports Windows and macOS only")
    PyInstaller.__main__.run(args)
    if sys.platform == "darwin":
        import plistlib
        import subprocess
        import shutil
        from importlib.metadata import distribution
        bundle = root/"dist/FloatTranslateNext.app"
        for dependency in ("pyobjc-core", "pyobjc-framework-Cocoa", "pyobjc-framework-Quartz", "pyobjc-framework-Vision", "pyobjc-framework-CoreML"):
            dist = distribution(dependency)
            for filename in dist.files or []:
                if filename.name.lower().startswith(("license", "copying")):
                    target = bundle/"Contents/Resources/licenses"/dependency/filename.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(dist.locate_file(filename), target)
        plist = bundle/"Contents/Info.plist"
        data = plistlib.loads(plist.read_bytes())
        data.update({"NSHighResolutionCapable": True, "LSMinimumSystemVersion": "14.0",
                     "LSUIElement": True,
                     "CFBundleDisplayName": "FloatTranslate Next",
                     "NSScreenCaptureUsageDescription": "FloatTranslate captures only the selected screen region to recognize and translate its text.",
                     "CFBundleShortVersionString": "0.3.9"})
        plist.write_bytes(plistlib.dumps(data))
        # Locally runnable ad-hoc signature. Public distribution still needs the
        # developer's own Apple certificate and notarization.
        subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(bundle)], check=True)


if __name__ == "__main__":
    main()
