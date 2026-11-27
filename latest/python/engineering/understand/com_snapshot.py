"""Read already-open AutoCAD documents through ActiveX; no export or file parsing.

COM objects stay on the backend STA. Plain immutable records cross its boundary.
Unsupported detail and approximate block boxes are disclosed in read_metadata.
No document activation, opening, saving, exploding, or selection-set mutation.
"""
from __future__ import annotations

import math
from collections import Counter

from backends.ocs import to_wcs_2d, wcs_bulge, is_flat_frame
from engineering.understand.labels import plain
from engineering.understand.snapshot import EntityRecord, Snapshot, _already_open


def xy(p):
    return float(p[0]), float(p[1])


def triples(values):
    values = list(values)
    if len(values) % 3:
        raise ValueError('coordinate array is not a sequence of triples')
    return tuple((float(values[i]), float(values[i + 1])) for i in range(0, len(values), 3))


def record(entity, space, com, notes):
    e = com._com_unnarrow(entity)
    name = str(e.ObjectName)
    kind = name.removeprefix('AcDb').upper()
    kind = {'POLYLINE':'LWPOLYLINE', 'LWPOLYLINE':'LWPOLYLINE',
            '2DPOLYLINE':'POLYLINE', '3DPOLYLINE':'POLYLINE',
            'BLOCKREFERENCE':'INSERT', 'MINSERTBLOCK':'INSERT',
            'MLEADER':'MULTILEADER'}.get(kind, kind)
    if 'DIMENSION' in kind:
        kind = 'DIMENSION'
    base = dict(handle=str(e.Handle), type=kind, layer=str(e.Layer), space=space)
    box = None
    if kind == 'INSERT':
        b = com._com_geometry_bbox(e)
        if b:
            box = (*xy(b['min']), *xy(b['max']))
            if b.get('approximate'):
                notes['approximate_insert_bbox'] += 1
        else:
            notes['insert_geometry_bbox_unavailable'] += 1
    else:
        try:
            lo, hi = e.GetBoundingBox()
            box = (*xy(lo), *xy(hi))
        except Exception:
            notes['bbox_unavailable:'+kind] += 1
    base['bbox'] = box
    if kind == 'LINE':
        return EntityRecord(**base, points=(xy(e.StartPoint), xy(e.EndPoint)))
    if name in ('AcDbPolyline', 'AcDbLWPolyline', 'AcDb2dPolyline'):
        normal = tuple(e.Normal)
        if not is_flat_frame(normal):
            raise ValueError('tilted polyline cannot be represented as an exact XY snapshot')
        coords = list(e.Coordinates)
        stride = 3 if name == 'AcDb2dPolyline' else 2
        if len(coords) % stride:
            raise ValueError('invalid polyline coordinate stride')
        elevation = float(e.Elevation)
        pts = tuple(tuple(to_wcs_2d(normal,coords[i],coords[i+1],elevation))
                    for i in range(0,len(coords),stride))
        bs = tuple(wcs_bulge(normal,float(e.GetBulge(i))) for i in range(len(pts)))
        return EntityRecord(**base,points=pts,bulges=bs,closed=bool(e.Closed))
    if name == 'AcDb3dPolyline':
        pts = triples(e.Coordinates)
        notes['3d_polyline_projected_to_xy'] += 1
        return EntityRecord(**base,points=pts,bulges=(0.0,)*len(pts),closed=bool(e.Closed))
    if kind in ('ARC','CIRCLE'):
        normal = tuple(e.Normal)
        if not is_flat_frame(normal):
            raise ValueError('tilted circle/arc cannot be represented as an exact XY snapshot')
        center = xy(e.Center)  # ActiveX point properties are WCS.
        angles = None
        if kind == 'ARC':
            angles = tuple(math.degrees(math.atan2(p[1]-center[1],p[0]-center[0])) % 360
                           for p in (e.StartPoint,e.EndPoint))
            if normal[2] < 0:
                angles = angles[::-1]
        return EntityRecord(**base,points=(center,),radius=float(e.Radius),angles=angles)
    if kind in ('TEXT','MTEXT'):
        return EntityRecord(**base,points=(xy(e.InsertionPoint),),text=plain(str(e.TextString)),
                            height=float(e.Height),rotation=math.degrees(float(e.Rotation)))
    if kind == 'INSERT':
        attrs = []
        if bool(e.HasAttributes):
            for a in e.GetAttributes():
                a = com._com_unnarrow(a)
                attrs.append((str(a.TagString),plain(str(a.TextString))))
        normal = tuple(e.Normal)
        if not is_flat_frame(normal):
            raise ValueError('tilted INSERT is not supported by the XY reader')
        if normal[2] < 0:
            notes['mirrored_insert_bbox_may_be_approximate'] += 1
        if name == 'AcDbMInsertBlock':
            notes['minsert_array_not_expanded'] += 1
        return EntityRecord(**base,points=(xy(e.InsertionPoint),),block=str(e.Name),
                            attribs=tuple(attrs),rotation=math.degrees(float(e.Rotation)),
                            scale=(float(e.XScaleFactor),float(e.YScaleFactor)))
    if kind == 'DIMENSION':
        text = str(e.TextOverride or '')
        notes['dimension_definition_point_not_exposed'] += 1
        return EntityRecord(**base,points=(xy(e.TextPosition),),
                            text=plain(text) if text not in ('','<>') else None)
    if kind == 'MULTILEADER':
        # Text is useful to the label reader; the ActiveX leader graph differs
        # between versions, so do not fabricate line vertices from its bbox.
        notes['multileader_vertices_not_read'] += 1
        try:
            text = plain(str(e.TextString))
            height = float(e.TextHeight)
        except Exception:
            text, height = None, None
            notes['multileader_text_unavailable'] += 1
        return EntityRecord(**base,text=text,height=height)
    if kind == 'LEADER':
        return EntityRecord(**base,points=triples(e.Coordinates))
    if kind == 'POINT':
        return EntityRecord(**base,points=(xy(e.Coordinates),))
    if kind == 'ELLIPSE':
        return EntityRecord(**base,points=(xy(e.Center),))
    if kind == 'SPLINE':
        return EntityRecord(**base,points=triples(e.ControlPoints))
    notes['bbox_only:'+kind] += 1
    return EntityRecord(**base)


def read_open_document(backend, path=None):
    from backends import com_backend as com
    app = com._acad_app()
    doc = com._acad_doc() if path is None else _already_open(app,str(path))
    if doc is None:
        raise ValueError(f'{path}: COM direct reading requires this drawing to be already open in AutoCAD; open it first. No file export or automatic opening was attempted.')
    before = (str(doc.FullName),bool(doc.Saved),int(doc.ModelSpace.Count))
    notes = Counter()
    layouts = sorted((doc.Layouts.Item(i) for i in range(int(doc.Layouts.Count))),key=lambda l:int(l.TabOrder))
    records = []
    counts = {}
    for layout in layouts:
        space = str(layout.Name)
        entities = layout.Block
        count = int(entities.Count)
        counts[space] = count
        for i in range(count):
            entity = entities.Item(i)
            try:
                records.append(record(entity,space,com,notes))
            except Exception as exc:
                raise ValueError(f'COM snapshot {space}, entity {entity.Handle} ({entity.ObjectName}): {exc}') from exc
        if int(entities.Count) != count:
            raise RuntimeError('drawing changed during COM snapshot; retry after editing stops')
    layers = {}
    for i in range(int(doc.Layers.Count)):
        layer = doc.Layers.Item(i)
        layers[str(layer.Name)] = {'color':int(layer.color),'linetype':str(layer.Linetype)}
    after = (str(doc.FullName),bool(doc.Saved),int(doc.ModelSpace.Count))
    if after != before:
        raise RuntimeError('document name/save state/count changed during read; snapshot discarded')
    # Preserve the meaning of declared header extents. The analysis engine
    # computes geometry extents separately and can report a stale header.
    def header_point(name):
        value = doc.GetVariable(name)
        point = xy(value)
        return point if all(math.isfinite(v) and abs(v)<1e19 for v in point) else None
    lo, hi = header_point('EXTMIN'), header_point('EXTMAX')
    meta = {'mode':'com_direct','document':str(doc.Name),'path':str(doc.FullName),
            'temporary_dxf':False,'records':len(records),'layout_counts':counts,
            'limitations':dict(notes),'block_definitions_compared':False,
            'xref_contents_expanded':False}
    return Snapshot(source=f'live-com:{doc.Name}',insunits=int(doc.GetVariable('INSUNITS')),
                    extmin=lo,extmax=hi,layers=layers,layouts=tuple(str(l.Name) for l in layouts),
                    records=tuple(records),read_metadata=meta)
