"""P0/P1 building workflows with document-bound preview tokens."""
from __future__ import annotations
from typing import Annotated,Literal
import hashlib,hmac,json,secrets,math
from fastmcp import Context
from engineering import building as g
from engineering.building_checks import check_snapshot,factor
from building_bridge import dispatch

_SECRET=secrets.token_bytes(32)
def token(snapshot,plan):return hmac.new(_SECRET,json.dumps([snapshot['token'],plan],sort_keys=True,ensure_ascii=True,separators=(',',':'),allow_nan=False).encode(),hashlib.sha256).hexdigest()
async def snapshot(s,ctx,scope='model'):
 b=s._backend(ctx)
 if not hasattr(b,'_run'):raise ValueError('此建筑工作流需要AutoCAD 2026 COM后端')
 return await b._run(dispatch,'snapshot',scope=scope)
def selected(snap,handles):
 if not handles or len(handles)>1000:raise ValueError('选择1–1000个不重复句柄')
 try:handles=[format(int(h.strip(),16),'X') for h in handles]
 except (ValueError,AttributeError):raise ValueError('句柄须为十六进制字符串')
 if len(set(handles))!=len(handles):raise ValueError('句柄重复')
 by={r['handle'].upper():r for r in snap['rows']};rows=[]
 for h in handles:
  r=by.get(h.upper())
  if r is None:raise ValueError('模型中没有对象: '+h)
  rows.append(r)
 return rows
async def present(s,ctx,snap,plan,dry_run,expected_token):
 if not snap['complete']:raise ValueError('图纸读取不完整，未执行修改')
 for e in plan.get('entities',[]):
  if not e.get('layer') or '|' in e['layer']:raise ValueError('目标图层不合法')
  if any(l['name']==e['layer'] and l['locked'] for l in snap['layers']):raise ValueError('目标图层已锁定')
 preview=token(snap,plan);result={'ok':True,'dry_run':dry_run,'can_apply':not plan.get('blockers'),'blockers':plan.get('blockers',[]),'preparations':plan.get('preparations',[]),'preview_token':preview,'create_count':len(plan.get('entities',[])),'update_count':len(plan.get('updates',[])),'result':plan.get('result',{}),'preview_entities':plan.get('entities',[])[:100],'preview_truncated':len(plan.get('entities',[]))>100,'updates':plan.get('updates',[])[:100]}
 if dry_run:return result
 if not expected_token or not hmac.compare_digest(preview,expected_token):raise ValueError('预览已失效或参数改变；请重新预览')
 if plan.get('blockers'):raise ValueError('方案无法执行: '+str(plan['blockers']))
 answer=await s._backend(ctx)._run(dispatch,'apply',scope=snap['scope'],expected_token=snap['token'],plan=plan)
 result.update(answer);result.pop('preview_entities',None);return result

def number(value,where):
 try:v=float(str(value).strip())
 except (ValueError,TypeError):raise ValueError(where+'需要明确数值，不能推断复合字符串') from None
 if not math.isfinite(v):raise ValueError(where+'不是有限数')
 return v

def opening_data(row,mapping,unit_factor):
 attrs={k.casefold():v for k,v in row.get('attributes',{}).items()};data={}
 if len(mapping)>24:raise ValueError('属性映射最多24个字段')
 for field,key in mapping.items():
  if not isinstance(key,str) or key.casefold() not in attrs:raise ValueError('块'+row['handle']+'缺少属性'+str(key))
  value=attrs[key.casefold()];data[field]=number(value,field)*unit_factor if field in ['width','height','sill'] else str(value).strip()
 if 'width' not in data or 'height' not in data or data['width']<=0 or data['height']<=0:raise ValueError('需要有效的宽度/高度属性映射')
 return data

def opening_signature(kind,data,extra_fields=()):
 keys=list(dict.fromkeys(['width','height','sill',*extra_fields]))
 return (kind,tuple((k,data.get(k)) for k in keys))


def register(s):
 # User-facing architectural defaults, independent of legacy manufacturing presets.
 for current in s._local_tool_components():
  if current.name in ['drawing_preflight','drawing_plan']:
   current.description=('只读检查建筑任务的单位、范围、图幅和约束；默认arch建筑图层。' if current.name=='drawing_preflight' else '记录建筑绘图计划和出图要求；默认arch建筑图层，不直接生成图元。')
   if 'requirements' in current.parameters['properties']:current.parameters['properties']['requirements']['description']='建筑要求：units，scope或dimensions/reference，可选project_rules和constraints。'
  elif current.name=='drawing_critique':
   current.description='检查建筑尺寸重叠、未修剪角、重复实体、构造线和已记录房间/墙/门窗问题。默认建筑组合，其他专业须显式指定focus。部分检查依赖建筑记录；返回问题列表。'
   current.parameters['properties']['focus']['description']='null使用建筑检查组合；可显式传原有focus名称列表。'
  elif current.name=='drawing_refine':
   current.description='预览或执行建筑图纸整改计划；默认dry_run=true，仅列出方案。默认允许重复实体清理与尺寸重叠调整，其他修复须显式选择。执行使用原有撤销保护，不自动保存。'
   current.parameters['properties']['focus']['description']='null使用建筑检查组合。'
   current.parameters['properties']['allowed_repairs']['description']='null只允许duplicate_entities和dim_overlap；其他规则须明确提供。'
  if current.name in ['drawing_preflight','drawing_plan','drawing_critique','drawing_refine'] and current.meta and 'cad' in current.meta:
   current.meta['cad']['limits']=current.description;current.meta['cad']['catalog_revision']='2026-11-27.p01'
 def tool(name,summary,aliases,risk='write'):
  def wrap(fn):
   if name in {t.name for t in s._local_tool_components()}:s.mcp._local_provider.remove_tool(name)
   s.mcp.tool(name=name,description=summary+'。\n'+(fn.__doc__ or '')+('\n仅支持AutoCAD 2026 COM及建筑原生桥。' if name!='stair_check' else '\n参数计算可离线运行。'),annotations={'readOnlyHint':risk=='read','destructiveHint':risk=='destructive','idempotentHint':risk=='read'},meta={'cad':{'summary':summary,'risk':risk,'cost':'read' if risk=='read' else 'destructive' if risk=='destructive' else 'mutate','zh_aliases':aliases,'catalog_revision':'2026-11-27.p01'}},tags={'arch'})(fn);return fn
  return wrap

 @tool('validation_check','检查空图层、零长、重复几何、编号和交付依赖',['检查图纸','质量检查','重线检查'],'read')
 async def validation_check(checks:Annotated[list[str]|None,'empty_layers/zero_length/duplicate_entities/duplicate_tags/assets；null全选']=None,scope:Literal['model','all']='all',tolerance_mm:float=.001,model_units:Literal['mm','cm','m','inch','ft']|None=None,ctx:Context=None)->dict:
  """只读；ok表示执行成功，passed表示没有error级发现；complete表示读取完整。重复检查按容差量化并区分空间/图层/样式，未支持类型单列coverage。全空间最多200000对象，超限拒绝，不会静默截断。"""
  return check_snapshot(await snapshot(s,ctx,scope),checks,tolerance_mm,model_units)

 @tool('arch_grid','生成正交、斜向及弧形轴网和轴号',['绘制轴网','轴号','弧形轴网'],'destructive')
 async def arch_grid(x_axes:Annotated[list[float]|None,'竖向轴线在局部X的位置，采用图纸单位']=None,y_axes:Annotated[list[float]|None,'横向轴线在局部Y的位置，采用图纸单位']=None,labels:dict|None=None,extension:Annotated[float,'轴线延伸毫米']=1500,scale:float=50,origin:list[float]=[0,0],rotation_deg:float=0,arc_axes:Annotated[list[dict]|None,'[{center:[x,y],radius:模型单位,start_angle_deg,end_angle_deg,label}]；弧轴使用WCS']=None,sides:Literal['start','end','both']='both',group:str='GRID',axis_layer:str='A-GRID-E-N',label_layer:str='A-SYMB-T-N',replace:bool=False,model_units:Literal['mm','cm','m','inch','ft']|None=None,dry_run:bool=True,expected_token:str|None=None,ctx:Context=None)->dict:
  """默认预览；执行须带token。正交坐标可按origin/rotation旋转；弧轴独立使用WCS。两端/单端轴号，禁止重号。replace仅替换同group由本工具记录的轴网。默认沿用建筑CENTER轴线图层；首次空图需先drawing_apply_iso_layers(standard=arch)。"""
  snap=await snapshot(s,ctx);mm=factor(snap,model_units);plan=g.grid_plan(x_axes or [],y_axes or [],arc_axes or [],labels,origin,rotation_deg,extension,scale,sides,mm,group,{'axis':axis_layer,'label':label_layer});plan['updates']=g.replacement(snap['rows'],'grid_',group,replace)
  if axis_layer=='A-GRID-E-N' and not any(l['name']==axis_layer for l in snap['layers']):
   plan['blockers']=['尚未初始化建筑轴网图层；先应用arch图层标准再预览']
   plan['preparations']=[{'tool':'drawing_apply_iso_layers','arguments':{'standard':'arch'}}]
  return await present(s,ctx,snap,plan,dry_run,expected_token)

 @tool('grid_label','为既有直线或弧轴补轴号并刷新位置',['补轴号','既有轴网标注'],'destructive')
 async def grid_label(handles:list[str],labels:list[str],group:str,scale:float=50,extension_mm:float=300,sides:Literal['start','end','both']='both',layer:str='A-GRID-TEXT',replace:bool=False,model_units:Literal['mm','cm','m','inch','ft']|None=None,dry_run:bool=True,expected_token:str|None=None,existing_labels:Annotated[dict|None,'可选：源轴线句柄→既有TEXT/MTEXT句柄列表；用于关联已有轴号并保留位置']=None,ctx:Context=None)->dict:
  """保留原轴线；标注记录源句柄。replace仅删除同group、同源轴线的已有轴号/圆圈/延伸线，再按当前源几何补标。"""
  snap=await snapshot(s,ctx);mm=factor(snap,model_units);axes=selected(snap,handles)
  if len(labels)!=len(axes) or len(set(labels))!=len(labels) or any(not str(x).strip() for x in labels):raise ValueError('轴号与轴线一一对应且不可重复')
  sources={a['handle'] for a in axes};existing=[r for r in snap['rows'] if (r.get('record') or {}).get('group')==group and (r.get('record') or {}).get('kind') in ['grid_label','grid_bubble','grid_extension']]
  if any(r['record']['source'] not in sources and r['record']['label'] in labels for r in existing):raise ValueError('与该组其他轴号重复')
  if existing_labels is not None:
   existing_labels={format(int(k,16),'X'):v for k,v in existing_labels.items()}
   if set(existing_labels)!=sources:raise ValueError('每条源轴线都须提供对应的既有轴号文字')
   all_labels=[h for hs in existing_labels.values() for h in hs];selected(snap,all_labels)
   updates=[]
   for axis,label in zip(axes,labels):
    texts=selected(snap,existing_labels[axis['handle']])
    for item in texts:
     if item['type'] not in ['TEXT','MTEXT'] or item['locked']:raise ValueError('既有轴号须为未锁定文字')
     rec=item.get('record') or {}
     if rec and (rec.get('kind')!='grid_label' or rec.get('group')!=group):raise ValueError('文字已有其他构件关联')
     updates.append({'handle':item['handle'],'text':str(label),'record':g.record('grid_label',group,mm,source=axis['handle'],label=str(label),side='existing')})
   return await present(s,ctx,snap,{'entities':[],'updates':updates,'result':{'adopted_labels':len(all_labels)}},dry_run,expected_token)
  old=[r for r in existing if r['record']['source'] in sources]
  if old and not replace:raise ValueError('已标注，请明确replace=true更新')
  plan={'entities':[e for a,label in zip(axes,labels) for e in g.axis_labels(a,label,group,mm,scale,extension_mm,sides,layer)],'updates':[{'handle':r['handle'],'delete':True} for r in old]+[{'handle':a['handle'],'record':dict(a['record'],label=label)} for a,label in zip(axes,labels) if (a.get('record') or {}).get('kind')=='grid_axis' and a['record'].get('group')==group],'result':{'axes':sources and list(sources),'labels':labels}}
  return await present(s,ctx,snap,plan,dry_run,expected_token)

 @tool('grid_renumber','批量修改已记录轴号并检查重号',['轴号重编号','批量改轴号'])
 async def grid_renumber(group:str,mapping:Annotated[dict,'源轴线句柄→新轴号'],dry_run:bool=True,expected_token:str|None=None,ctx:Context=None)->dict:
  """只更新本工具记录的轴网标签，保留位置。一次支持交换轴号；与未改轴线发生重号时拒绝。"""
  snap=await snapshot(s,ctx);mapping={k.upper():str(v) for k,v in mapping.items()}
  rows=[r for r in snap['rows'] if (r.get('record') or {}).get('group')==group and (r.get('record') or {}).get('kind','').startswith('grid_')];current={}
  for row in rows:
   rec=row['record'];source=rec.get('source',row['handle']);current[source]=mapping.get(source,rec['label'])
  if not mapping or set(mapping)-set(current) or len(set(current.values()))!=len(current) or any(not x.strip() for x in current.values()):raise ValueError('映射源不存在、为空或改后重号')
  updates=[]
  for row in rows:
   rec=row['record'];source=rec.get('source',row['handle'])
   if source in mapping:
    u={'handle':row['handle'],'record':dict(rec,label=mapping[source])}
    if rec['kind']=='grid_label':u['text']=mapping[source]
    updates.append(u)
  return await present(s,ctx,snap,{'entities':[],'updates':updates,'result':{'labels':current}},dry_run,expected_token)

 @tool('parking_layout','按边界和障碍排布停车行并编号统计',['停车位排布','停车场布置'],'destructive')
 async def parking_layout(rows:Annotated[list[dict],'每行{origin:[x,y],count,width_mm,length_mm,aisle_mm,angle_deg:0或15..90,direction_deg,sides:single/double,prefix,start_number,bay_overrides:{索引:{width_mm,access_strip_mm,kind}}}'],group:str,boundary:Annotated[list[list[float]]|None,'场地闭合边界，图纸单位；null不限制']=None,obstacles:Annotated[list[list[list[float]]]|None,'柱墙等障碍多边形，图纸单位']=None,clearance_mm:float=0,layer:str='A-PARKING',label_layer:str='A-PARKING-TEXT',text_height_mm:float=200,replace:bool=False,model_units:Literal['mm','cm','m','inch','ft']|None=None,dry_run:bool=True,expected_token:str|None=None,boundary_handle:Annotated[str|None,'可选已有Z=0闭合直线多段线，和boundary二选一']=None,obstacle_handles:Annotated[list[str]|None,'可选柱墙闭合直线多段线或Z=0圆']=None,ctx:Context=None)->dict:
  """输入为项目明确尺寸，不内置法规判定。过滤超界、障碍/通道冲突和重叠车位，报告每个遗漏；含特殊车位宽度及侧向预留带。斜列端线与通道平行。圆障碍使用128段外包多边形作保守避让；未进行车辆转弯扫掠。"""
  snap=await snapshot(s,ctx);mm=factor(snap,model_units)
  if boundary_handle:
   if boundary is not None:raise ValueError('boundary与boundary_handle二选一')
   row=selected(snap,[boundary_handle])[0]
   if any(abs(p[2])>1e-9 for p in row.get('points',[])):raise ValueError('停车边界须在Z=0平面')
   boundary=list(g.polygon_row(row).exterior.coords)[:-1]
  obstacles=list(obstacles or [])
  for row in selected(snap,obstacle_handles) if obstacle_handles else []:
   if row['type']=='CIRCLE':
    c=row['center'];normal=row.get('normal',[0,0,1])
    if abs(c[2])>1e-9 or abs(abs(normal[2])-1)>1e-9:raise ValueError('障碍圆须位于Z=0的XY平面')
    radius=row['radius']/math.cos(math.pi/128);obstacles.append([[c[0]+radius*math.cos(i*math.tau/128),c[1]+radius*math.sin(i*math.tau/128)] for i in range(128)])
   else:
    if any(abs(p[2])>1e-9 for p in row.get('points',[])):raise ValueError('障碍边界须在Z=0平面')
    obstacles.append(list(g.polygon_row(row).exterior.coords)[:-1])
  plan=g.parking_plan(rows,boundary,obstacles or [],mm,group,clearance_mm,layer,label_layer,g.positive(text_height_mm,'text_height'));plan['updates']=g.replacement(snap['rows'],'parking_',group,replace)
  if plan['result']['count']==0:plan['blockers']=['没有满足边界和障碍条件的车位，保留原有停车组']
  return await present(s,ctx,snap,plan,dry_run,expected_token)

 @tool('parking_row','绘制一行或背靠背两行停车位',['单排车位','双排车位'],'destructive')
 async def parking_row(origin:list[float],count:int,width_mm:float,length_mm:float,aisle_mm:float,group:str,angle_deg:float=90,direction_deg:float=0,sides:Literal['single','double']='single',prefix:str='P',start_number:int=1,bay_overrides:dict|None=None,boundary:list[list[float]]|None=None,obstacles:list[list[list[float]]]|None=None,replace:bool=False,model_units:Literal['mm','cm','m','inch','ft']|None=None,dry_run:bool=True,expected_token:str|None=None,boundary_handle:Annotated[str|None,'可选已有Z=0闭合直线多段线，和boundary二选一']=None,obstacle_handles:Annotated[list[str]|None,'可选柱墙闭合直线多段线或Z=0圆']=None,ctx:Context=None)->dict:
  """尺寸毫米，origin和边界使用图纸单位。预览及碰撞规则同parking_layout；双排按通道两侧布置。"""
  return await parking_layout([dict(origin=origin,count=count,width_mm=width_mm,length_mm=length_mm,aisle_mm=aisle_mm,angle_deg=angle_deg,direction_deg=direction_deg,sides=sides,prefix=prefix,start_number=start_number,bay_overrides=bay_overrides or {})],group,boundary,obstacles,replace=replace,model_units=model_units,dry_run=dry_run,expected_token=expected_token,boundary_handle=boundary_handle,obstacle_handles=obstacle_handles,ctx=ctx)

 @tool('door_window_tag','按块属性识别门窗并按实例或型号编号',['门窗编号','门窗属性识别','门窗型号'])
 async def door_window_tag(handles:list[str],kind:Literal['door','window'],mapping:Annotated[dict,'width/height→宽高属性名必填；tag/sill可选；其他字段按字符串保存，可用于材料/防火等级'],group:str,prefix:str,start_number:int=1,numbering:Literal['instance','type']='instance',type_fields:Annotated[list[str]|None,'型号分组附加字段；宽高窗台始终参与，如material、fire_rating']=None,attribute_units:Literal['mm','model']='mm',label_offset:list[float]=[0,0],text_height_mm:float=200,layer:str='A-DOOR-WINDOW-TEXT',model_units:Literal['mm','cm','m','inch','ft']|None=None,dry_run:bool=True,expected_token:str|None=None,ctx:Context=None)->dict:
  """instance逐实例编号；type按规格共用型号，明细可汇总数量。读取显式映射的本地块属性，不推断散线；锁层/外参拒绝。检查与未选块的同名编号冲突；缩放块列出核对提示。"""
  snap=await snapshot(s,ctx);mm=factor(snap,model_units);blocks=selected(snap,handles);updates=[];entities=[];summary=[];warnings=[]
  if not prefix.strip() or start_number<0 or numbering not in ['instance','type']:raise ValueError('编号前缀、起号或模式不合法')
  if len(label_offset)!=2:raise ValueError('label_offset需要两个坐标值')
  extras=sorted(k for k in mapping if k not in ['tag','width','height','sill']) if type_fields is None else type_fields
  if any(field not in mapping for field in extras):raise ValueError('型号分组字段缺少映射')
  values=[];tags=[];types={}
  for row in blocks:
   if row['type']!='INSERT' or row.get('xref') or row['locked']:raise ValueError('需要未锁定本地块')
   data=opening_data(row,mapping,mm if attribute_units=='model' else 1);signature=opening_signature(kind,data,extras)
   if numbering=='type':
    if signature not in types:types[signature]=prefix+str(start_number+len(types))
    tag=types[signature]
   else:tag=prefix+str(start_number+len(tags))
   values.append(data);tags.append(tag)
   if any(abs(v-1)>1e-9 for v in row.get('scale',[1,1])[:2]):warnings.append({'handle':row['handle'],'message':'块存在缩放，宽高按映射属性读取，请核对属性与几何是否一致','scale':row.get('scale')})
  if numbering=='type':
   specs={}
   for tag,data in zip(tags,values):
    signature=opening_signature(kind,data,[k for k in mapping if k!='tag'])
    if tag in specs and specs[tag]!=signature:raise ValueError('同型号的映射属性不同，请补全type_fields')
    specs[tag]=signature
  chosen={r['handle'] for r in blocks};planned={tag:opening_signature(kind,data,extras) for tag,data in zip(tags,values)}
  for r in snap['rows']:
   if r['handle'] in chosen or r['type']!='INSERT':continue
   rec=r.get('record') or {};attrs={k.casefold():v for k,v in r.get('attributes',{}).items()};existing_tag=attrs.get(str(mapping.get('tag','')).casefold(),rec.get('tag'))
   if existing_tag not in planned:continue
   compatible=False
   if numbering=='type' and rec.get('numbering','type')=='type':
    try:compatible=opening_signature(kind,opening_data(r,mapping,mm if attribute_units=='model' else 1),extras)==planned[existing_tag]
    except ValueError:pass
   if not compatible:raise ValueError('门窗编号与未选对象冲突: '+str(existing_tag))
  for row,tag,data in zip(blocks,tags,values):
   data=dict(data,tag=tag);rec=g.record('door_window',group,mm,opening_kind=kind,tag=tag,numbering=numbering,type_fields=extras,mapping=mapping,attribute_units=attribute_units,source_values=data,label_offset=label_offset)
   u={'handle':row['handle'],'record':rec}
   if mapping.get('tag'):u['attributes']={mapping['tag']:tag}
   updates.append(u);at=[row['position'][i]+label_offset[i] for i in (0,1)];z=row['position'][2]
   label_rows=[r for r in snap['rows'] if (r.get('record') or {}).get('kind')=='door_window_label' and r['record'].get('source')==row['handle']]
   label_rec=g.record('door_window_label',group,mm,source=row['handle'],tag=tag)
   if label_rows:
    for r in label_rows:updates.append({'handle':r['handle'],'text':tag,'position':[*at,z],'record':label_rec})
   else:
    e=g.text(tag,at,g.positive(text_height_mm,'text_height')/mm,layer,label_rec);e['position'][2]=z;entities.append(e)
   summary.append({'handle':row['handle'],'kind':kind,**data})
  return await present(s,ctx,snap,{'entities':entities,'updates':updates,'result':{'items':summary,'numbering':numbering,'warnings':warnings}},dry_run,expected_token)

 @tool('schedule_update','从当前门窗块属性更新关联明细和型号数量',['更新门窗表','关联明细表','门窗数量统计'])
 async def schedule_update(group:str,at:list[float],scale:Annotated[float|None,'创建默认50；更新省略沿用已记录比例']=None,layer:str='A-SCHEDULE',model_units:Literal['mm','cm','m','inch','ft']|None=None,dry_run:bool=True,expected_token:str|None=None,ctx:Context=None)->dict:
  """重读已标识源块，按当前属性更新宽高/自定义字段/编号及标签位置。型号模式汇总同规格数量；实例模式保留逐门窗行。同编号不同规格或源块删除时拒绝。表格按group原位更新；行列数或比例改变时按记录版式重建，句柄可能变化。"""
  snap=await snapshot(s,ctx);mm=factor(snap,model_units);blocks=[r for r in snap['rows'] if (r.get('record') or {}).get('kind')=='door_window' and r['record']['group']==group];updates=[];buckets={};sources={r['handle'] for r in blocks}
  dangling=[r['handle'] for r in snap['rows'] if (r.get('record') or {}).get('kind')=='door_window_label' and r['record']['group']==group and r['record']['source'] not in sources]
  if dangling:raise ValueError('源块已删除，需处理孤立标签: '+','.join(dangling))
  if not blocks:raise ValueError('该组没有已标识门窗')
  custom=sorted({k for row in blocks for k in row['record']['mapping'] if k not in ['tag','width','height','sill']})
  for row in blocks:
   rec=row['record'];data=opening_data(row,rec['mapping'],mm if rec['attribute_units']=='model' else 1);tag=data.get('tag',rec['tag']);kind=rec['opening_kind'];mode=rec.get('numbering','instance');sig=opening_signature(kind,data,custom)
   if not tag.strip():raise ValueError('门窗编号为空')
   if tag in buckets:
    bucket=buckets[tag]
    if mode!='type' or bucket['mode']!='type' or bucket['signature']!=sig:raise ValueError('同编号的门窗规格冲突或实例重号: '+tag)
    bucket['handles'].append(row['handle'])
   else:buckets[tag]={'mode':mode,'signature':sig,'data':data,'kind':kind,'handles':[row['handle']]}
   updates.append({'handle':row['handle'],'record':dict(rec,tag=tag,source_values=data)})
   for label in snap['rows']:
    if (label.get('record') or {}).get('kind')=='door_window_label' and label['record'].get('source')==row['handle']:
     at_label=[row['position'][i]+rec.get('label_offset',[0,0])[i] for i in (0,1)];updates.append({'handle':label['handle'],'text':tag,'position':[*at_label,row['position'][2]],'record':dict(label['record'],tag=tag)})
  rows=[]
  for tag,bucket in sorted(buckets.items()):
   data=bucket['data'];rows.append([tag,'门' if bucket['kind']=='door' else '窗',f"{data['width']:g}",f"{data['height']:g}",str(data.get('sill','')),*[str(data.get(k,'')) for k in custom],str(len(bucket['handles']))])
  display_labels={'material':'材质','fire_rating':'防火等级','remarks':'备注','category':'类别'}
  cells=[['编号','类型','宽(mm)','高(mm)','窗台(mm)',*[display_labels.get(k,k) for k in custom],'数量']]+rows
  tables=[r for r in snap['rows'] if (r.get('record') or {}).get('kind')=='opening_schedule' and r['record']['group']==group]
  if len(tables)>1:raise ValueError('同组存在多个关联表，请保留一个后重试')
  effective_scale=g.positive(scale if scale is not None else tables[0]['record'].get('scale',50) if tables else 50,'scale')
  entities=[];rec=g.record('opening_schedule',group,mm,sources=sorted(sources),scale=effective_scale);rebuilt=False
  if tables:
   old=tables[0];old_cells=old.get('cells',[])
   same_shape=len(old_cells)==len(cells) and bool(old_cells) and len(old_cells[0])==len(cells[0])
   if same_shape and effective_scale==old['record'].get('scale',50):updates.append({'handle':old['handle'],'cells':cells,'record':rec})
   else:
    rebuilt=True;updates.append({'handle':old['handle'],'delete':True});e=g.table(cells,old['position'],mm,effective_scale,old['layer'],rec)
    for field in ['color','linetype','lineweight']:
     if field in old:e[field]=old[field]
    entities=[e]
  else:entities=[g.table(cells,at,mm,effective_scale,layer,rec)]
  return await present(s,ctx,snap,{'entities':entities,'updates':updates,'result':{'rows':rows,'instance_count':len(blocks),'schedule_rows':len(rows),'rebuilt_table':rebuilt,'custom_columns':custom,'sources_by_tag':{tag:b['handles'] for tag,b in buckets.items()}}},dry_run,expected_token)

 @tool('area_schedule','按项目规则计算面积、扣减并按楼层分区汇总',['建筑面积','计容面积','面积汇总'],'destructive')
 async def area_schedule(zones:Annotated[list[dict],'[{id,name,floor,zone,rule,boundary:坐标多边形或boundary_handle, deductions:[多边形]}]'],rules:Annotated[dict,'规则名→{factor:非负系数,basis:依据说明,version:版本}'],group:str,at:list[float],scale:float=50,layer:str='A-AREA-SCHEDULE',replace:bool=False,model_units:Literal['mm','cm','m','inch','ft']|None=None,dry_run:bool=True,expected_token:str|None=None,ctx:Context=None)->dict:
  """边界使用图纸单位；扣减区取并集防重复扣减，同层区域重叠拒绝。结果m²。规则由用户明确提供，不自动判断法定面积；支持已有闭合直线多段线边界。"""
  snap=await snapshot(s,ctx);mm=factor(snap,model_units);resolved=[]
  for zone in zones:
   z=dict(zone)
   if 'boundary_handle' in z:z['boundary']=list(g.polygon_row(selected(snap,[z['boundary_handle']])[0]).exterior.coords)[:-1]
   resolved.append(z)
  result=g.area_rows(resolved,rules,mm);cells=[['区域','楼层','分区','净面积m²','系数','计入m²']]+[[r['name'] or r['id'],r['floor'],r['zone'],f"{r['net_m2']:.3f}",f"{r['factor']:g}",f"{r['counted_m2']:.3f}"] for r in result['rows']]+[[f'合计:{kind}','','','','',f'{value:.3f}'] for kind,value in result['totals_by_type_m2'].items()]
  plan={'entities':[g.table(cells,at,mm,g.positive(scale,'scale'),layer,g.record('area_schedule',group,mm,zones=resolved,rules=rules))],'updates':g.replacement(snap['rows'],'area_schedule',group,replace),'result':result}
  return await present(s,ctx,snap,plan,dry_run,expected_token)

 @tool('column_place','按点位或直轴交点布置圆柱和矩形柱',['柱网落柱','布置柱'],'destructive')
 async def column_place(group:str,width_mm:float,depth_mm:float,points:list[list[float]]|None=None,axis_handles:list[str]|None=None,shape:Literal['rectangle','circle']='rectangle',rotation_deg:float=0,layer:str='A-COLUMN',replace:bool=False,model_units:Literal['mm','cm','m','inch','ft']|None=None,dry_run:bool=True,expected_token:str|None=None,ctx:Context=None)->dict:
  """尺寸毫米，点位为图纸WCS单位。axis_handles模式取有限直线轴网交点，重合轴拒绝；记录柱尺寸和来源轴网。"""
  snap=await snapshot(s,ctx);mm=factor(snap,model_units)
  if (points is None)==(axis_handles is None):raise ValueError('points与axis_handles二选一')
  if axis_handles:
   from shapely.geometry import LineString
   axes=selected(snap,axis_handles);points=[]
   if any(a['type']!='LINE' for a in axes):raise ValueError('落柱轴线须为直线')
   for i,a in enumerate(axes):
    for b in axes[i+1:]:
     inter=LineString([p[:2] for p in a['points']]).intersection(LineString([p[:2] for p in b['points']]))
     if inter.is_empty:continue
     if inter.geom_type!='Point':raise ValueError('轴线重合')
     p=[inter.x,inter.y]
     if not any(math.dist(p,q)<1e-9 for q in points):points.append(p)
  plan=g.columns_plan(points or [],width_mm,depth_mm,shape,rotation_deg,mm,group,layer);plan['updates']=g.replacement(snap['rows'],'column',group,replace)
  for e in plan['entities']:e['record']['source_axes']=axis_handles or []
  return await present(s,ctx,snap,plan,dry_run,expected_token)

 @tool('beam_place','沿直轴绘制梁平面边界并记录宽度',['绘制梁','梁边线'],'destructive')
 async def beam_place(axes:list[list[list[float]]],width_mm:float,group:str,layer:str='A-BEAM',replace:bool=False,model_units:Literal['mm','cm','m','inch','ft']|None=None,dry_run:bool=True,expected_token:str|None=None,ctx:Context=None)->dict:
  """每根梁提供两个WCS端点（图纸单位），宽度毫米；生成闭合平面边界，保留轴线记录。"""
  snap=await snapshot(s,ctx);plan=g.beams_plan(axes,width_mm,factor(snap,model_units),group,layer);plan['updates']=g.replacement(snap['rows'],'beam',group,replace);return await present(s,ctx,snap,plan,dry_run,expected_token)

 @tool('wall_join','预览并处理墙面角点或柱墙收口',['柱墙收口','墙线连接'],'destructive')
 async def wall_join(handles:list[str],group:str,mode:Literal['corner','columns'],ends:list[int]=[1,0],column_handles:list[str]|None=None,max_shift_mm:float=1000,model_units:Literal['mm','cm','m','inch','ft']|None=None,dry_run:bool=True,expected_token:str|None=None,ctx:Context=None)->dict:
  """corner将两条墙面线指定端点延伸/修剪到交点；columns从直线墙面或本工具生成的闭合梁边界中扣除柱范围，可能拆分并产生新句柄；闭合梁使用多边形柱。保留图层/颜色/线型/线宽并记录关联。拒绝锁层及既有ACADMCP_ARCH墙记录。"""
  snap=await snapshot(s,ctx);plan=g.wall_join_plan(selected(snap,handles),selected(snap,column_handles) if column_handles else [],mode,ends,g.positive(max_shift_mm,'max_shift'),factor(snap,model_units),group);return await present(s,ctx,snap,plan,dry_run,expected_token)

 @tool('ramp_draw','按路径和标高绘制坡道平面及坡度标注',['绘制坡道','坡度标注'],'destructive')
 async def ramp_draw(path:list[list[float]],width_mm:float,elevations_mm:list[float],group:str,landings:Annotated[list[dict]|None,'[{boundary:图纸坐标,elevation_mm:标高}]']=None,max_slope:float|None=None,layer:str='A-RAMP',replace:bool=False,model_units:Literal['mm','cm','m','inch','ft']|None=None,dry_run:bool=True,expected_token:str|None=None,ctx:Context=None)->dict:
  """各路径点对应标高，标高和宽度毫米；可提供最大坡度比例（如0.08）。平台边界和标高由用户提供，输出分段坡度与关联记录。"""
  snap=await snapshot(s,ctx);plan=g.ramp_plan(path,width_mm,elevations_mm,landings or [],factor(snap,model_units),group,layer,max_slope);plan['updates']=g.replacement(snap['rows'],'ramp_',group,replace);return await present(s,ctx,snap,plan,dry_run,expected_token)

 @tool('stair_check','按给定规则检查梯段尺寸和断面净高',['楼梯检查','净高校核'],'read')
 async def stair_check(risers:int,riser_height_mm:float,going_mm:float,width_mm:float,limits:Annotated[dict,'字段→{min,max}；riser_height_mm/going_mm/width_mm/blondel_mm/headroom_mm'],profile:Annotated[list[list[float]]|None,'断面[里程mm,完成面标高mm]，可表达多梯段和平台']=None,obstacles:Annotated[list[dict]|None,'[{id,start_mm,end_mm,underside_mm}] 梁板底在断面中的范围']=None,ctx:Context=None)->dict:
  """只计算不改图，规则需用户给定。净高取障碍覆盖区间内最不利值；缺断面或障碍时headroom_complete=false，不能当作已完成净高校核。"""
  return g.stair_check(risers,riser_height_mm,going_mm,width_mm,limits,profile,obstacles or [])
