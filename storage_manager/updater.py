from __future__ import annotations

import json
import re
import ssl
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from storage_manager import __version__
from storage_manager.config import GITHUB_REPO_FULL, INSTALLER_ASSET_PREFIX


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    tag: str
    name: str
    body: str
    published_at: str
    installer_url: str
    installer_name: str
    installer_size: int


ProgressCallback = Callable[[int, int], None]


def _parse_version(version: str) -> tuple[int, ...]:
    cleaned = version.strip().lstrip("v")
    parts = re.findall(r"\d+", cleaned)
    if not parts:
        return (0,)
    return tuple(int(p) for p in parts)


def is_newer(remote: str, current: str) -> bool:
    remote_parts = _parse_version(remote)
    current_parts = _parse_version(current)
    length = max(len(remote_parts), len(current_parts))
    remote_parts += (0,) * (length - len(remote_parts))
    current_parts += (0,) * (length - len(current_parts))
    return remote_parts > current_parts


def _api_request(url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"GerenciadorArmazenamento/{__version__}",
        },
    )
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=30, context=ctx) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_latest_release() -> ReleaseInfo | None:
    url = f"https://api.github.com/repos/{GITHUB_REPO_FULL}/releases/latest"
    try:
        data = _api_request(url)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    tag = str(data.get("tag_name", "")).strip()
    version = tag.lstrip("v") or tag
    installer_url = ""
    installer_name = ""
    installer_size = 0
    for asset in data.get("assets", []):
        name = str(asset.get("name", ""))
        if name.startswith(INSTALLER_ASSET_PREFIX) and name.lower().endswith(".exe"):
            installer_url = str(asset.get("browser_download_url", ""))
            installer_name = name
            installer_size = int(asset.get("size", 0) or 0)
            break
    if not installer_url:
        raise RuntimeError(
            "A release mais recente não inclui o instalador (.exe). "
            "Aguarde a publicação do build ou baixe manualmente no GitHub."
        )
    return ReleaseInfo(
        version=version,
        tag=tag,
        name=str(data.get("name", tag)),
        body=str(data.get("body", "") or ""),
        published_at=str(data.get("published_at", "")),
        installer_url=installer_url,
        installer_name=installer_name,
        installer_size=installer_size,
    )


def check_for_update() -> tuple[str, ReleaseInfo | None]:
    latest = fetch_latest_release()
    if latest is None:
        return "none", None
    if is_newer(latest.version, __version__):
        return "available", latest
    return "current", latest


def download_installer(
    release: ReleaseInfo,
    *,
    on_progress: ProgressCallback | None = None,
) -> Path:
    destination = Path(tempfile.gettempdir()) / release.installer_name
    req = urllib.request.Request(
        release.installer_url,
        headers={"User-Agent": f"GerenciadorArmazenamento/{__version__}"},
    )
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=120, context=ctx) as response:
        total = int(response.headers.get("Content-Length", release.installer_size) or 0)
        chunk_size = 256 * 1024
        downloaded = 0
        with destination.open("wb") as handle:
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                handle.write(chunk)
                downloaded += len(chunk)
                if on_progress:
                    on_progress(downloaded, total)
    return destination
