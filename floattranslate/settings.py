from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlsplit


def config_dir() -> Path:
    override = os.environ.get("FLOATTRANSLATE_CONFIG_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", str(Path.home()))) / "FloatTranslateNext"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/FloatTranslateNext"
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "FloatTranslateNext"


@dataclass(frozen=True)
class Settings:
    provider: str = "auto"
    base_url: str = ""
    model: str = ""
    target: str = "简体中文"
    ocr_language: str = ""
    interval_ms: int = 1500
    reduce_motion: bool = False
    always_on_top: bool = True
    border_width: int = 2
    mask_opacity: int = 100
    font_size: int = 22
    fast_mode: bool = True
    toggle_shortcut: str = "Alt+T"
    translate_shortcut: str = "Ctrl+Alt+Return"
    api_protocol: str = "auto"
    auth_mode: str = "auto"
    update_repo: str = "Yuluoqianmo/FloatTranslate-next"
    update_auto_check: bool = True
    update_last_check: int = 0

    @classmethod
    def load(cls, directory: Path | None = None) -> "Settings":
        try:
            data = json.loads(((directory or config_dir()) / "settings.json").read_text("utf-8"))
            fields = cls.__dataclass_fields__
            defaults = cls()
            valid = {k: v for k, v in data.items() if k in fields and type(v) is type(getattr(defaults, k))}
            valid["interval_ms"] = max(700, min(10000, valid.get("interval_ms", 1500)))
            valid["border_width"] = max(1, min(5, valid.get("border_width", 2)))
            valid["mask_opacity"] = max(80, min(100, valid.get("mask_opacity", 100)))
            valid["font_size"] = max(10, min(28, valid.get("font_size", 22)))
            return cls(**valid)
        except (OSError, ValueError, TypeError, AttributeError):
            return cls()

    def save(self, directory: Path | None = None) -> None:
        directory = directory or config_dir()
        directory.mkdir(parents=True, exist_ok=True)
        temp = directory / "settings.json.tmp"
        temp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), "utf-8")
        temp.replace(directory / "settings.json")


class SecretStore:
    """Keep credentials in the OS keychain; never write them to settings JSON."""

    def __init__(self):
        self._session: dict[str, str] = {}

    @staticmethod
    def identity(provider: str, base_url: str) -> str:
        # Bind a credential to the exact endpoint, including a gateway path.
        value = provider + "|" + base_url.rstrip("/")
        return hashlib.sha256(value.encode()).hexdigest()

    def get(self, identity: str) -> str:
        if identity in self._session:
            return self._session[identity]
        try:
            import keyring
            value = keyring.get_password("FloatTranslateNext", identity) or ""
            if value:
                self._session[identity] = value
            return value
        except Exception:
            return ""

    def set(self, identity: str, key: str) -> bool:
        self._session[identity] = key
        try:
            import keyring
            if key:
                keyring.set_password("FloatTranslateNext", identity, key)
            else:
                try:
                    keyring.delete_password("FloatTranslateNext", identity)
                except keyring.errors.PasswordDeleteError:
                    pass
            return True
        except Exception:
            return False


def validate_base_url(value: str) -> str:
    value = value.strip().rstrip("/")
    parts = urlsplit(value)
    if not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("请输入不含账号、查询参数的 API 基础地址")
    local = parts.hostname in ("localhost", "127.0.0.1", "::1")
    if parts.scheme != "https" and not (parts.scheme == "http" and local):
        raise ValueError("API 地址需要 HTTPS；本机服务可使用 HTTP")
    return value
