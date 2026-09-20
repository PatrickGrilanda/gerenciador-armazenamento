from __future__ import annotations

import ctypes
import string
from dataclasses import dataclass

import psutil


@dataclass(frozen=True)
class DriveInfo:
    letter: str
    label: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    drive_type: str

    @property
    def mount_path(self) -> str:
        return f"{self.letter}:\\"


def _volume_label(root: str) -> str:
    buf = ctypes.create_unicode_buffer(261)
    if ctypes.windll.kernel32.GetVolumeInformationW(
        ctypes.c_wchar_p(root),
        buf,
        ctypes.sizeof(buf),
        None,
        None,
        None,
        None,
        0,
    ):
        return buf.value or ""
    return ""


def _drive_type_name(root: str) -> str:
    kernel32 = ctypes.windll.kernel32
    drive_type = kernel32.GetDriveTypeW(ctypes.c_wchar_p(root))
    names = {
        2: "Removível",
        3: "Disco local",
        4: "Rede",
        5: "CD/DVD",
        6: "RAM",
    }
    return names.get(drive_type, "Outro")


def list_drives() -> list[DriveInfo]:
    drives: list[DriveInfo] = []
    for part in psutil.disk_partitions(all=False):
        if not part.mountpoint or len(part.mountpoint) < 2:
            continue
        letter = part.mountpoint[0].upper()
        if letter not in string.ascii_uppercase:
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue
        root = f"{letter}:\\"
        label = _volume_label(root)
        drives.append(
            DriveInfo(
                letter=letter,
                label=label,
                total_bytes=usage.total,
                used_bytes=usage.used,
                free_bytes=usage.free,
                drive_type=_drive_type_name(root),
            )
        )
    drives.sort(key=lambda d: d.letter)
    return drives
