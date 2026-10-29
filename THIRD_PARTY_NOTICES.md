# Third-party components

FloatTranslate Next is derived from CH-DONG77/FloatTranslate (MIT). The original copyright and license are preserved in LICENSE.

Runtime dependencies retain their own licenses:

| Component | License / upstream |
| --- | --- |
| PySide6 / Qt | LGPL v3 / GPL v3 / commercial; https://www.qt.io/licensing/ |
| Shiboken6 | LGPL v3 / GPL v3 / commercial; https://code.qt.io/cgit/pyside/pyside-setup.git/ |
| Pillow | HPND; https://github.com/python-pillow/Pillow |
| httpx / httpcore / anyio | BSD-3-Clause / BSD-3-Clause / MIT; upstream packages |
| keyring | MIT; https://github.com/jaraco/keyring |
| PyWinRT | MIT; https://github.com/pywinrt/pywinrt |
| PyObjC (macOS) | MIT; https://github.com/ronaldoussoren/pyobjc |
| PyInstaller bootloader | GPL with bootloader exception; https://pyinstaller.org/en/stable/license.html |

Qt is linked dynamically. Use the source build / onedir build when you need to inspect or replace bundled Qt libraries. The source in this directory includes the complete application and build script. Qt's source and license texts are available from the Qt upstream repositories; retain the license texts and notices with redistributed binaries.
