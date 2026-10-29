"""Validate a native Mac build, then produce architecture-specific ZIP and DMG."""
import hashlib
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from floattranslate import __version__


def main():
    if sys.platform != "darwin":
        raise SystemExit("Run this script on macOS after python build.py")
    root = Path(__file__).resolve().parent
    app = root / "dist/FloatTranslateNext.app"
    executable = app / "Contents/MacOS/FloatTranslateNext"
    reports = root / "build-reports"
    reports.mkdir(exist_ok=True)
    release = root / "release"
    release.mkdir(exist_ok=True)
    arch = "arm64" if platform.machine() == "arm64" else "x64"
    name = f"FloatTranslateNext-{__version__}-macOS-{arch}"
    subprocess.run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)], check=True)
    for flag, report in (("--update-health-check", "qt-health.json"), ("--mac-self-test", "mac-runtime.json")):
        subprocess.run([str(executable), flag, str(reports / report)], check=True, timeout=120)
        result = json.loads((reports / report).read_text("utf-8"))
        if not result.get("passed"):
            raise RuntimeError(f"Runtime check failed: {report}")
    file_info = subprocess.check_output(["file", str(executable)], text=True)
    (reports / "architecture.txt").write_text(file_info, "utf-8")
    if ("arm64" if arch == "arm64" else "x86_64") not in file_info:
        raise RuntimeError("Built executable architecture does not match runner")
    subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(release / (name + ".app.zip"))], check=True)
    staging = root / "build/dmg-staging"
    staging.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ditto", str(app), str(staging / app.name)], check=True)
    (staging / "Applications").symlink_to("/Applications", target_is_directory=True)
    shutil.copy2(root / "MACOS.md", staging / "安装与权限说明.md")
    subprocess.run(["hdiutil", "create", "-volname", "FloatTranslate Next", "-srcfolder", str(staging), "-ov", "-format", "UDZO", str(release / (name + ".dmg"))], check=True)
    files = [release / (name + suffix) for suffix in (".app.zip", ".dmg")]
    (release / (name + "-sha256.txt")).write_text("\n".join(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name for path in files) + "\n", "utf-8")


if __name__ == "__main__":
    main()
