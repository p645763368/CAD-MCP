"""Canonical millimetre adapter for existing architectural generators."""
from __future__ import annotations
from contextvars import ContextVar
from dataclasses import replace,is_dataclass
from typing import Annotated,Literal
import copy,inspect,functools,math
from fastmcp import Context
from engineering.arch import model
from engineering.building import FACTORS

ACTIVE=ContextVar('building_unit_backend',default=None)
POSITION_KEYS={'start','end','center','insertion','position','alignment_point','centroid','at','start_point','end_point','p1','p2','text_position','dim_line_point'}
POINT_LIST_KEYS={'points','vertices','axis','outer','boundary','loop'}
LENGTH_KEYS={'length','radius','height','char_height','text_height','width','perimeter','measurement'}

def transform_properties(data,k):
 result=copy.deepcopy(data)
 for key,value in list(result.items()):
  if key in POSITION_KEYS and isinstance(value,(list,tuple)) and value and all(isinstance(x,(float,int)) for x in value):result[key]=[x*k for x in value]
  elif key in POINT_LIST_KEYS and isinstance(value,(list,tuple)):result[key]=[[float(x)*k for x in p] for p in value]
  elif key=='holes' and isinstance(value,(list,tuple)):result[key]=[[[float(x)*k for x in p] for p in loop] for loop in value]
  elif key in LENGTH_KEYS and isinstance(value,(int,float)):result[key]=value*k
  elif key=='area' and isinstance(value,(int,float)):result[key]=value*k*k
  elif key in {'bounding_box','bbox','geometry_bbox'} and isinstance(value,dict):result[key]={a:[float(v)*k for v in p] for a,p in value.items()}
 return result

def scale_payload(payload,k):
 data=copy.deepcopy(payload);kind=data['kind']
 if kind=='wall':data['axis']=[[v*k for v in p] for p in data['axis']];data['thickness']*=k
 elif kind=='opening':
  for name in ['offset','width','height','sill']:
   if data.get(name) is not None:data[name]*=k
 elif kind=='stair':
  data['start']=[v*k for v in data['start']]
  for name in ['width','riser_height','going']:data[name]*=k
 elif kind=='room':data['at']=[v*k for v in data['at']];data['area']=float(data.get('area',0))*k*k
 return data

class UnitBackend:
 def __init__(self,base,mm,identity=None,scale=50):self.base=base;self.mm=mm;self.identity=identity;self.plot_scale=scale;self._canonical_mm=True
 def __getattr__(self,name):
  original=getattr(self.base,name)
  if name=='_run':
   async def run(fn,*args,**kwargs):
    if getattr(fn,'__name__','')=='room_factor_sync':return 1.
    return await original(fn,*args,**kwargs)
   return run
  if not inspect.iscoroutinefunction(original):return original
  signature=inspect.signature(original)
  async def call(*args,**kwargs):
   if self.identity is not None and hasattr(self.base,'_run'):
    from backends import com_backend as com
    current=await self.base._run(lambda:str(com._acad_doc().FullName or com._acad_doc().Name))
    if current!=self.identity:raise ValueError('活动图纸已改变，停止建筑操作')
   bound=signature.bind(*args,**kwargs);values=bound.arguments
   if name=='entity_set_xdata' and values.get('app_name')==model.APP_ID:
    data=model.decode(values['values']);data.update(coordinate_units='mm',model_mm_per_unit=self.mm);values['values']=model.to_values(data)
   elif name=='block_insert':
    for key in ['x','y']:
     if key in values:values[key]/=self.mm
    values['scale_x']=values.get('scale_x',1)/self.mm;values['scale_y']=values.get('scale_y',1)/self.mm
   elif name=='entity_move':
    for key in ['dx','dy','dz']:
     if key in values:values[key]/=self.mm
   elif name=='entity_edit_geometry':
    params=values.get('kwargs',{})
    for key in ['x1','y1','z1','x2','y2','z2','cx','cy','radius','height']:
     if key in params:params[key]/=self.mm
   elif name.startswith(('entity_create_','dimension_')):
    for key in ['x','y','z','x1','y1','z1','x2','y2','z2','cx','cy','radius','height','width','row_height','text_height','dim_x','dim_y','distance','length']:
     if key in values and values[key] is not None:values[key]=float(values[key])/self.mm
    for key in ['points','boundary_points']:
     if key in values:values[key]=[[float(v)/self.mm for v in p] for p in values[key]]
    if values.get('column_widths') is not None:values['column_widths']=[float(x)/self.mm for x in values['column_widths']]
    if name=='entity_create_hatch':values['scale']=float(values.get('scale',1))/self.mm
   elif name=='hatch_add_boundary':
    edges=[]
    for edge in values['edges']:
     edge=dict(edge)
     for k in ['start','end','center']:
      if k in edge:edge[k]=[float(x)/self.mm for x in edge[k]]
     if 'radius' in edge:edge['radius']/=self.mm
     edges.append(edge)
    values['edges']=edges
   if name=='drawing_critique':
    from engineering.critique import run_critique
    await self.base._ensure_document_state()
    answer=await run_critique(self,values.get('focus'))
   else:answer=await original(*bound.args,**bound.kwargs)
   if name=='entity_get_xdata':
    apps=answer.get('xdata',{});rows=apps.get(model.APP_ID,[])
    if rows:
     payload=model.decode(rows)
     if 'coordinate_units' not in payload:
      if self.mm!=1:raise ValueError('旧建筑记录没有单位标识，请先用arch_units_migrate明确迁移')
     elif payload.get('coordinate_units')!='mm' or not math.isclose(float(payload.get('model_mm_per_unit',0)),self.mm):raise ValueError('建筑记录单位与当前图纸单位不一致，请核对并迁移')
   if name.startswith('dimension_') and hasattr(answer,'handle') and hasattr(self.base,'_run'):
    from backends import com_backend as com
    from arch_deep_tools import PROFILE
    scale=float(PROFILE.get().get('plot_scale',self.plot_scale))
    def adjust():
     e=com._com_unnarrow(com._acad_doc().HandleToObject(answer.handle));e.LinearScaleFactor=self.mm;e.ScaleFactor=scale/self.mm;e.TextHeight=2.5;e.ArrowheadSize=2.5;e.PrimaryUnitsPrecision=0;e.Update()
    await self.base._run(adjust)
   if name in ['entity_get','entity_list'] or name.startswith(('entity_create_','dimension_')) or name=='block_insert':
    def convert(row):return replace(row,properties=transform_properties(row.properties or {},self.mm)) if is_dataclass(row) and hasattr(row,'properties') else row
    return [convert(r) for r in answer] if isinstance(answer,list) else convert(answer)
   return answer
  return call

def scale_input(name,args,mm):
 args=copy.deepcopy(args)
 for key in ['x','y','start_x','start_y']:
  if key in args:args[key]*=mm
 if name=='arch_wall':
  for wall in args['walls']:wall['axis']=[[float(v)*mm for v in p] for p in wall['axis']]
 if name=='arch_symbol' and isinstance(args.get('params'),dict):
  for key in ['p1','p2']:
   if key in args['params']:args['params'][key]=[float(v)*mm for v in args['params'][key]]
 if name=='arch_plan_from_spec':
  spec=args['spec']
  for w in spec.get('walls',[]):w['axis']=[[float(v)*mm for v in p] for p in w['axis']]
  for st in spec.get('stairs',[]):st['start']=[float(v)*mm for v in st['start']]
  for room in spec.get('rooms',[]):room['at']=[float(v)*mm for v in room['at']]
  for schedule in spec.get('schedules',[]):schedule['at']=[float(v)*mm for v in schedule['at']]
 return args

def output_coordinates(value,mm):
 if isinstance(value,list):return [output_coordinates(v,mm) for v in value]
 if not isinstance(value,dict):return value
 result={}
 for key,v in value.items():
  if key in POSITION_KEYS and isinstance(v,(list,tuple)) and v and all(isinstance(x,(int,float)) for x in v):result[key]=[x/mm for x in v]
  elif key in POINT_LIST_KEYS and isinstance(v,(list,tuple)) and v and isinstance(v[0],(list,tuple)):result[key]=[[x/mm for x in p] for p in v]
  elif key=='holes' and isinstance(v,list):result[key]=[[[x/mm for x in p] for p in loop] for loop in v]
  elif key=='area' and isinstance(v,(float,int)):result[key]=v/mm/mm
  elif key=='mm_per_unit':result[key]=mm
  else:result[key]=output_coordinates(v,mm)
 return result

def register(s):
 original_backend=s._backend
 def backend(ctx):return ACTIVE.get() or original_backend(ctx)
 s._backend=backend
 targets={'arch_wall','arch_opening','arch_stair','arch_room','arch_schedule','arch_symbol','arch_catalogue_insert','arch_dimension_chains','arch_plan_from_spec','arch_rooms_detect','drawing_critique','drawing_refine'}
 for t in s._local_tool_components():
  if t.name not in targets:continue
  fn=t.fn;signature=inspect.signature(fn);name=t.name
  def wrap(fn,signature,name):
   @functools.wraps(fn)
   async def wrapped(*args,**kwargs):
    override=kwargs.pop('model_units',None);bound=signature.bind_partial(*args,**kwargs);ctx=bound.arguments.get('ctx');base=original_backend(ctx)
    if not hasattr(base,'_run'):
     if override not in [None,'mm']:raise ValueError('无界面建筑生成目前只支持毫米')
     return await fn(*args,**kwargs)
    from project_fixes import required_context
    state=await base._run(required_context,override);mm=state['mm_per_unit'];identity=state['document']
    if not identity:
     from backends import com_backend as com
     identity=await base._run(lambda:str(com._acad_doc().Name))
    proxy=UnitBackend(base,mm,identity,float(bound.arguments.get('scale') or 50))
    values={k:v for k,v in bound.arguments.items() if k!='ctx'};values=scale_input(name,values,mm);values['ctx']=ctx
    token=ACTIVE.set(proxy)
    try:result=await fn(**values)
    finally:ACTIVE.reset(token)
    result=output_coordinates(result,mm)
    if isinstance(result,dict):result['unit_context']=state
    return result
   params=list(signature.parameters.values());idx=next((i for i,p in enumerate(params) if p.name=='ctx'),len(params));params.insert(idx,inspect.Parameter('model_units',inspect.Parameter.POSITIONAL_OR_KEYWORD,default=None,annotation=str|None));wrapped.__signature__=signature.replace(parameters=params)
   return wrapped
  t.fn=wrap(fn,signature,name)
  t.parameters['properties']['model_units']={'anyOf':[{'type':'string','enum':list(FACTORS)},{'type':'null'}],'default':None,'description':'显式实际模型单位；null读取INSUNITS。坐标采用图纸单位，构件尺寸/偏移/高度仍为毫米。'}
  for key in ['x','y','start_x','start_y']:
   if key in t.parameters['properties']:t.parameters['properties'][key]['description']='WCS坐标，采用实际图纸单位。'
  if 'walls' in t.parameters['properties']:t.parameters['properties']['walls']['description']='墙列表：axis为WCS图纸单位坐标；thickness为毫米。其他字段按原定义。'
  t.description='\n'.join(line for line in t.description.splitlines() if not line.startswith(('单位前置检查','单位适配：')))+'\n单位：坐标采用图纸单位，构件尺寸使用毫米；内部毫米计算后换算写入。新记录保存单位标记，非毫米旧记录需显式迁移。'
  if t.meta and 'cad' in t.meta:t.meta['cad']['limits']=t.description;t.meta['cad']['catalog_revision']='2026-11-27.p01'

 from building_tools import snapshot,selected,present
 from engineering.building_checks import factor
 async def arch_units_migrate(source_record_units:Literal['mm','model'],handles:Annotated[list[str]|None,'要迁移的ACADMCP_ARCH载体句柄；null读取全部模型记录']=None,model_units:Literal['mm','cm','m','inch','ft']|None=None,dry_run:bool=True,expected_token:str|None=None,ctx:Context=None)->dict:
  """只转换建筑记录中的数值及单位标识，不缩放任何几何。source_record_units由用户确认：mm保留原数值，model将记录长度/坐标按实际模型单位换算为毫米；执行必须带预览token。"""
  snap=await snapshot(s,ctx);mm=factor(snap,model_units);rows=selected(snap,handles) if handles else [r for r in snap['rows'] if r.get('arch_values')];updates=[];details=[]
  for row in rows:
   if not row.get('arch_values'):raise ValueError('对象没有建筑记录: '+row['handle'])
   old=model.decode(row['arch_values'])
   if old.get('coordinate_units')=='mm' and source_record_units=='model':raise ValueError('记录已标记毫米，不能按模型单位重复换算')
   new=scale_payload(old,1 if source_record_units=='mm' else mm);new.update(coordinate_units='mm',model_mm_per_unit=mm);model.from_payload(new)
   if new['kind']=='wall' and row.get('bbox'):
    xs=[p[0]/mm for p in new['axis']];ys=[p[1]/mm for p in new['axis']];margin=2*new['thickness']/mm
    lo,hi=row['bbox']['min'],row['bbox']['max']
    if lo[0]<min(xs)-margin or hi[0]>max(xs)+margin or lo[1]<min(ys)-margin or hi[1]>max(ys)+margin:raise ValueError('记录与墙体位置不匹配，需先核对源记录单位: '+row['handle'])
   updates.append({'handle':row['handle'],'arch_values':model.to_values(new)});details.append({'handle':row['handle'],'before':old,'after':new})
  if not updates:raise ValueError('没有需要迁移的建筑记录')
  return await present(s,ctx,snap,{'entities':[],'updates':updates,'result':{'records':details,'geometry_scaled':False}},dry_run,expected_token)
 s.mcp.tool(name='arch_units_migrate',description='预览并迁移旧建筑记录的单位标识。\n'+arch_units_migrate.__doc__,annotations={'readOnlyHint':False,'destructiveHint':False},meta={'cad':{'summary':'迁移建筑记录单位','risk':'write','cost':'mutate','zh_aliases':['建筑单位迁移','旧记录单位','米制建筑'],'catalog_revision':'2026-11-27.p01'}},tags={'arch'})(arch_units_migrate)
