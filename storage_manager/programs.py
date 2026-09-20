from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

import winreg


@dataclass(frozen=True)
class InstalledProgram:
    name: str
    publisher: str
    version: str
    install_location: str
    estimated_size_kb: int
    uninstall_string: str
    quiet_uninstall_string: str
    registry_path: str

    @property
    def estimated_size_bytes(self) -> int:
        return self.estimated_size_kb * 1024


_UNINSTALL_ROOTS = (
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    (
        winreg.HKEY_LOCAL_MACHINE,
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
    ),
    (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
)


def _read_str(key: winreg.HKEYType, name: str) -> str:
    try:
        value, _ = winreg.QueryValueEx(key, name)
        if value is None:
            return ""
        return str(value).strip()
    except OSError:
        return ""


def _read_dword(key: winreg.HKEYType, name: str) -> int:
    try:
        value, _ = winreg.QueryValueEx(key, name)
        if isinstance(value, int):
            return value
    except OSError:
        pass
    return 0


def _enum_programs() -> list[InstalledProgram]:
    found: dict[str, InstalledProgram] = {}

    for hive, subkey in _UNINSTALL_ROOTS:
        try:
            with winreg.OpenKey(hive, subkey) as root:
                index = 0
                while True:
                    try:
                        child_name = winreg.EnumKey(root, index)
                    except OSError:
                        break
                    index += 1
                    try:
                        with winreg.OpenKey(root, child_name) as key:
                            display = _read_str(key, "DisplayName")
                            if not display:
                                continue
                            system = _read_dword(key, "SystemComponent")
                            if system == 1:
                                continue
                            release_type = _read_str(key, "ReleaseType")
                            if release_type in ("Security Update", "Update", "Hotfix"):
                                continue
                            uninstall = _read_str(key, "UninstallString")
                            if not uninstall:
                                continue
                            program = InstalledProgram(
                                name=display,
                                publisher=_read_str(key, "Publisher"),
                                version=_read_str(key, "DisplayVersion"),
                                install_location=_read_str(key, "InstallLocation"),
                                estimated_size_kb=_read_dword(key, "EstimatedSize"),
                                uninstall_string=uninstall,
                                quiet_uninstall_string=_read_str(key, "QuietUninstallString"),
                                registry_path=f"{subkey}\\{child_name}",
                            )
                            key_id = program.name.lower()
                            existing = found.get(key_id)
                            if existing is None or program.estimated_size_kb > existing.estimated_size_kb:
                                found[key_id] = program
                    except OSError:
                        continue
        except OSError:
            continue

    programs = list(found.values())
    programs.sort(key=lambda p: (p.estimated_size_bytes, p.name.lower()), reverse=True)
    return programs


def list_installed_programs() -> list[InstalledProgram]:
    return _enum_programs()


def _split_uninstall_command(command: str) -> list[str]:
    command = command.strip()
    if not command:
        return []
    if command[0] in ('"', "'"):
        match = re.match(r'^("([^"]*)"|\'([^\']*)\')\s*(.*)$', command)
        if match:
            exe = match.group(2) or match.group(3)
            rest = match.group(4).strip()
            if rest:
                return [exe] + rest.split()
            return [exe]
    parts = command.split()
    return parts if parts else []


def run_uninstall(program: InstalledProgram, *, quiet: bool = False) -> subprocess.Popen[str]:
    cmd = program.quiet_uninstall_string if quiet and program.quiet_uninstall_string else program.uninstall_string
    args = _split_uninstall_command(cmd)
    if not args:
        raise ValueError("Comando de desinstalação inválido.")
    return subprocess.Popen(args, shell=False)
