"""Portable paths, with no AutoCAD connection or configuration side effects."""
from __future__ import annotations
import os
import sys
from pathlib import Path

BUILD_ID = "portable-20261127.1"
NATIVE_MODULES = ("CadMcpNative2026", "CadMcpArch2026V2Safe", "CadMcpProjectFix2026")

def absolute_directory(value: str, name: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{name} must be an absolute directory: {value}")
    return path.resolve()

def native_root() -> Path:
    override = os.environ.get("CAD_MCP_NATIVE_ROOT", "").strip()
    if override:
        return absolute_directory(override, "CAD_MCP_NATIVE_ROOT")
    roaming = os.environ.get("APPDATA", "").strip()
    base = absolute_directory(roaming, "APPDATA") if roaming else Path.home() / "AppData" / "Roaming"
    return base / "Autodesk" / "ApplicationPlugins"

def native_relative(name: str) -> Path:
    if name not in NATIVE_MODULES:
        raise ValueError(f"Unknown native module: {name}")
    return Path(name + ".bundle") / "Contents" / "Win64" / (name + ".dll")

def native_dll(name: str) -> Path:
    return native_root() / native_relative(name)

def native_payload_root() -> Path:
    # A built wheel owns its payload under the interpreter's installation prefix.
    installed = Path(sys.prefix) / "share" / "cad-mcp" / "native"
    source = Path(__file__).resolve().parent.parent / "native"
    for root in (installed, source):
        if all((root / native_relative(n)).is_file() for n in NATIVE_MODULES):
            return root
    raise FileNotFoundError("Native payload missing; reinstall this repository's wheel (not the upstream package)")

def system_directories() -> list[Path]:
    if os.name != "nt":
        return [Path(p) for p in ("/etc", "/usr", "/bin", "/sbin", "/boot", "/sys", "/proc")]
    drive = os.environ.get("SystemDrive", "C:") + "/"
    values = [os.environ.get("SystemRoot") or os.environ.get("WINDIR") or str(Path(drive) / "Windows")]
    for name, fallback in (("ProgramW6432", "Program Files"), ("ProgramFiles", "Program Files"), ("ProgramFiles(x86)", "Program Files (x86)")):
        values.append(os.environ.get(name) or str(Path(drive) / fallback))
    return list(dict.fromkeys(Path(v).resolve() for v in values))
