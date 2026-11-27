"""Install native payloads, generate private client snippets, and diagnose offline.

Never opens AutoCAD, loads a DLL, edits a registry key, or rewrites a client config.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from cad_mcp_paths import BUILD_ID, NATIVE_MODULES, absolute_directory, native_relative, native_root, native_payload_root
from version import __version__

def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def install_native(destination: Path | None = None, dry_run: bool = False) -> list[dict]:
    root = (destination or native_root()).resolve()
    source = native_payload_root()
    jobs = []
    # Validate all payloads before writing any destination.
    for name in NATIVE_MODULES:
        data = (source / native_relative(name)).read_bytes()
        if not data.startswith(b"MZ"):
            raise ValueError(f"{name}: payload is not a readable Windows DLL")
        target = root / native_relative(name)
        if not target.resolve().is_relative_to(root):
            raise ValueError("Native destination escaped requested root")
        same = target.is_file() and target.read_bytes() == data
        jobs.append((name, data, target, same))
    # The UI bundle has a manifest so the status ribbon returns at CAD startup.
    relative = Path("CadMcpStatus2026.bundle/PackageContents.xml")
    data = (source / relative).read_bytes()
    root_element = ET.fromstring(data)
    if root_element.tag != "ApplicationPackage":
        raise ValueError("Invalid CAD-MCP status manifest")
    target = root / relative
    jobs.append(("CadMcpStatus2026 manifest", data, target, target.is_file() and target.read_bytes() == data))
    result = []
    for name, data, target, same in jobs:
        status = "unchanged" if same else "would_install" if dry_run else "installed"
        if not same and not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = None
            try:
                with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".tmp", delete=False) as stream:
                    tmp = Path(stream.name)
                    stream.write(data)
                os.replace(tmp, target)
                if target.read_bytes() != data:
                    raise OSError(f"Readback mismatch: {target}")
            except PermissionError as exc:
                raise PermissionError(f"Cannot replace {target}; close AutoCAD if this DLL is loaded, then retry. No safety setting was changed.") from exc
            finally:
                if tmp is not None and tmp.exists():
                    tmp.unlink()
        result.append({"module": name, "path": str(target), "sha256": digest(data), "status": status})
    return result

def install_main() -> None:
    parser = argparse.ArgumentParser(description="Install native bridges and status ribbon; no CAD launch/NETLOAD/registry edits")
    parser.add_argument("--destination", help="Absolute ApplicationPlugins root; default APPDATA/Autodesk/ApplicationPlugins")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    dest = absolute_directory(args.destination, "destination") if args.destination else None
    print(json.dumps(install_native(dest, args.dry_run), ensure_ascii=False, indent=2))

def client_config(workspaces: list[str], backend: str = "com", plugin_root: str | None = None) -> dict:
    paths = [absolute_directory(p, "workspace") for p in workspaces]
    if not paths or any("," in str(p) for p in paths):
        raise ValueError("At least one workspace is required; comma-containing paths are unsupported by ALLOWED_PATHS")
    command = Path(sys.executable).parent / ("autocad-mcp.exe" if os.name == "nt" else "autocad-mcp")
    env = {"AUTOCAD_MCP_BACKEND": backend, "CAD_PROGID": "AutoCAD.Application.25.1",
           "ALLOWED_PATHS": ",".join(map(str, paths)), "TOOL_PROFILE": "full", "TOOL_PACKS": "all",
           "DISCOVERY_MODE": "search", "DISABLED_TOOLS": "drawing_deliver,drawing_finalize,validation_check",
           "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    if plugin_root:
        env["CAD_MCP_NATIVE_ROOT"] = str(absolute_directory(plugin_root, "native root"))
    return {"mcp_servers": {"autocad-mcp": {"command": str(command), "startup_timeout_sec": 120, "env": env}}}

def config_main() -> None:
    parser = argparse.ArgumentParser(description="Print a CAD-only client config; does not edit any client file")
    parser.add_argument("--workspace", action="append", required=True)
    parser.add_argument("--backend", choices=["com", "ezdxf"], default="com")
    parser.add_argument("--native-root")
    parser.add_argument("--format", choices=["toml", "json"], default="toml")
    args = parser.parse_args()
    result = client_config(args.workspace, args.backend, args.native_root)
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    config = result["mcp_servers"]["autocad-mcp"]
    print('[mcp_servers."autocad-mcp"]')
    print("command = " + json.dumps(config["command"], ensure_ascii=False))
    print("startup_timeout_sec = 120\n\n[mcp_servers.\"autocad-mcp\".env]")
    for key, value in config["env"].items():
        print(key + " = " + json.dumps(value, ensure_ascii=False))

def doctor_main() -> None:
    parser = argparse.ArgumentParser(description="Offline installation diagnostics; never attaches to AutoCAD")
    parser.add_argument("--require-native", action="store_true")
    args = parser.parse_args()
    source = native_payload_root()
    modules = []
    for name in NATIVE_MODULES:
        expected = (source / native_relative(name)).read_bytes()
        installed = native_root() / native_relative(name)
        modules.append({"name": name, "path": str(installed), "payload_readable": expected.startswith(b"MZ"),
                        "installed_matches": installed.is_file() and installed.read_bytes() == expected})
    relative = Path("CadMcpStatus2026.bundle/PackageContents.xml")
    manifest = native_root() / relative
    manifest_matches = manifest.is_file() and manifest.read_bytes() == (source / relative).read_bytes()
    core = all(m["payload_readable"] for m in modules)
    print(json.dumps({"version": __version__, "build": BUILD_ID, "python": sys.executable,
                      "native_root": str(native_root()), "modules": modules, "status_manifest_matches": manifest_matches, "autocad_contacted": False}, ensure_ascii=False, indent=2))
    if not core or (args.require_native and (not manifest_matches or not all(m["installed_matches"] for m in modules))):
        raise SystemExit(1)
