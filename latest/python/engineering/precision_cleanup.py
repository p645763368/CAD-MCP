"""Pure geometry planning for conservative XY grid cleanup (no CAD side effects)."""
import math


def bounds(points):
    return [min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)]


def overlap(a, b, pad=0.0):
    return a[0] <= b[2]+pad and b[0] <= a[2]+pad and a[1] <= b[3]+pad and b[1] <= a[3]+pad


def on_segment(p, a, b, eps):
    dx, dy = b[0]-a[0], b[1]-a[1]
    length = math.hypot(dx, dy)
    if length <= eps:
        return math.dist(p[:2], a[:2]) <= eps
    return (abs(dx*(p[1]-a[1])-dy*(p[0]-a[0])) <= eps*length
            and min(a[0], b[0])-eps <= p[0] <= max(a[0], b[0])+eps
            and min(a[1], b[1])-eps <= p[1] <= max(a[1], b[1])+eps)


def contact(a,b,c,d,eps):
    ends = (on_segment(a,c,d,eps),on_segment(b,c,d,eps),on_segment(c,a,b,eps),on_segment(d,a,b,eps))
    def cross(p,q,r):return (q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0])
    crossing = cross(a,b,c)*cross(a,b,d)<0 and cross(c,d,a)*cross(c,d,b)<0
    return (any(ends) or crossing, *ends)


def segments(row, points=None):
    p = points if points is not None else row['points']
    return list(zip(p,p[1:]+([p[0]] if row.get('closed') else [])))


def plan(rows, handles, step, max_move, origin):
    """All dimensions in drawing units. Rows include context bounding boxes."""
    if not all(math.isfinite(v) for v in [step,max_move,*origin]) or step<=0 or max_move<=0 or max_move>step/2:
        raise ValueError('步长须为正数；最大位移须大于0且不超过步长的一半')
    if len(origin)!=2:raise ValueError('origin需要两个WCS坐标')
    selected=set(handles); index={r['handle']:r for r in rows}
    if selected-index.keys():raise ValueError('对象不存在于模型空间: '+','.join(sorted(selected-index.keys())))
    eps=max(1e-10,step*1e-8)
    changed={};skipped=[];blocked=[];details=[]
    for h in handles:
        r=index[h];p=r.get('points')
        reason=r.get('unsupported')
        if reason or not p:
            skipped.append({'handle':h,'reason':reason or '对象类型不支持'});continue
        if not all(math.isfinite(v) for point in p for v in point):raise ValueError('坐标含非有限数')
        if len(p)>200 or len(p)<2:
            skipped.append({'handle':h,'reason':'顶点数须为2–200'});continue
        q=[[origin[k]+math.floor((point[k]-origin[k])/step+0.5)*step for k in (0,1)]+[point[2]] for point in p]
        moves=[math.dist(a,b) for a,b in zip(p,q)]
        if max(moves)<=eps:continue
        if max(moves)>max_move+eps:
            blocked.append({'handle':h,'reason':'位移超过上限','max_move':max(moves)});continue
        old=segments(r);new=segments(r,q)
        if any(math.dist(a,b)<=eps for a,b in new):
            blocked.append({'handle':h,'reason':'整理后出现零长度段'});continue
        if any(min(abs(a[0]-b[0]),abs(a[1]-b[1]))>eps for a,b in new):
            skipped.append({'handle':h,'reason':'整理后仍为斜线；首版仅处理水平/垂直线网'});continue
        if any(min(abs(a[0]-b[0]),abs(a[1]-b[1]))>2*max_move+eps for a,b in old):
            skipped.append({'handle':h,'reason':'斜线超出微调范围'});continue
        if r.get('closed'):
            area=lambda v:sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(v,v[1:]+v[:1]))/2
            if abs(area(q))<=eps*eps or area(p)*area(q)<=0:
                blocked.append({'handle':h,'reason':'闭合区域塌缩或方向改变'});continue
        changed[h]=q
        details.append({'handle':h,'before':p,'after':q,'max_displacement':max(moves),
                        'lengths_before':[math.dist(a,b) for a,b in old],
                        'lengths_after':[math.dist(a,b) for a,b in new]})
    if sum(len(segments(index[h])) for h in changed)>500:raise ValueError('每次最多整理500个直线段，请分批')
    # Compare endpoint-on-segment and crossing relationships. Context is never moved.
    checks=0;seen=set()
    for h,q in changed.items():
        r=index[h];swept=bounds(r['points']+q)
        for other in rows:
            k=other['handle']
            if not other.get('bbox'):
                blocked.append({'handle':h,'other':k,'reason':'邻接检查缺少对象包围盒'});continue
            if not overlap(swept,other['bbox'],max_move+eps):continue
            if k!=h and (other.get('unsupported') or not other.get('points')):
                blocked.append({'handle':h,'other':k,'reason':'附近有不支持对象，无法验证连接关系'});continue
            pair=tuple(sorted((h,k)))
            if pair in seen:continue
            seen.add(pair)
            old_a=segments(r);new_a=segments(r,q)
            old_b=segments(other);new_b=segments(other,changed.get(k))
            for i,(a,b) in enumerate(old_a):
                for j,(c,d) in enumerate(old_b):
                    if h==k and i>=j:continue
                    if abs(a[2]-c[2])>eps:continue
                    checks+=1
                    if checks>200000:raise ValueError('连接检查超过上限，请缩小选择范围')
                    if contact(a,b,c,d,eps)!=contact(*new_a[i],*new_b[j],eps):
                        blocked.append({'handle':h,'other':k,'reason':'端点连接或交叉关系将改变','segments':[i,j]})
    return {'can_apply':not blocked,'changed_count':len(changed),'unchanged_count':len(handles)-len(changed)-len(skipped)-len({x['handle'] for x in blocked if x['handle'] not in changed}),
            'changes':details,'skipped':skipped,'blockers':blocked[:100], 'blocker_count':len(blocked),'connection_checks':checks}
