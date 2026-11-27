"""Frozen drawing records for analysis.

COM uses a read-only ActiveX traversal of already-open drawings. It never
exports temporary DXFs. Headless DXFs still use ezdxf with the size guard.
See com_snapshot.py and Snapshot.read_metadata for live-reader limitations.
"""

from __future__ import annotations

import asyncio
import math
import os
from dataclasses import dataclass, field
from pathlib import Path

import ezdxf
from ezdxf import bbox as ezbbox

import config
from backends.capability import UnsupportedCapabilityError
from backends.ocs import to_wcs_2d, wcs_arc_angles, wcs_bulge
from engineering.measure import polygon_area_perimeter
from engineering.understand.labels import plain

__all__ = [
    "EntityRecord",
    "Pt",
    "Snapshot",
    "length_of",
    "read_snapshot",
    "records_from_doc",
    "take_snapshot",
]

Pt = tuple[float, float]

#: ezdxf's placeholder for an extents header nobody computed.
_UNSET_EXTENT = 1e19
#: The live export's base name inside its temporary folder.
_SNAP_BASE = "snap"


@dataclass(frozen=True)
class EntityRecord:
    """One entity of a layout, in WCS, as the readers need it."""

    handle: str
    type: str
    layer: str
    space: str
    points: tuple[Pt, ...] = ()
    bulges: tuple[float, ...] = ()
    closed: bool = False
    radius: float | None = None
    angles: tuple[float, float] | None = None
    text: str | None = None
    height: float | None = None
    block: str | None = None
    attribs: tuple[tuple[str, str], ...] = ()
    bbox: tuple[float, float, float, float] | None = None
    rotation: float = 0.0
    scale: tuple[float, float] = (1.0, 1.0)


@dataclass(frozen=True)
class Snapshot:
    """A whole drawing, read once."""

    source: str
    insunits: int
    extmin: Pt | None
    extmax: Pt | None
    layers: dict[str, dict]
    layouts: tuple[str, ...]
    records: tuple[EntityRecord, ...]
    read_metadata: dict = field(default_factory=dict)


def _xy(point) -> Pt:
    return (float(point[0]), float(point[1]))


def _box(entity) -> tuple[float, float, float, float] | None:
    """The entity's WCS box. An INSERT's box is its block geometry only: the
    ATTRIB texts are left out, because a TAG lettered beside a tank would push
    the tank's box past its body (the rule `engineering/pid/graph.py` keeps)."""
    try:
        if entity.dxftype() == "INSERT":
            box = ezbbox.extents(entity.virtual_entities(), fast=True)
        else:
            box = ezbbox.extents([entity], fast=True)
    except Exception:  # a proxy or a malformed entity has no box; the record stays
        return None
    if not box.has_data:
        return None
    return (
        float(box.extmin.x),
        float(box.extmin.y),
        float(box.extmax.x),
        float(box.extmax.y),
    )


def _header_point(doc, name: str) -> Pt | None:
    try:
        value = doc.header.get(name)
    except Exception:
        return None
    if value is None or abs(float(value[0])) >= _UNSET_EXTENT:
        return None
    return _xy(value)


def _extrusion(entity):
    """The entity's extrusion, or +Z for a type that has none (MULTILEADER, ...)."""
    if entity.dxf.is_supported("extrusion"):
        return entity.dxf.get("extrusion", (0.0, 0.0, 1.0))
    return (0.0, 0.0, 1.0)


def _polyline(entity) -> tuple[tuple[Pt, ...], tuple[float, ...], bool]:
    extrusion = _extrusion(entity)
    if entity.dxftype() == "LWPOLYLINE":
        elevation = float(entity.dxf.get("elevation", 0.0))
        rows = [(float(x), float(y), float(b)) for x, y, b in entity.get_points("xyb")]
        points = tuple(tuple(to_wcs_2d(extrusion, x, y, elevation)) for x, y, _ in rows)
        bulges = tuple(wcs_bulge(extrusion, b) for _, _, b in rows)
        return points, bulges, bool(entity.closed)
    vertices = list(entity.vertices)
    if entity.is_2d_polyline:
        points = tuple(
            tuple(to_wcs_2d(extrusion, v.dxf.location.x, v.dxf.location.y, v.dxf.location.z))
            for v in vertices
        )
        bulges = tuple(wcs_bulge(extrusion, v.dxf.get("bulge", 0.0)) for v in vertices)
    else:  # a 3D polyline is WCS already; its z is dropped
        points = tuple(_xy(v.dxf.location) for v in vertices)
        bulges = tuple(0.0 for _ in vertices)
    return points, bulges, bool(entity.is_closed)


def _record(entity, space: str) -> EntityRecord | None:
    kind = entity.dxftype()
    dxf = entity.dxf
    base = {
        "handle": str(dxf.handle),
        "type": kind,
        "layer": str(dxf.get("layer", "0")),
        "space": space,
        "bbox": _box(entity),
    }
    extrusion = _extrusion(entity)
    if kind == "LINE":
        return EntityRecord(**base, points=(_xy(dxf.start), _xy(dxf.end)))
    if kind in ("LWPOLYLINE", "POLYLINE"):
        if kind == "POLYLINE" and (entity.is_poly_face_mesh or entity.is_polygon_mesh):
            return EntityRecord(**base)
        points, bulges, closed = _polyline(entity)
        return EntityRecord(**base, points=points, bulges=bulges, closed=closed)
    if kind in ("ARC", "CIRCLE"):
        centre = tuple(to_wcs_2d(extrusion, dxf.center.x, dxf.center.y, dxf.center.z))
        angles = None
        if kind == "ARC":
            angles = wcs_arc_angles(
                extrusion, dxf.center, dxf.radius, dxf.start_angle, dxf.end_angle
            )
        return EntityRecord(**base, points=(centre,), radius=float(dxf.radius), angles=angles)
    if kind == "TEXT":
        insert = dxf.insert
        return EntityRecord(
            **base,
            points=(tuple(to_wcs_2d(extrusion, insert.x, insert.y, insert.z)),),
            text=plain(dxf.get("text", "")),
            height=float(dxf.get("height", 0.0)),
            rotation=float(dxf.get("rotation", 0.0)),
        )
    if kind == "MTEXT":
        return EntityRecord(
            **base,
            points=(_xy(dxf.insert),),
            text=plain(entity.text),
            height=float(dxf.get("char_height", 0.0)),
            rotation=float(entity.get_rotation()),
        )
    if kind == "INSERT":
        insert = dxf.insert
        attribs = tuple((str(a.dxf.tag), plain(a.dxf.get("text", ""))) for a in entity.attribs)
        return EntityRecord(
            **base,
            points=(tuple(to_wcs_2d(extrusion, insert.x, insert.y, insert.z)),),
            block=str(dxf.name),
            attribs=attribs,
            rotation=float(dxf.get("rotation", 0.0)),
            scale=(float(dxf.get("xscale", 1.0)), float(dxf.get("yscale", 1.0))),
        )
    if kind == "MULTILEADER":
        context = entity.context
        points: list[Pt] = []
        for leader in context.leaders:
            for line in leader.lines:
                points.extend(_xy(v) for v in line.vertices)
            points.append(_xy(leader.last_leader_point))
        text = None
        height = None
        if context.mtext is not None:
            text = plain(context.mtext.default_content)
            points.append(_xy(context.mtext.insert))
            height = float(context.char_height)
        return EntityRecord(**base, points=tuple(points), text=text, height=height)
    if kind == "DIMENSION":
        override = str(dxf.get("text", "") or "")
        text = plain(override) if override not in ("", "<>") else None
        middle = dxf.get("text_midpoint", dxf.defpoint)
        points = (_xy(dxf.defpoint), tuple(to_wcs_2d(extrusion, middle.x, middle.y, middle.z)))
        return EntityRecord(**base, points=points, text=text)
    if kind == "LEADER":
        return EntityRecord(**base, points=tuple(_xy(v) for v in entity.vertices))
    if kind == "POINT":
        return EntityRecord(**base, points=(_xy(dxf.location),))
    if kind == "SPLINE":
        return EntityRecord(**base, points=tuple(_xy(p) for p in entity.control_points))
    if kind == "ELLIPSE":
        return EntityRecord(**base, points=(_xy(dxf.center),))
    return EntityRecord(**base)


def records_from_doc(doc, *, source: str) -> Snapshot:
    """Every entity of every layout of an ``ezdxf`` document, as records.

    Model space first, then each paper layout in tab order. ``insunits`` is
    ``$INSUNITS`` (0 when absent); ``extmin`` / ``extmax`` are the declared
    ``$EXTMIN`` / ``$EXTMAX``, None when the header holds ezdxf's "never
    computed" placeholder. Nothing in ``doc`` is modified.
    """
    records: list[EntityRecord] = []
    layouts = tuple(doc.layouts.names_in_taborder())
    for name in layouts:
        for entity in doc.layouts.get(name):
            record = _record(entity, name)
            if record is not None:
                records.append(record)
    layers = {
        str(layer.dxf.name): {
            "color": int(layer.dxf.get("color", 7)),
            "linetype": str(layer.dxf.get("linetype", "Continuous")),
        }
        for layer in doc.layers
    }
    return Snapshot(
        source=source,
        insunits=int(doc.header.get("$INSUNITS", 0) or 0),
        extmin=_header_point(doc, "$EXTMIN"),
        extmax=_header_point(doc, "$EXTMAX"),
        layers=layers,
        layouts=layouts,
        records=tuple(records),
    )


def _read(path: str, *, source: str) -> Snapshot:
    # Every parse or walk failure is one refusal. A truncated file makes ezdxf's
    # tag reader raise StopIteration, which asyncio.to_thread cannot hand back to
    # an awaiting tool - uncaught, the tool would never answer.
    try:
        return records_from_doc(ezdxf.readfile(path), source=source)
    except MemoryError:
        raise
    except Exception as exc:  # noqa: BLE001 - see above
        reason = str(exc) or type(exc).__name__
        raise ValueError(f"{path} is not a readable DXF file: {reason}") from exc


def read_snapshot(path: str) -> Snapshot:
    """The snapshot of a DXF file on disk, after the size check.

    Refuses a missing file (``FileNotFoundError``) and a file larger than
    ``MAX_DXF_BYTES`` (``ValueError`` naming the size, the limit and the
    variable; 0 disables the check) before reading a byte of it.
    """
    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(f"{path}: no such file")
    limit = int(config.settings.max_dxf_bytes)
    size = target.stat().st_size
    if limit > 0 and size > limit:
        raise ValueError(
            f"{path} is {size:,} bytes ({size / 2**20:.1f} MB), over the MAX_DXF_BYTES "
            f"limit of {limit:,} bytes ({limit / 2**20:.0f} MB). Raise MAX_DXF_BYTES "
            "(0 disables the check) to read it."
        )
    return _read(str(target), source=str(target))


def _already_open(app, path: str):
    """The document AutoCAD already has open at ``path``, or None. Opens nothing."""
    wanted = os.path.normcase(os.path.abspath(path))
    documents = app.Documents
    for index in range(int(documents.Count)):
        doc = documents.Item(index)
        try:
            full = str(doc.FullName or "")
        except Exception:  # a document closing under us answers nothing; it is not ours
            continue
        if full and os.path.normcase(os.path.abspath(full)) == wanted:
            return doc
    return None


async def take_snapshot(backend, path: str | None = None) -> Snapshot:
    """COM reads already-open documents directly, without exports or disk parsing.

    Explicit COM paths must identify open DWG/DXF documents; unsaved in-memory
    edits are included. Headless DXF reading retains its existing size guard.
    """
    if path is not None and Path(path).suffix.lower() not in (".dwg", ".dxf"):
        raise ValueError(f"{path}: a snapshot reads a .dxf or a .dwg")
    if backend.name == "com":
        from engineering.understand.com_snapshot import read_open_document
        return await backend._run(read_open_document, backend, path)
    if path is not None:
        if Path(path).suffix.lower() == ".dxf":
            return await asyncio.to_thread(read_snapshot, str(path))
        raise UnsupportedCapabilityError("dwg", "Open this DWG in AutoCAD and use the COM backend.")
    source = backend._doc_path or "memory:untitled"
    return await backend._async(lambda: records_from_doc(backend._doc, source=source))


def length_of(rec: EntityRecord) -> float:
    """Drawn length in drawing units: LINE, LWPOLYLINE / POLYLINE with their
    bulges (``engineering.measure``, the same arithmetic ``analysis_measure_entity``
    reports), ARC, CIRCLE. Every other type is 0.0.
    """
    if rec.type == "LINE" and len(rec.points) == 2:
        return math.dist(rec.points[0], rec.points[1])
    if rec.type in ("LWPOLYLINE", "POLYLINE") and len(rec.points) >= 2:
        bulges = rec.bulges or tuple(0.0 for _ in rec.points)
        vertices = [(x, y, b) for (x, y), b in zip(rec.points, bulges, strict=False)]
        return polygon_area_perimeter(vertices, rec.closed)[1]
    if rec.type == "ARC" and rec.radius is not None and rec.angles is not None:
        sweep = (rec.angles[1] - rec.angles[0]) % 360.0
        return rec.radius * math.radians(sweep)
    if rec.type == "CIRCLE" and rec.radius is not None:
        return 2.0 * math.pi * rec.radius
    return 0.0
