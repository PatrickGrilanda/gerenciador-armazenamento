from __future__ import annotations

import heapq
import os
import stat
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable


@dataclass
class EntrySize:
    name: str
    path: str
    size_bytes: int
    is_dir: bool
    child_count: int = 0
    folder_size_unknown: bool = False


@dataclass(frozen=True)
class LargeFile:
    path: str
    name: str
    size_bytes: int
    modified_at: datetime | None


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


def _is_reparse_or_link(entry: os.DirEntry) -> bool:
    try:
        if entry.is_symlink():
            return True
    except OSError:
        return True
    is_junction = getattr(entry, "is_junction", None)
    if callable(is_junction):
        try:
            if entry.is_junction():
                return True
        except OSError:
            return True
    if os.name == "nt":
        try:
            attrs = entry.stat(follow_symlinks=False).st_file_attributes
            if attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                return True
        except (OSError, AttributeError):
            pass
    return False


def _dir_size(path: Path, cancel: threading.Event | None = None) -> int:
    total = 0
    stack = [path]
    while stack:
        if cancel and cancel.is_set():
            return total
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    if cancel and cancel.is_set():
                        return total
                    try:
                        if _is_reparse_or_link(entry):
                            continue
                        if entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                        elif entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def scan_directory(
    root: str,
    *,
    deep_folders: bool = False,
    max_workers: int = 8,
    cancel: threading.Event | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> list[EntrySize]:
    """Lista filhos imediatos. Por padrão é rápido; pastas não somam subpastas."""
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
    for entry in entries:
        if cancel and cancel.is_set():
            break
        try:
            if _is_reparse_or_link(entry):
                continue
            if entry.is_dir(follow_symlinks=False):
                dirs.append(Path(entry.path))
            elif entry.is_file(follow_symlinks=False):
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
        except OSError:
            continue

    if deep_folders and dirs:
        workers = min(max_workers, len(dirs))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_dir_size, d, cancel): d for d in dirs}
            for future in as_completed(futures):
                d = futures[future]
                if on_progress:
                    on_progress(str(d))
                try:
                    size = future.result()
                except OSError:
                    size = 0
                child_count = _child_count(d)
                children.append(
                    EntrySize(
                        name=d.name,
                        path=str(d),
                        size_bytes=size,
                        is_dir=True,
                        child_count=child_count,
                    )
                )
    else:
        for d in dirs:
            child_count = _child_count(d)
            children.append(
                EntrySize(
                    name=d.name,
                    path=str(d),
                    size_bytes=0,
                    is_dir=True,
                    child_count=child_count,
                    folder_size_unknown=True,
                )
            )

    def _sort_key(entry: EntrySize) -> tuple:
        if entry.folder_size_unknown:
            return (1, 0, entry.name.lower())
        return (0, -entry.size_bytes, entry.name.lower())

    children.sort(key=_sort_key)
    return children


def _child_count(path: Path) -> int:
    try:
        with os.scandir(path) as sub:
            return sum(1 for _ in sub)
    except OSError:
        return 0


def _scan_branch_for_large_files(
    root: str,
    min_bytes: int,
    cancel: threading.Event | None,
    progress: Callable[[int, str], None] | None,
    progress_lock: threading.Lock,
    files_scanned: list[int],
) -> list[LargeFile]:
    found: list[LargeFile] = []
    stack = [root]
    local_scanned = 0

    while stack:
        if cancel and cancel.is_set():
            break
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    if cancel and cancel.is_set():
                        break
                    try:
                        if _is_reparse_or_link(entry):
                            continue
                        if entry.is_file(follow_symlinks=False):
                            local_scanned += 1
                            if local_scanned % 400 == 0 and progress:
                                with progress_lock:
                                    files_scanned[0] += 400
                                    progress(files_scanned[0], entry.path)
                            try:
                                st = entry.stat(follow_symlinks=False)
                                size = st.st_size
                            except OSError:
                                continue
                            if size < min_bytes:
                                continue
                            modified = None
                            try:
                                modified = datetime.fromtimestamp(st.st_mtime)
                            except (OSError, OverflowError, ValueError):
                                pass
                            found.append(
                                LargeFile(
                                    path=entry.path,
                                    name=entry.name,
                                    size_bytes=size,
                                    modified_at=modified,
                                )
                            )
                        elif entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                    except OSError:
                        continue
        except OSError:
            continue

    if progress and local_scanned:
        remainder = local_scanned % 400
        if remainder:
            with progress_lock:
                files_scanned[0] += remainder
                progress(files_scanned[0], root)

    return found


def find_large_files(
    root: str,
    *,
    min_bytes: int,
    max_results: int = 300,
    max_workers: int = 6,
    cancel: threading.Event | None = None,
    on_progress: Callable[[int, str], None] | None = None,
) -> list[LargeFile]:
    """
    Varre o volume em paralelo (por pastas de primeiro nível) e retorna
    os maiores arquivos acima de min_bytes.
    """
    root_path = Path(root)
    if not root_path.exists():
        return []

    branches: list[str] = [str(root_path)]
    try:
        with os.scandir(root_path) as it:
            top_dirs = []
            top_files: list[LargeFile] = []
            for entry in it:
                if cancel and cancel.is_set():
                    return []
                try:
                    if _is_reparse_or_link(entry):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        top_dirs.append(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        try:
                            st = entry.stat(follow_symlinks=False)
                            size = st.st_size
                        except OSError:
                            continue
                        if size >= min_bytes:
                            modified = None
                            try:
                                modified = datetime.fromtimestamp(st.st_mtime)
                            except (OSError, OverflowError, ValueError):
                                pass
                            top_files.append(
                                LargeFile(
                                    path=entry.path,
                                    name=entry.name,
                                    size_bytes=size,
                                    modified_at=modified,
                                )
                            )
                except OSError:
                    continue
    except OSError:
        top_dirs = []
        top_files = []

    if top_dirs:
        branches = top_dirs

    progress_lock = threading.Lock()
    files_scanned = [0]
    collected: list[LargeFile] = list(top_files)
    workers = min(max_workers, max(1, len(branches)))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(
                _scan_branch_for_large_files,
                branch,
                min_bytes,
                cancel,
                on_progress,
                progress_lock,
                files_scanned,
            )
            for branch in branches
        ]
        for future in as_completed(futures):
            if cancel and cancel.is_set():
                break
            try:
                collected.extend(future.result())
            except OSError:
                continue

    if cancel and cancel.is_set():
        return []

    heap: list[tuple[int, int, LargeFile]] = []
    for index, item in enumerate(collected):
        if len(heap) < max_results:
            heapq.heappush(heap, (item.size_bytes, index, item))
        elif item.size_bytes > heap[0][0]:
            heapq.heapreplace(heap, (item.size_bytes, index, item))

    ordered = sorted(heap, key=lambda t: (-t[0], t[1]))
    return [item for _, _, item in ordered]
