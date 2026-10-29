"""Public GitHub releases, independent of translation-provider credentials."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx

PRODUCT = "floattranslate-next"
MANIFEST = "floattranslate-next-update.json"
MAX_DOWNLOAD = 350 * 1024 * 1024


def repository(value: str) -> str:
    value = value.strip().rstrip("/")
    if value.startswith("https://"):
        parts = urlsplit(value)
        if parts.netloc.lower() != "github.com" or parts.query or parts.fragment:
            raise ValueError("请输入 github.com 的完整仓库地址或 用户名/仓库名")
        value = parts.path.strip("/")
    if value.endswith(".git"):
        value = value[:-4]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}", value):
        raise ValueError("需要完整的 用户名/仓库名，例如 yourname/FloatTranslate-next")
    if value.split("/")[1] in (".", ".."):
        raise ValueError("仓库名无效")
    return value


def version(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", value)
    if not match:
        raise ValueError("版本必须是稳定版 x.y.z")
    return tuple(map(int, match.groups()))


def platform_key() -> str:
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x64" if machine in ("amd64", "x86_64") else machine
    return f"{'windows' if sys.platform == 'win32' else 'macos' if sys.platform == 'darwin' else sys.platform}-{arch}"


@dataclass(frozen=True)
class Release:
    version: str
    page: str
    notes: str
    name: str
    url: str
    sha256: str
    size: int


def _asset_url(url: str, repo: str) -> str:
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.netloc.lower() != "github.com"
            or not parts.path.lower().startswith(f"/{repo}/releases/download/".lower())
            or parts.query or parts.fragment):
        raise ValueError("更新附件不属于配置的 GitHub 仓库")
    return url


def _json(client, url: str, limit: int):
    with client.stream("GET", url) as response:
        if response.status_code == 404:
            raise ValueError("仓库不存在、不是公开仓库，或尚未发布更新附件")
        if response.status_code in (403, 429):
            raise ValueError("GitHub 请求受限，请稍后重试")
        response.raise_for_status()
        data = bytearray()
        for chunk in response.iter_bytes():
            data.extend(chunk)
            if len(data) > limit:
                raise ValueError("更新信息过大")
        return json.loads(data)


def client():
    return httpx.Client(timeout=httpx.Timeout(30, connect=8), follow_redirects=True,
                        headers={"User-Agent": "FloatTranslateNext-Updater", "Accept": "application/vnd.github+json"})


def check(repo: str, current: str, *, http=None, target=None) -> Release | None:
    repo = repository(repo)
    if http is None:
        with client() as connection:
            return check(repo, current, http=connection, target=target)
    releases = _json(http, f"https://api.github.com/repos/{repo}/releases?per_page=100", 4 * 1024 * 1024)
    if not isinstance(releases, list):
        raise ValueError("GitHub 发布列表格式无效")
    candidates = []
    for item in releases:
        if not isinstance(item, dict) or item.get("draft") or item.get("prerelease"):
            continue
        try:
            number = version(item.get("tag_name", ""))
        except (ValueError, TypeError):
            continue
        if number > version(current):
            candidates.append((number, item))
    for number, item in sorted(candidates, key=lambda pair: pair[0], reverse=True):
        assets = {a.get("name"): a for a in item.get("assets", []) if isinstance(a, dict)}
        if MANIFEST not in assets:
            continue  # An unrelated upstream product is never an install candidate.
        manifest = _json(http, _asset_url(assets[MANIFEST]["browser_download_url"], repo), 64 * 1024)
        if not isinstance(manifest, dict) or manifest.get("product") != PRODUCT or manifest.get("schema") != 1:
            continue
        if version(manifest.get("version", "")) != number:
            raise ValueError("更新清单版本与发布标签不一致")
        entry = manifest.get("assets", {}).get(target or platform_key())
        if not entry:
            continue
        name = entry.get("name", "")
        name_version = ".".join(map(str, number))
        if (name not in assets or not re.fullmatch(r"FloatTranslateNext-[0-9.]+\.(exe|zip)", name)
                or name != f"FloatTranslateNext-{name_version}.{'exe' if (target or platform_key()).startswith('windows-') else 'zip'}"):
            raise ValueError("更新附件名称无效")
        digest, size = entry.get("sha256", ""), entry.get("size")
        if not re.fullmatch(r"[a-fA-F0-9]{64}", digest) or type(size) is not int or not 0 < size <= MAX_DOWNLOAD:
            raise ValueError("更新附件校验信息无效")
        if assets[name].get("size") != size:
            raise ValueError("更新附件大小与清单不一致")
        page = f"https://github.com/{repo}/releases/tag/{item['tag_name']}"
        return Release(name_version, page, str(item.get("body") or "暂无更新说明")[:20000], name,
                       _asset_url(assets[name]["browser_download_url"], repo), digest.lower(), size)
    return None


def download(release: Release, directory: Path, *, http=None, progress=lambda value: None) -> Path:
    if http is None:
        with client() as connection:
            return download(release, directory, http=connection, progress=progress)
    directory.mkdir(parents=True, exist_ok=True)
    # A unique directory also isolates two app instances and interrupted downloads.
    destination = directory / uuid.uuid4().hex
    destination.mkdir()
    final = destination / release.name
    partial = final.with_suffix(final.suffix + ".part")
    total = 0
    digest = hashlib.sha256()
    try:
        with http.stream("GET", release.url) as response, partial.open("xb") as handle:
            response.raise_for_status()
            for chunk in response.iter_bytes(128 * 1024):
                total += len(chunk)
                if total > release.size or total > MAX_DOWNLOAD:
                    raise ValueError("下载大小超过更新清单")
                digest.update(chunk)
                handle.write(chunk)
                progress(int(total * 100 / release.size))
        if total != release.size or digest.hexdigest() != release.sha256:
            raise ValueError("下载不完整或 SHA-256 校验失败，请重新下载")
        if final.suffix == ".exe":
            with partial.open("rb") as handle:
                if handle.read(2) != b"MZ":
                    raise ValueError("下载附件不是 Windows 程序")
        partial.replace(final)
        return final
    except Exception:
        partial.unlink(missing_ok=True)
        raise


# Fixed script; file paths travel in JSON, never as PowerShell source fragments.
INSTALL_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
$job = Get-Content -LiteralPath $jobPath -Raw -Encoding UTF8 | ConvertFrom-Json
$backup = $job.target + '.previous'
$staged = $job.target + '.update-' + [Guid]::NewGuid().ToString('N') + '.exe'
try {
    $healthPath = $job.source + '.health.json'
    $candidate = Start-Process -FilePath $job.source -ArgumentList @('--update-health-check', ('"' + $healthPath + '"')) -PassThru -WindowStyle Hidden
    if (-not $candidate.WaitForExit(60000)) { $candidate.Kill(); throw '新版本启动检查超时' }
    if ($candidate.ExitCode -ne 0) { throw '新版本启动检查失败' }
    $health = Get-Content -LiteralPath $healthPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($health.product -ne 'floattranslate-next' -or $health.version -ne $job.version -or $health.passed -ne $true) { throw '新版本身份检查失败' }
    $hasher = [Security.Cryptography.SHA256]::Create()
    $stream = [IO.File]::OpenRead($job.source)
    try { $actualHash = [BitConverter]::ToString($hasher.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
    finally { $stream.Dispose(); $hasher.Dispose() }
    if ($actualHash -ne $job.sha256) { throw '安装前校验失败' }
    # Signal readiness before asking the running app to exit.
    [IO.File]::WriteAllText($job.ready, 'ready')
    $running = Get-Process -Id $job.pid -ErrorAction SilentlyContinue
    if ($running -and -not $running.WaitForExit(120000)) { throw '等待旧版本退出超时' }
    Copy-Item -LiteralPath $job.source -Destination $staged
    $replaced = $false
    for ($attempt=0; $attempt -lt 120; $attempt++) {
        try {
            [IO.File]::Replace($staged, $job.target, $backup, $true)
            $replaced = $true
            break
        } catch { Start-Sleep -Milliseconds 500 }
    }
    if (-not $replaced) { throw '程序仍被占用或安装目录不可写，旧版本已保留' }
    try { Start-Process -FilePath $job.target -WorkingDirectory ([IO.Path]::GetDirectoryName($job.target)) -WindowStyle Hidden }
    catch { [IO.File]::Copy($backup, $job.target, $true); throw }
    [IO.File]::WriteAllText($job.result, 'success')
} catch {
    [IO.File]::WriteAllText($job.result, $_.Exception.Message)
} finally {
    if (Test-Path -LiteralPath $staged) { Remove-Item -LiteralPath $staged }
}
'''


def start_install(path: Path, release: Release, directory: Path) -> tuple[Path, Path]:
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        raise ValueError("自动替换适用于 Windows EXE；源码 / macOS 请从发布页手动安装")
    target = Path(sys.executable).resolve()
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != release.sha256:
        raise ValueError("安装包校验失败，请重新下载")
    directory.mkdir(parents=True, exist_ok=True)
    probe = target.parent / (".floattranslate-write-" + uuid.uuid4().hex)
    try:
        probe.write_bytes(b"")
    finally:
        probe.unlink(missing_ok=True)
    job_path = directory / ("install-" + uuid.uuid4().hex + ".json")
    ready, result = job_path.with_suffix(".ready"), job_path.with_suffix(".result")
    job_path.write_text(json.dumps({"source": str(path.resolve()), "target": str(target), "version": release.version,
                                   "sha256": release.sha256, "pid": os.getpid(), "ready": str(ready), "result": str(result)}), "utf-8")
    encoded_path = base64.b64encode(str(job_path.resolve()).encode("utf-8")).decode("ascii")
    script = f"$jobPath = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded_path}'))\n" + INSTALL_SCRIPT
    command = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    powershell = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    subprocess.Popen([str(powershell), "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-EncodedCommand", command],
                     creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS, close_fds=True)
    return ready, result
