"""Deterministic LINE/LINE planar corners; no interactive CAD commands."""
import math

def corner_plan(a0,a1,b0,b1,kind,size1,size2=None,trim=True):
    pts=[tuple(map(float,p)) for p in (a0,a1,b0,b1)]
    if any(len(p)!=3 or not all(math.isfinite(v) for v in p) for p in pts):
        raise ValueError('Corner coordinates must be finite XYZ points')
    a0,a1,b0,b1=pts
    la=math.dist(a0,a1);lb=math.dist(b0,b1);tol=max(1e-8,max(la,lb)*1e-9)
    if not math.isfinite(la) or not math.isfinite(lb):raise ValueError('Source coordinate magnitude is too large')
    if min(la,lb)<=tol:raise ValueError('Zero-length source line')
    if max(p[2] for p in pts)-min(p[2] for p in pts)>tol:
        raise ValueError('Source lines must lie in the same plane parallel to WCS XY')
    da=(a1[0]-a0[0],a1[1]-a0[1]);db=(b1[0]-b0[0],b1[1]-b0[1])
    cross=lambda a,b:a[0]*b[1]-a[1]*b[0]
    den=cross(da,db)
    if abs(den)<=la*lb*1e-10:raise ValueError('Parallel or collinear lines do not define a unique corner')
    q=(b0[0]-a0[0],b0[1]-a0[1]);t=cross(q,db)/den
    p=(a0[0]+t*da[0],a0[1]+t*da[1],a0[2])
    def ray(s,e):
        ds,de=math.dist(s,p),math.dist(e,p)
        # The public API has no pick locations: choose farther endpoint;
        # an equal-distance crossing deterministically chooses EndPoint.
        far,near_index=(s,1) if ds>de+tol else (e,0)
        length=math.dist(far,p)
        if length<=tol:raise ValueError('Degenerate corner ray')
        return ((far[0]-p[0])/length,(far[1]-p[1])/length),near_index,length
    u,ia,fa=ray(a0,a1);v,ib,fb=ray(b0,b1)
    theta=math.acos(max(-1.0,min(1.0,u[0]*v[0]+u[1]*v[1])))
    if theta<1e-8 or math.pi-theta<1e-8:raise ValueError('Near-parallel corner is numerically unstable')
    x=float(size1);y=float(x if size2 is None else size2)
    if not all(math.isfinite(n) for n in (x,y)):raise ValueError('Corner sizes must be finite')
    center=None;angles=None
    if kind=='fillet':
        if x<0:raise ValueError('Radius must be nonnegative')
        if x==0 and not trim:raise ValueError('Zero radius with trim=false performs no operation')
        ta=tb=x/math.tan(theta/2) if x else 0.0
    elif kind=='chamfer':
        if min(x,y)<=0:raise ValueError('Chamfer distances must be positive')
        ta,tb=x,y
    else:raise ValueError('Unknown corner operation')
    if ta>fa+tol or tb>fb+tol or trim and (ta>=fa-tol or tb>=fb-tol):
        raise ValueError('Corner size exceeds available rays or would consume a source line')
    t1=(p[0]+ta*u[0],p[1]+ta*u[1],p[2]);t2=(p[0]+tb*v[0],p[1]+tb*v[1],p[2])
    if kind=='fillet' and x:
        bis=(u[0]+v[0],u[1]+v[1]);bl=math.hypot(*bis)
        dist=x/math.sin(theta/2)
        center=(p[0]+dist*bis[0]/bl,p[1]+dist*bis[1]/bl,p[2])
        va=(t1[0]-center[0],t1[1]-center[1]);vb=(t2[0]-center[0],t2[1]-center[1])
        a,b=math.atan2(va[1],va[0]),math.atan2(vb[1],vb[0])
        angles=(a%(2*math.pi),b%(2*math.pi)) if cross(va,vb)>=0 else (b%(2*math.pi),a%(2*math.pi))
    return dict(kind=kind,intersection=p,tangent1=t1,tangent2=t2,near_index1=ia,near_index2=ib,
                center=center,angles=angles,radius=x if kind=='fillet' else None,
                tolerance=tol,ray_rule='farther endpoint; equal distance uses EndPoint')

def edit_corner(handle1,handle2,kind,size1,size2=None,trim=True):
    from . import com_backend as com
    doc=com._acad_doc()
    if int(doc.GetVariable('CMDACTIVE')):
        raise RuntimeError('AutoCAD command is active; finish or cancel it before corner editing')
    if str(handle1).upper()==str(handle2).upper():raise ValueError('Two different source handles are required')
    e1=com._com_unnarrow(doc.HandleToObject(str(handle1)));e2=com._com_unnarrow(doc.HandleToObject(str(handle2)))
    if e1.ObjectName!='AcDbLine' or e2.ObjectName!='AcDbLine':raise ValueError('COM corner editing supports LINE + LINE only')
    space=com._msp()
    if int(e1.OwnerID)!=int(e2.OwnerID) or int(e1.OwnerID)!=int(space.ObjectID):
        raise ValueError('Both source lines must be in the current active layout')
    if doc.Layers.Item(e1.Layer).Lock or doc.Layers.Item(e2.Layer).Lock:
        raise ValueError('A source layer is locked; no geometry changed')
    original=[(tuple(e.StartPoint),tuple(e.EndPoint)) for e in [e1,e2]]
    plan=corner_plan(*original[0],*original[1],kind,size1,size2,trim)
    created=None
    try:
        if kind=='fillet' and plan['radius']>0:
            created=com._com_unnarrow(space.AddArc(com._apoint(*plan['center']),plan['radius'],*plan['angles']))
        elif kind=='chamfer':
            created=com._com_unnarrow(space.AddLine(com._apoint(*plan['tangent1']),com._apoint(*plan['tangent2'])))
        if created is not None:
            created.Layer=e1.Layer;created.color=e1.color;created.Linetype=e1.Linetype;created.Lineweight=e1.Lineweight
        for i,e in enumerate([e1,e2],1):
            idx=plan['near_index'+str(i)];point=plan['tangent'+str(i)]
            if trim:setattr(e,'StartPoint' if idx==0 else 'EndPoint',com._apoint(*point));e.Update()
            expected=list(original[i-1])
            if trim:expected[idx]=point
            if any(math.dist(tuple(getattr(e,attr)),wanted)>plan['tolerance'] for attr,wanted in zip(['StartPoint','EndPoint'],expected)):
                raise RuntimeError('Source endpoint readback mismatch')
        if created is not None:
            created.Update()
            if kind=='fillet':
                if abs(float(created.Radius)-plan['radius'])>plan['tolerance'] or math.dist(tuple(created.Center),plan['center'])>plan['tolerance']:
                    raise RuntimeError('Arc radius/center readback mismatch')
                wanted=[plan['tangent1'],plan['tangent2']]
                actual=[tuple(created.StartPoint),tuple(created.EndPoint)]
                if not all(min(math.dist(p,q) for q in wanted)<=plan['tolerance'] for p in actual):raise RuntimeError('Arc tangent point readback mismatch')
            elif math.dist(tuple(created.StartPoint),plan['tangent1'])>plan['tolerance'] or math.dist(tuple(created.EndPoint),plan['tangent2'])>plan['tolerance']:
                raise RuntimeError('Chamfer endpoint readback mismatch')
        com._regen()
        result=com._entity_info(created if created is not None else e1)
        result.properties['corner_verification']={'kind':kind,'trim':bool(trim),'source_handles':[str(e1.Handle),str(e2.Handle)],
            'intersection':list(plan['intersection']),'tangent_points':[list(plan['tangent1']),list(plan['tangent2'])],
            'selection_rule':plan['ray_rule'],'method':'direct_com_geometry','created':created is not None}
        return result
    except Exception as exc:
        cleanup=[]
        if trim:
            for e,(s,t) in zip([e1,e2],original):
                try:e.StartPoint=com._apoint(*s);e.EndPoint=com._apoint(*t);e.Update()
                except Exception as err:cleanup.append(str(err))
        if created is not None:
            try:created.Delete()
            except Exception as err:cleanup.append(str(err))
        if cleanup:raise RuntimeError(f'{exc}; recovery incomplete: {cleanup}') from exc
        raise

def model_extents():
    from . import com_backend as com
    doc=com._acad_doc();space=doc.ModelSpace;total=int(space.Count)
    lo=[math.inf]*3;hi=[-math.inf]*3;measured=0;skipped=[];skip_count=0
    for i in range(total):
        e=None
        try:
            e=space.Item(i)
            if str(e.ObjectName) in {'AcDbXline','AcDbRay'}:raise ValueError('unbounded entity')
            a,b=e.GetBoundingBox();a=tuple(map(float,a));b=tuple(map(float,b))
            if len(a)!=3 or len(b)!=3 or not all(math.isfinite(v) for v in a+b) or any(x>y for x,y in zip(a,b)):
                raise ValueError('invalid entity bounding box')
            lo=[min(x,y) for x,y in zip(lo,a)];hi=[max(x,y) for x,y in zip(hi,b)];measured+=1
        except Exception as err:
            skip_count+=1
            if len(skipped)<100:
                row={'index':i,'reason':str(err)}
                if e is not None:
                    try:row.update(handle=str(e.Handle),type=str(e.ObjectName))
                    except Exception:pass
                skipped.append(row)
    if int(space.Count)!=total:raise RuntimeError('Model space changed while reading extents; retry after editing stops')
    return {'ok':measured>0 or total==0,'min':lo[:2] if measured else None,'max':hi[:2] if measured else None,
            'width':hi[0]-lo[0] if measured else 0.0,'height':hi[1]-lo[1] if measured else 0.0,
            'min3d':lo if measured else None,'max3d':hi if measured else None,'depth':hi[2]-lo[2] if measured else 0.0,
            'scope':'model_space','document':str(doc.Name),'method':'entity_GetBoundingBox_union',
            'entity_count':total,'measured_count':measured,'skipped_count':skip_count,'skipped':skipped,
            'skipped_truncated':skip_count>len(skipped),'complete':skip_count==0,'empty':total==0}
