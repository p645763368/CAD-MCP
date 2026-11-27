"""Pure interval selection for deterministic planar LINE trimming."""
import math

def retained_interval(start,end,intersections,keep):
    s=tuple(map(float,start));e=tuple(map(float,end));k=tuple(map(float,keep))
    if len(s)!=3 or len(e)!=3 or len(k)!=2:raise ValueError('Invalid point dimensions')
    if not all(math.isfinite(v) for p in [s,e,k] for v in p):raise ValueError('Coordinates must be finite')
    length=math.dist(s,e);tol=max(1e-8,length*1e-9)
    if length<=tol:raise ValueError('Cannot trim a zero-length line')
    if abs(s[2]-e[2])>tol:raise ValueError('COM trim supports planar XY LINE targets only')
    d=tuple(e[i]-s[i] for i in range(3));den=sum(v*v for v in d)
    def project(p):return sum((p[i]-s[i])*d[i] for i in range(3))/den
    k3=(k[0],k[1],s[2]);t=project(k3)
    at=lambda u:tuple(s[i]+u*d[i] for i in range(3))
    if t < -tol/length or t > 1+tol/length or math.dist(k3,at(t))>tol:
        raise ValueError('keep_x/keep_y must lie on the target line')
    cuts=[]
    for point in intersections:
        p=tuple(map(float,point))
        if len(p)!=3 or not all(math.isfinite(v) for v in p):raise ValueError('Invalid intersection returned by CAD')
        u=project(p)
        if math.dist(p,at(u))>tol:raise ValueError('CAD intersection is not on the target')
        if tol/length < u < 1-tol/length and all(abs(u-v)*length>tol for v in cuts):cuts.append(u)
    if not cuts:raise ValueError('No internal intersection; no geometry changed (cutters are not implicitly extended)')
    if any(abs(t-u)*length<=tol for u in cuts):raise ValueError('Keep point is on a cut: choose one retained segment explicitly')
    bounds=[0.0]+sorted(cuts)+[1.0]
    lo,hi=next((a,b) for a,b in zip(bounds,bounds[1:]) if a-tol/length<=t<=b+tol/length)
    return at(lo),at(hi),{'original_length':length,'retained_length':(hi-lo)*length,'cut_count':len(cuts),'tolerance':tol}
