"""After building: python release_manifest.py dist/FloatTranslateNext.exe output-folder"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

from floattranslate import __version__


def main():
    source, directory = Path(sys.argv[1]), Path(sys.argv[2])
    directory.mkdir(parents=True, exist_ok=True)
    name = f"FloatTranslateNext-{__version__}.exe"
    destination = directory / name
    if source.resolve() != destination.resolve():
        shutil.copy2(source, destination)
    entry = {"name": name, "size": destination.stat().st_size,
             "sha256": hashlib.sha256(destination.read_bytes()).hexdigest()}
    manifest = {"schema": 1, "product": "floattranslate-next", "version": __version__, "assets": {"windows-x64": entry}}
    (directory / "floattranslate-next-update.json").write_text(json.dumps(manifest, indent=2), "utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
