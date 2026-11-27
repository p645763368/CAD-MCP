"""Deterministic finite-boundary LINE extension, no command selection."""
import math

def extension_plan(start,end,bstart,bend,end_x=None,end_y=None):
    points=[tuple(map(float,p)) for p in (start,end,bstart,bend)]
    if any(len(p)!=3 or not all(map(math.isfinite,p)) for p in points):raise ValueError('Finite XYZ coordinates required')
    a,b,c,d=points
    length=math.dist(a,b);boundary_length=math.dist(c,d)
    if not math.isfinite(length+boundary_length) or min(length,boundary_length)<=1e-9:raise ValueError('Nonzero finite lines required')
    tol=max(1e-8,max(length,boundary_length)*1e-10)
    if max(p[2] for p in points)-min(p[2] for p in points)>tol:raise ValueError('Only coplanar WCS XY LINE pairs are supported')
    u=(b[0]-a[0],b[1]-a[1]);v=(d[0]-c[0],d[1]-c[1]);w=(c[0]-a[0],c[1]-a[1])
    cross=lambda p,q:p[0]*q[1]-p[1]*q[0]
    den=cross(u,v)
    if abs(den)<=1e-10*length*boundary_length:raise ValueError('Parallel or near-parallel lines have no stable extension')
    t=cross(w,v)/den;s=cross(w,u)/den
    if not (math.isfinite(t) and math.isfinite(s)):raise ValueError('Nonfinite intersection')
    if s < -tol/boundary_length or s>1+tol/boundary_length:raise ValueError('Intersection is outside the finite boundary; boundary is not extended')
    if t < -tol/length:idx=0
    elif t>1+tol/length:idx=1
    else:raise ValueError('Boundary does not lie beyond a target endpoint; no extension')
    if (end_x is None)!=(end_y is None):raise ValueError('end_x and end_y must be supplied together')
    if end_x is not None:
        pick=(float(end_x),float(end_y))
        if not all(map(math.isfinite,pick)):raise ValueError('Endpoint selector must be finite')
        ds=math.dist(pick,a[:2]);de=math.dist(pick,b[:2])
        if abs(ds-de)<=tol:raise ValueError('Endpoint selector is ambiguous')
        if (0 if ds<de else 1)!=idx:raise ValueError('Selected endpoint points away from boundary')
    hit=(a[0]+t*u[0],a[1]+t*u[1],a[2])
    if not all(map(math.isfinite,hit)):raise ValueError('Nonfinite endpoint')
    return {'index':idx,'point':hit,'tolerance':tol,'distance_added':math.dist(points[idx],hit)}

def extend_line(target_handle,boundary_handle,end_x=None,end_y=None):
    from . import com_backend as com
    doc=com._acad_doc()
    if int(doc.GetVariable('CMDACTIVE')):raise RuntimeError('Finish or cancel the active CAD command before extension')
    if str(target_handle).upper()==str(boundary_handle).upper():raise ValueError('Target and boundary must be different')
    target=com._com_unnarrow(doc.HandleToObject(str(target_handle)));boundary=com._com_unnarrow(doc.HandleToObject(str(boundary_handle)))
    if target.ObjectName!='AcDbLine' or boundary.ObjectName!='AcDbLine':raise ValueError('COM extension supports LINE target and finite LINE boundary only')
    if int(target.OwnerID)!=int(boundary.OwnerID) or int(target.OwnerID)!=int(com._msp().ObjectID):raise ValueError('Both lines must belong to the active layout')
    if doc.Layers.Item(target.Layer).Lock:raise ValueError('Target layer is locked')
    original=(tuple(target.StartPoint),tuple(target.EndPoint));bound=(tuple(boundary.StartPoint),tuple(boundary.EndPoint))
    plan=extension_plan(*original,*bound,end_x,end_y);attr='StartPoint' if plan['index']==0 else 'EndPoint'
    try:
        setattr(target,attr,com._apoint(*plan['point']));target.Update()
        expected=list(original);expected[plan['index']]=plan['point']
        if any(math.dist(tuple(getattr(target,k)),v)>plan['tolerance'] for k,v in zip(['StartPoint','EndPoint'],expected)):raise RuntimeError('Extension endpoint readback mismatch')
        com._regen();result=com._entity_info(target)
        result.properties['extension_verification']={'method':'direct_com_geometry','boundary_handle':str(boundary.Handle),'endpoint':attr,'distance_added':plan['distance_added'],'boundary_extended':False}
        return result
    except Exception as exc:
        try:
            target.StartPoint=com._apoint(*original[0]);target.EndPoint=com._apoint(*original[1]);target.Update()
            if any(math.dist(tuple(getattr(target,k)),v)>plan['tolerance'] for k,v in zip(['StartPoint','EndPoint'],original)):raise RuntimeError('restore readback mismatch')
        except Exception as recovery:raise RuntimeError(f'{exc}; recovery incomplete: {recovery}') from exc
        raise
