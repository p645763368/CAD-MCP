"""Preview-first, bounded model-space geometry cleanup through existing COM bridge."""
from typing import Annotated, Literal
import hashlib, hmac, json, math, secrets
from fastmcp import Context
from engineering.precision_cleanup import plan, bounds, overlap

_SECRET=secrets.token_bytes(32)


def _identity(doc):
    return [str(doc.FullName),str(doc.Name),int(doc.HWND),int(doc.ModelSpace.ObjectID)]


def _selected(doc, handle):
    from backends import com_backend as com
    e=com._com_unnarrow(doc.HandleToObject(handle))
    r={'handle':handle,'type':str(e.ObjectName),'layer':str(e.Layer)}
    if int(e.OwnerID)!=int(doc.ModelSpace.ObjectID):raise ValueError('仅支持模型空间对象')
    if bool(doc.Layers.Item(e.Layer).Lock):r['unsupported']='锁定图层';return r
    if bool(e.HasExtensionDictionary):r['unsupported']='对象含扩展数据字典，需单独核对约束或关联';return r
    if e.ObjectName=='AcDbLine':
        r['points']=[list(e.StartPoint),list(e.EndPoint)];r['closed']=False
    elif e.ObjectName=='AcDbPolyline':
        if math.dist(tuple(e.Normal),(0,0,1))>1e-9:r['unsupported']='多段线法向必须为+Z';return r
        coords=list(e.Coordinates);n=len(coords)//2
        if n>200:r['unsupported']='多段线超过200个顶点';return r
        if any(abs(e.GetBulge(i))>1e-12 for i in range(n)):r['unsupported']='含圆弧段';return r
        if any(any(abs(v)>1e-12 for v in e.GetWidth(i)) for i in range(n)):
            r['unsupported']='含宽度的多段线';return r
        r['points']=[[coords[2*i],coords[2*i+1],float(e.Elevation)] for i in range(n)];r['closed']=bool(e.Closed)
    else:r['unsupported']='首版仅支持LINE和直线段LWPOLYLINE';return r
    if max(p[2] for p in r['points'])-min(p[2] for p in r['points'])>1e-10:
        r['unsupported']='三维倾斜线';return r
    if abs(float(e.Thickness))>1e-12:r['unsupported']='对象有厚度';return r
    r['bbox']=bounds(r['points'])
    return r


def _snapshot(doc, handles, padding):
    from project_fixes import dispatch
    # Existing native snapshot is XY-only; use it for spatial filtering, then
    # read true WCS XYZ and polyline OCS/normal through COM for nearby objects.
    result=dispatch('entities',limit=50000,offset=0,fields=['properties.bounding_box'])
    if result['errors'] or len(result['rows'])!=result['total']:raise ValueError('模型快照不完整或超过50000个对象，请拆分图纸后处理')
    chosen={h:_selected(doc,h) for h in handles}
    boxes=[r['bbox'] for r in chosen.values() if r.get('bbox') and not r.get('unsupported')]
    rows=[];nearby=0
    for e in result['rows']:
        p=e['properties'];h=e['handle'].upper();r={'handle':h,'type':e['type'],'layer':e['layer']}
        if 'bounding_box' in p:
            box=p['bounding_box'];r['bbox']=[*box['min'][:2],*box['max'][:2]]
        if h in chosen:r.update(chosen[h])
        elif r.get('bbox') and any(overlap(r['bbox'],box,padding) for box in boxes):
            nearby+=1
            if nearby>500:raise ValueError('邻近对象超过500个，请缩小选择范围')
            r.update(_selected(doc,h))
        else:r['unsupported']='范围外或缺少包围盒'
        if r.get('points') and (len(r['points'])<2 or any(len(pt)!=3 or not all(math.isfinite(v) for v in pt) for pt in r['points'])):
            raise ValueError('快照坐标不完整')
        rows.append(r)
    return rows


def _write(doc,handle,points):
    from backends import com_backend as com
    e=com._com_unnarrow(doc.HandleToObject(handle))
    if e.ObjectName=='AcDbLine':
        e.StartPoint=com._apoint(*points[0]);e.EndPoint=com._apoint(*points[1])
    else:e.Coordinates=com._av([v for p in points for v in p[:2]])
    e.Update()


def cleanup_sync(handles,step_mm,max_move_mm,origin,model_units,dry_run,expected_token):
    from backends import com_backend as com
    from project_fixes import required_context
    if not 1<=len(handles)<=100 or len(set(h.upper() for h in handles))!=len(handles):raise ValueError('选择1–100个不重复句柄')
    if any(not h or any(c not in '0123456789abcdefABCDEF' for c in h) for h in handles):raise ValueError('句柄必须为十六进制字符串')
    if len(origin)!=2 or any(not math.isfinite(v) for v in [step_mm,max_move_mm,*origin]):raise ValueError('输入必须为有限数，origin为两个WCS坐标')
    if step_mm<=0 or max_move_mm<=0 or max_move_mm>step_mm/2:raise ValueError('最大位移须大于0且不超过步长的一半')
    handles=sorted(h.upper() for h in handles)
    doc=com._acad_doc();identity=_identity(doc)
    if int(doc.GetVariable('CMDACTIVE')):raise ValueError('请先结束当前CAD命令')
    if not bool(doc.ActiveLayout.ModelType):raise ValueError('请在模型选项卡操作')
    units=required_context(model_units);factor=units['mm_per_unit']
    rows=_snapshot(doc,handles,2*max_move_mm/factor+step_mm/factor*1e-8)
    result=plan(rows,handles,step_mm/factor,max_move_mm/factor,origin)
    state={'document':identity,'units':units,'handles':handles,'step_mm':step_mm,'max_move_mm':max_move_mm,'origin':origin,'rows':rows}
    token=hmac.new(_SECRET,json.dumps(state,sort_keys=True,separators=(',',':'),allow_nan=False).encode(),hashlib.sha256).hexdigest()
    result.update(ok=True,dry_run=dry_run,preview_token=token,document=identity[0],unit_context=units,step_mm=step_mm,max_move_mm=max_move_mm,origin=origin,applied_count=0)
    for change in result['changes']:change['max_displacement_mm']=change['max_displacement']*factor
    if dry_run:return result
    if not expected_token or not hmac.compare_digest(expected_token,token):raise ValueError('预览已失效或未提供token；请按相同参数重新预览')
    if not result['can_apply']:raise ValueError('连接/位移检查未通过，未执行任何几何修改；请查看预览blockers')
    if not result['changes']:return result
    touched=[];rollback=[]
    def active():
        if _identity(com._acad_doc())!=identity:raise RuntimeError('活动图纸已改变，停止操作')
        if int(doc.GetVariable('CMDACTIVE')):raise RuntimeError('CAD命令状态已改变，停止操作')
    active();doc.StartUndoMark()
    try:
        # Re-read selected objects immediately before the first mutation.
        originals={r['handle']:r for r in rows if r['handle'] in handles}
        for h in handles:
            actual=_selected(doc,h)
            if any(originals[h].get(k)!=v for k,v in actual.items()):raise RuntimeError('对象已变化，请重新预览')
        for change in result['changes']:
            active();touched.append(change);_write(doc,change['handle'],change['after'])
        for change in touched:
            actual=_selected(doc,change['handle'])
            if actual.get('points')!=change['after']:raise RuntimeError('几何读回与方案不一致')
        active()
    except Exception as exc:
        for change in reversed(touched):
            try:
                _write(doc,change['handle'],change['before'])
                if _selected(doc,change['handle']).get('points')!=change['before']:raise RuntimeError('恢复读回不一致')
            except Exception as error:rollback.append({'handle':change['handle'],'error':str(error)})
        raise RuntimeError(json.dumps({'error':str(exc),'rollback_verified':not rollback,'rollback_errors':rollback},ensure_ascii=False)) from exc
    finally:doc.EndUndoMark()
    result.update(applied_count=len(touched),readback_verified=True)
    return result


def register(s):
    async def drawing_round_geometry(
        handles:Annotated[list[str],'明确选择的1–100个模型空间实体句柄；支持LINE及零宽直线段LWPOLYLINE'],
        step_mm:Annotated[float,'XY网格步长，毫米；如1表示归整到1mm网格'],
        max_move_mm:Annotated[float,'单个端点/顶点最大二维位移，毫米；大于0且不超过步长的一半'],
        origin:Annotated[list[float],'网格基点[WCS x,y]，使用图纸单位；应与项目轴网基点一致'],
        model_units:Annotated[Literal['mm','cm','m','inch','ft']|None,'null读取INSUNITS；已核对实际单位后可显式覆盖，不改INSUNITS']=None,
        dry_run:Annotated[bool,'默认只预览，返回坐标/段长变化和连接检查；false才写入']=True,
        expected_token:Annotated[str|None,'执行必须携带相同参数最新预览token；文档、实体或单位变化会使其失效']=None,
        ctx:Context=None)->dict:
        b=s._backend(ctx)
        if not hasattr(b,'_run'):raise ValueError('当前工具需要AutoCAD 2026 COM后端')
        return await b._run(cleanup_sync,handles,step_mm,max_move_mm,origin,model_units,dry_run,expected_token)
    summary='图纸碎数整理：预览并将直线网端点/顶点归整到指定毫米网格'
    limits='实际修改XY坐标，保留Z、句柄、图层和闭合状态；归整后须为水平/垂直线段。最大100实体/500线段，模型快照上限50000实体。检查模型空间线段端点连接和交叉关系；位移超限、零长、关系改变整次拒绝。锁层、斜线、弧线、宽多段线、块、外参及扩展字典对象跳过；附近不支持对象或缺失包围盒会阻止执行。相连未选对象保持原位。仅COM，依赖已有CadMcpProjectFix2026桥；尺寸、填充和建筑元数据需另行核对，不自动保存；失败尝试恢复并报告读回结果。'
    s.mcp.tool(name='drawing_round_geometry',description=summary+'。\n'+limits,
        annotations={'readOnlyHint':False,'destructiveHint':False,'idempotentHint':False},
        meta={'cad':{'summary':summary,'limits':limits,'cost':'mutate','risk':'write',
          'zh_aliases':['碎数','碎数整理','图纸碎数','坐标取整','几何取整','墙线归整','小数整理'],
          'synonyms':['round geometry','coordinate rounding','grid cleanup'],'catalog_revision':'2026-11-27.precision1'}},tags={'modify','architecture_edit'})(drawing_round_geometry)
