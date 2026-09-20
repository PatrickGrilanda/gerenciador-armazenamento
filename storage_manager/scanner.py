from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass
class EntrySize:
    name: str
    path: str
    size_bytes: int
    is_dir: bool
    child_count: int = 0


def format_bytes(num: int) -> str:
    if num < 0:
        num = 0
    units = ("B", "KB", "MB", "GB", "TB")
    value = float(num)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{num} B"


def _dir_size(path: Path) -> int:
    total = 0
    try:
        with os.scandir(path) as it:
            for entry in it:
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_file(follow_symlinks=False):
                        total += entry.stat(follow_symlinks=False).st_size
                    elif entry.is_dir(follow_symlinks=False):
                        total += _dir_size(Path(entry.path))
                except OSError:
                    continue
    except OSError:
        pass
    return total


def scan_directory(
    root: str,
    *,
    max_workers: int = 8,
    on_progress: Callable[[str], None] | None = None,
) -> list[EntrySize]:
    root_path = Path(root)
    if not root_path.exists():
        return []

    children: list[EntrySize] = []
    try:
        with os.scandir(root_path) as it:
            entries = list(it)
    except OSError:
        return []

    dirs: list[Path] = []
    files: list[os.DirEntry] = []
    for entry in entries:
        try:
            if entry.is_symlink():
                continue
            if entry.is_dir(follow_symlinks=False):
                dirs.append(Path(entry.path))
            elif entry.is_file(follow_symlinks=False):
                files.append(entry)
        except OSError:
            continue

    for entry in files:
        try:
            size = entry.stat(follow_symlinks=False).st_size
        except OSError:
            size = 0
        children.append(
            EntrySize(
                name=entry.name,
                path=entry.path,
                size_bytes=size,
                is_dir=False,
            )
        )

    if dirs:
        workers = min(max_workers, len(dirs))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_dir_size, d): d for d in dirs}
            for future in as_completed(futures):
                d = futures[future]
                if on_progress:
                    on_progress(str(d))
                try:
                    size = future.result()
                except OSError:
                    size = 0
                child_count = 0
                try:
                    with os.scandir(d) as sub:
                        child_count = sum(1 for _ in sub)
                except OSError:
                    pass
                children.append(
                    EntrySize(
                        name=d.name,
                        path=str(d),
                        size_bytes=size,
                        is_dir=True,
                        child_count=child_count,
                    )
                )

    children.sort(key=lambda e: e.size_bytes, reverse=True)
    return children
