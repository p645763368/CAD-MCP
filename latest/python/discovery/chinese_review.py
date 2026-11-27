"""Final Chinese contract review, applied after every endpoint replacement.

Only descriptions, discovery metadata and risk annotations change. JSON Schema
validation constraints and callable signatures remain owned by implementations.
"""
from pathlib import Path
import copy
import json
import re
from mcp.types import ToolAnnotations

REVISION = "2026-11-27.zh-review1"
PATCHES = json.loads(Path(__file__).with_suffix(".json").read_text(encoding="utf-8"))


def apply_review(tools, backend="com"):
    names = {tool.name for tool in tools}
    if names != set(PATCHES):
        raise ValueError(f"Chinese review mismatch: missing={names-set(PATCHES)}, extra={set(PATCHES)-names}")
    for tool in tools:
        patch = PATCHES[tool.name]
        schema = copy.deepcopy(tool.parameters)
        unknown = set(patch.get("parameters", {})) - set(schema.get("properties", {}))
        if unknown:
            raise ValueError(f"Stale reviewed parameters: {tool.name}: {unknown}")
        if backend == "com":
            for key, description in patch.get("parameters", {}).items():
                schema["properties"][key]["description"] = description
            tool.parameters = schema
            tool.description = patch.get("description", tool.description)
        meta = copy.deepcopy(tool.meta or {})
        cad = meta.setdefault("cad", {})
        risk = patch.get("risk", cad.get("risk", "write"))
        cad.update(summary=patch["summary"], risk=risk, catalog_revision=REVISION)
        if cad.get("cost") != "escape":
            cad["cost"] = {"read": "read", "write": "mutate", "destructive": "destructive"}[risk]
        cad["zh_aliases"] = list(dict.fromkeys([*patch.get("aliases", cad.get("zh_aliases", [])), patch["summary"]]))
        # The compact card and full tool must share current restrictions.
        if backend == "com":
            detail = re.sub(r"(?:风险|检索)：[^\n]*", "", tool.description).strip()
            cad["limits"] = detail.removeprefix(patch["summary"]).lstrip("。\n ")
        tool.meta = meta
        previous = tool.annotations.model_dump(exclude_none=True) if tool.annotations else {}
        previous.update(readOnlyHint=risk == "read", destructiveHint=risk == "destructive")
        if risk != "read":
            previous["idempotentHint"] = False
        tool.annotations = ToolAnnotations(**previous)
