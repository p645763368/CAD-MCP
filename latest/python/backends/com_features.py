"""Validated COM geometry adapters and an in-process AutoCAD 2026 .NET bridge.

No DXF export/import. Geometry is computed in memory; native operations execute
inside a transaction. Unsupported projections/types are refused explicitly.
"""
import json, math, time
from pathlib import Path
from collections import Counter
import ezdxf
from ezdxf import edgeminer, edgesmith
from ezdxf.math import has_clockwise_orientation
from ezdxf.revcloud import REQUIRED_BULGE, REVCLOUD_PROPS
from engineering.measure import is_self_intersecting, polygon_area_perimeter

from cad_mcp_paths import native_dll
DLL = native_dll('CadMcpNative2026')
VERSION='1.0.0'

def vertices(points,closed=True):
    pts=[(float(p[0]),float(p[1])) for p in points]
    if len(pts)>1 and pts[0]==pts[-1]:pts.pop()
    if len(pts)<(3 if closed else 2):raise ValueError('Not enough distinct vertices')
    if not all(math.isfinite(v) for p in pts for v in p):raise ValueError('Nonfinite coordinates')
    if len(set(pts))!=len(pts):raise ValueError('Duplicate vertices')
    if closed and is_self_intersecting(pts) is None:raise ValueError('Polygon too complex to validate for self-intersection')
    if closed and (abs(polygon_area_perimeter([(*p,0.0) for p in pts],True)[0])<1e-12 or is_self_intersecting(pts)):
        raise ValueError('Boundary must be simple and have nonzero area')
    return pts

def create_polyline(rows,closed,layer=None,cloud_length=None):
    from . import com_backend as com
    if closed:
        if abs(polygon_area_perimeter(rows,True)[0])<1e-12:raise ValueError('Closed polyline has zero area')
        if all(abs(p[2])<1e-12 for p in rows) and is_self_intersecting([(p[0],p[1]) for p in rows]) is not False:
            raise ValueError('Closed linear boundary is self-crossing or too complex to validate')
    doc=com._acad_doc()
    if layer:doc.Layers.Item(layer)  # fail before creating anything
    e=com._com_unnarrow(doc.ModelSpace.AddLightWeightPolyline(com._av([v for p in rows for v in p[:2]])))
    try:
        for i,(_,_,b) in enumerate(rows):e.SetBulge(i,float(b))
        e.Closed=bool(closed)
        if layer:e.Layer=layer
        if cloud_length is not None:
            apps=doc.RegisteredApplications
            if not any(str(apps.Item(i).Name).lower()==REVCLOUD_PROPS.lower() for i in range(apps.Count)):apps.Add(REVCLOUD_PROPS)
            e.SetXData(com._ai([1001,1070,1040]),com._avar([REVCLOUD_PROPS,0,float(cloud_length)]))
        e.Update()
        return {'ok':True,'handle':str(e.Handle),'vertices':len(rows),'closed':bool(e.Closed),
                'area':float(e.Area) if closed else None,'layer':str(e.Layer)}
    except Exception:
        e.Delete();raise

def cloud(points,segment_length,layer=None,closed=True):
    pts=vertices(points,closed);length=float(segment_length)
    if not math.isfinite(length) or length<1e-6:raise ValueError('segment_length must be finite and >= 1e-6')
    pairs=list(zip(pts,pts[1:]+([pts[0]] if closed else [])))
    if length>min(math.dist(a,b) for a,b in pairs):raise ValueError('segment_length exceeds shortest edge')
    bulge=-REQUIRED_BULGE if closed and has_clockwise_orientation(pts) else REQUIRED_BULGE
    rows=[]
    for a,b in pairs:
        n=math.ceil(math.dist(a,b)/length)
        if n+len(rows)>10000:raise ValueError('Revision cloud exceeds 10000 segments')
        rows.extend((a[0]+(b[0]-a[0])*i/n,a[1]+(b[1]-a[1])*i/n,bulge) for i in range(n))
    if not closed:rows.append((*pts[-1],0.0))
    result=create_polyline(rows,closed,layer,length)
    result.update(segments=len(rows) if closed else len(rows)-1,segment_length=length,representation='LWPOLYLINE_with_RevcloudProps')
    return result

def boundary(handles,tolerance=1e-9):
    from . import com_backend as com
    from .ezdxf_backend import EzdxfBackend
    from engineering.understand.com_snapshot import record
    tol=float(tolerance)
    if not math.isfinite(tol) or tol<=0:raise ValueError('tolerance must be finite and positive')
    if not handles or len(handles)>200 or len(set(handles))!=len(handles):raise ValueError('Provide 1-200 unique handles')
    handles=[str(h).strip().upper() for h in handles]
    if len(set(handles))!=len(handles):raise ValueError('Duplicate handles')
    doc=com._acad_doc();memory=ezdxf.new();space=memory.modelspace();entities=[]
    for h in handles:
        e=com._com_unnarrow(doc.HandleToObject(str(h)))
        if int(e.OwnerID)!=int(doc.ModelSpace.ObjectID):raise ValueError('Boundary sources must be in model space')
        if e.ObjectName not in ('AcDbLine','AcDbArc','AcDbCircle','AcDbPolyline','AcDbLWPolyline','AcDb2dPolyline'):
            raise ValueError(f'{h}: only planar LINE/ARC/CIRCLE/POLYLINE sources are supported')
        r=record(e,'Model',com,Counter())
        if r.type=='LINE':
            if abs(e.StartPoint[2])>tol or abs(e.EndPoint[2])>tol:raise ValueError('Boundary sources must lie in WCS XY at z=0')
            item=space.add_line(*r.points)
        elif r.type in ('ARC','CIRCLE'):
            if abs(e.Center[2])>tol:raise ValueError('Boundary sources must lie in WCS XY at z=0')
            if r.type=='CIRCLE':
                if len(handles)!=1:raise ValueError('A closed circle cannot be chained with other sources into one loop')
                x,y=r.points[0];radius=r.radius
                return create_polyline([(x-radius,y,1.0),(x+radius,y,1.0)],True)
            item=space.add_arc(r.points[0],r.radius,*r.angles)
        else:
            if abs(e.Elevation)>tol:raise ValueError('Boundary sources must lie in WCS XY at z=0')
            item=space.add_lwpolyline([(*p,b) for p,b in zip(r.points,r.bulges)],format='xyb',close=r.closed)
            if len(handles)==1 and r.closed:
                return create_polyline([(*p,b) for p,b in zip(r.points,r.bulges)],True)
        entities.append(item)
    edges=[]
    for item in entities:
        part=list(edgesmith.edges_from_entities_2d([item]))
        if not part:raise ValueError('A source is closed or cannot be chained; no input may be silently ignored')
        edges.extend(part)
    if not edges:raise ValueError('No chainable planar edges')
    chain=edgeminer.find_loop(edgeminer.Deposit(edges,gap_tol=max(tol,1e-9)),timeout=5)
    if not chain or len(chain)!=len(edges):raise ValueError('Sources do not form one closed loop; gap, branching, or multiple loops')
    poly,verts=EzdxfBackend._chain_to_polyline(space,chain,tol)
    result=create_polyline([(x,y,b) for x,y,b in poly.get_points('xyb')],True)
    result['source_handles']=list(handles)
    return result

def native_call(backend,op,**args):
    from . import com_backend as com
    doc=com._acad_doc()
    if int(doc.GetVariable('CMDACTIVE')):raise RuntimeError('AutoCAD has an active command; finish/cancel it first')
    if not DLL.is_file():raise RuntimeError(f'Native bridge missing: {DLL}')
    from config import settings
    call_deadline=time.monotonic()+max(1.0,settings.com_call_timeout-20.0)
    if op=='chspace':
        for h in args.get('handles',[]):
            ent=com._com_unnarrow(doc.HandleToObject(str(h)))
            if ent.ObjectName=='AcDbBlockReference' and ent.HasAttributes:
                raise ValueError('Blocks with attributes are not yet supported by space transfer')
    saved=doc.GetVariable('USERS5');filedia=doc.GetVariable('FILEDIA')
    try:
        # Verify transport capacity BEFORE any geometric mutation.
        doc.SetVariable('USERS5','x'*8192)
        if len(doc.GetVariable('USERS5'))!=8192:raise RuntimeError('USERS5 transport is too short')
        doc.SetVariable('FILEDIA',0)
        def invoke(expr):
            marker='MCP_PENDING_'+__import__('uuid').uuid4().hex
            doc.SetVariable('USERS5',marker)
            doc.SendCommand(f'(setvar "USERS5" {expr})\n')
            deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                value=str(doc.GetVariable('USERS5'))
                if value!=marker:return value
                time.sleep(.05)
            raise RuntimeError('Native bridge response timed out; inspect document before retrying')
        test=invoke('(if (member "MCPNATIVE2026" (atoms-family 1)) "loaded" "missing")')
        if test=='missing':
            doc.SendCommand(f'(command "_.NETLOAD" {json.dumps(str(DLL).replace(chr(92),"/"))})\n')
            # Do not alter SECURELOAD/TRUSTEDPATHS; AutoCAD may request approval for this user-installed DLL.
            test=invoke('(if (member "MCPNATIVE2026" (atoms-family 1)) "loaded" "missing")')
            if test!='loaded':raise RuntimeError('Native bridge did not load; inspect AutoCAD load/security message')
        def dispatch(payload):return json.loads(invoke('(car (MCPNATIVE2026 '+json.dumps(json.dumps(payload,ensure_ascii=True,separators=(',',':')))+'))'))
        ping=dispatch({'op':'ping'})
        if ping.get('version')!=VERSION:raise RuntimeError('Native bridge version mismatch; restart AutoCAD to load installed version')
        if time.monotonic()>call_deadline:raise RuntimeError('Native load exceeded its budget; no geometric operation was dispatched. Retry only after load completes.')
        payload=dict(op=op,document=str(doc.FullName),**args)
        result=dispatch(payload)
        if not result.get('ok'):raise ValueError(result.get('error','Native operation failed'))
        result['backend']='com_native_bridge';return result
    finally:
        doc.SetVariable('FILEDIA',filedia)
        doc.SetVariable('USERS5',saved)
