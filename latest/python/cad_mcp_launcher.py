"""Installed STDIO/HTTP entry point. Explicit environment settings take priority."""
import os
import sys

def defaults() -> None:
    values = {
        "AUTOCAD_MCP_BACKEND": "com" if sys.platform == "win32" else "ezdxf",
        "CAD_PROGID": "AutoCAD.Application.25.1",
        "TOOL_PROFILE": "full", "TOOL_PACKS": "all", "DISCOVERY_MODE": "search",
        "DISABLED_TOOLS": "drawing_deliver,drawing_finalize,validation_check",
        "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
    }
    for key, value in values.items():
        os.environ.setdefault(key, value)

def main() -> None:
    defaults()
    if not any(x in sys.argv for x in ("-h", "--help")) and not os.environ.get("ALLOWED_PATHS", "").strip():
        raise SystemExit("Set ALLOWED_PATHS to your drawing workspace. Generate a client snippet with autocad-mcp-config --workspace <absolute-directory>.")
    from server import main as serve
    serve()

if __name__ == "__main__":
    main()
