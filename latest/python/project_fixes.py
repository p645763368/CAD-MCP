"""Project acceptance fixes: native snapshots, viewport identity, explicit units."""
from pathlib import Path
from typing import Annotated,Literal
from fastmcp import Context
import json,time,uuid,math,functools,inspect
from cad_mcp_paths import native_dll
DLL = native_dll('CadMcpProjectFix2026')
UNITS={1:('inch',25.4),2:('ft',304.8),4:('mm',1.),5:('cm',10.),6:('m',1000.)}
FACTORS={name:mm for name,mm in UNITS.values()}

def dispatch(op,**args):
 from backends import com_backend as com
 doc=com._acad_doc();identity=str(doc.FullName or doc.Name)
 if int(doc.GetVariable('CMDACTIVE')):raise RuntimeError('AutoCAD命令未结束')
 saved=doc.GetVariable('USERS5');filedia=doc.GetVariable('FILEDIA')
 try:
  doc.SetVariable('FILEDIA',0)
  def invoke(expr):
   if str(com._acad_doc().FullName or com._acad_doc().Name)!=identity:raise RuntimeError('Active document changed')
   marker='PROJECT_PENDING_'+uuid.uuid4().hex;doc.SetVariable('USERS5',marker)
   doc.SendCommand('(setvar "USERS5" '+expr+')\n');end=time.monotonic()+15
   while time.monotonic()<end:
    result=str(doc.GetVariable('USERS5'))
    if result!=marker:return result
    time.sleep(.02)
   raise RuntimeError('Native timeout; inspect CAD before retrying')
  if invoke('(if (member "MCPPROJECTFIX2026" (atoms-family 1)) "loaded" "missing")')!='loaded':
   if not DLL.is_file():raise RuntimeError('Missing project fix DLL')
   doc.SendCommand('(command "_.NETLOAD" '+json.dumps(str(DLL).replace('\\','/'))+')\n')
   raise RuntimeError('已请求加载CadMcpProjectFix2026.dll；确认加载一次后重试。尚未派发操作。')
  def request(op,args):
   payload=json.dumps({'op':op,'document':identity,**args},ensure_ascii=True,separators=(',',':'))
   if len(payload)>24000:raise ValueError('Request too large')
   r=json.loads(invoke('(car (MCPPROJECTFIX2026 '+json.dumps(payload)+'))'))
   if not r.get('ok'):raise ValueError(r.get('error','Native failure'))
   return r
  r=request(op,args)
  if 'token' in r:
   text=r['data'];token=r['token'];length=r['length']
   while len(text)<length:
    part=request('chunk',{'token':token,'offset':len(text)})
    if part['offset']!=len(text) or not part['data']:raise ValueError('Invalid snapshot chunk')
    text+=part['data']
   r=json.loads(text)
  return r
 finally:
  doc.SetVariable('FILEDIA',filedia);doc.SetVariable('USERS5',saved)

def context(model_units=None,reference_length=None,reference_mm=None):
 from backends import com_backend as com
 d=com._acad_doc();code=int(d.GetVariable('INSUNITS'));declared=UNITS.get(code)
 if model_units is not None and model_units not in FACTORS:raise ValueError('model_units: mm/cm/m/inch/ft')
 name=model_units or (declared[0] if declared else None);mm=FACTORS.get(name)
 if (reference_length is None)!=(reference_mm is None):raise ValueError('reference_length和reference_mm必须同时提供')
 consistent=None;observed=None
 if reference_length is not None:
  if any(not math.isfinite(x) or x<=0 for x in [reference_length,reference_mm]):raise ValueError('参考长度必须为正有限数')
  observed=reference_mm/reference_length;consistent=mm is not None and math.isclose(mm,observed,rel_tol=.01)
 return {'ok':True,'document':str(d.FullName or d.Name),'insunits':code,'declared_units':declared[0] if declared else 'unknown','model_units':name,'mm_per_unit':mm,'source':'explicit_override' if model_units else 'INSUNITS','reference_consistent':consistent,'observed_mm_per_unit':observed,'modified':False,'warning':'INSUNITS仅为声明，不能证明实际几何单位；请用已知长度校核。'}

def required_context(model_units=None):
 state=context(model_units)
 if state['mm_per_unit'] is None:raise ValueError('图纸单位未知；先核对已知长度，再显式指定model_units，或修正drawing_set_units；不会自动缩放原图')
 return state

def install_backend():
 from backends import com_backend as com
 cls=com.COMBackend if hasattr(com,'COMBackend') else com.ComBackend
 if getattr(cls,'_project_fixed',False):return
 cls._project_fixed=True
 old_entities=cls.entity_list;old_count=cls.entity_count
 async def page(self,type_filter=None,layer_filter=None,limit=200,offset=0,fields=None):
  # Keep the existing active-layout scope. Native fast path targets model;
  # paper layouts retain the COM path and are never replaced by model rows.
  model=await self._run(lambda:bool(com._acad_doc().ActiveLayout.ModelType))
  if not model:
   from dataclasses import asdict
   rows=await old_entities(self,type_filter,layer_filter,limit,offset) if limit else []
   return {'ok':True,'rows':[asdict(x) for x in rows],'total':await old_count(self,type_filter,layer_filter),'errors':[],'snapshot':False}
  return await self._run(dispatch,'entities',type_filter=type_filter,layer_filter=layer_filter,limit=limit,offset=offset,fields=fields)
 async def entities(self,type_filter=None,layer_filter=None,limit=200,offset=0):
  r=await page(self,type_filter,layer_filter,limit,offset)
  if r['errors']:raise ValueError('原生实体属性读取不完整: '+str(r['errors']))
  return [com.EntityInfo(**x) for x in r['rows']]
 async def count(self,type_filter=None,layer_filter=None):return (await page(self,type_filter,layer_filter,0))['total']
 async def viewports(self,layout=None):return await self._run(dispatch,'viewports',layout=layout)
 async def delete(self,handle,force=False):return await self._run(dispatch,'viewport_delete',handle=handle)
 async def ordinary(self,handle):
  r=await viewports(self);row=next((v for v in r['viewports'] if v['handle'].upper()==handle.upper()),None)
  if row is None or row['is_main'] is not False:raise ValueError('主视口或身份未知，拒绝修改/删除')
  return row
 old_scale=cls.viewport_set_scale;old_lock=cls.viewport_lock;old_delete=cls.entity_delete
 async def scale(self,handle,scale):
  await ordinary(self,handle);return await old_scale(self,handle,scale)
 async def lock(self,handle,locked=True):
  await ordinary(self,handle);return await old_lock(self,handle,locked)
 async def entity_delete(self,handle):
  def vp():return com._acad_doc().HandleToObject(handle).ObjectName=='AcDbViewport'
  if await self._run(vp):return await delete(self,handle)
  return await old_delete(self,handle)
 cls.entity_page=page;cls.entity_list=entities;cls.entity_count=count
 cls.viewport_list=viewports;cls.viewport_delete=delete;cls.viewport_set_scale=scale;cls.viewport_lock=lock;cls.entity_delete=entity_delete

def register(s):
 install_backend()
 def replace(name,fn,summary,risk,aliases):
  s.mcp._local_provider.remove_tool(name)
  s.mcp.tool(name=name,description=summary+'。\n'+(fn.__doc__ or ''),annotations={'readOnlyHint':risk=='read','destructiveHint':risk=='destructive'},meta={'cad':{'summary':summary,'limits':fn.__doc__ or '', 'risk':risk,'cost':'read' if risk=='read' else 'mutate','zh_aliases':aliases,'catalog_revision':'2026-11-11.project-fix1'}})(fn)
 async def unit_context(model_units:Annotated[Literal['mm','cm','m','inch','ft']|None,'显式实际单位；null读取INSUNITS，不改单位或缩放图形']=None,reference_length:Annotated[float|None,'图上已知长度的实测图纸单位值']=None,reference_mm:Annotated[float|None,'对应真实长度，毫米；须与reference_length同时给']=None,ctx:Context=None)->dict:
  """仅诊断和返回mm_per_unit；reference_consistent=false必须先解决单位冲突。不能靠门宽或外观自动猜单位。"""
  return await s._backend(ctx)._run(context,model_units,reference_length,reference_mm)
 s.mcp.tool(name='drawing_unit_context',description='读取图纸单位并用已知长度校核；不修改图形或INSUNITS。',annotations={'readOnlyHint':True},meta={'cad':{'summary':'图纸单位与已知长度校核','risk':'read','cost':'read','zh_aliases':['米制','单位适配','单位校核','毫米换算']}})(unit_context)
 async def vp_scale(handle:Annotated[str,'普通视口句柄；主视口及未知身份拒绝'],scale:Annotated[float|None,'原始纸空间/模型数值比例；与scale_denominator二选一']=None,scale_denominator:Annotated[float|None,'物理出图比例分母，如100表示1:100；自动换算模型单位及布局纸单位']=None,model_units:Annotated[Literal['mm','cm','m','inch','ft']|None,'实际模型单位覆盖；null采用INSUNITS，仅在分母模式使用']=None,ctx:Context=None)->dict:
  """分母模式：scale=每模型单位毫米数/每纸空间单位毫米数/分母。不会改尺寸/注释；未知单位和像素纸单位拒绝。原始scale模式保留兼容性。"""
  if (scale is None)==(scale_denominator is None):raise ValueError('scale与scale_denominator必须二选一')
  b=s._backend(ctx);state=None
  if scale_denominator is not None:
   if not math.isfinite(scale_denominator) or scale_denominator<=0:raise ValueError('比例分母必须大于0')
   state=await b._run(required_context,model_units);rows=await b.viewport_list();row=next((x for x in rows['viewports'] if x['handle'].upper()==handle.upper()),None)
   if row is None or row['is_main'] is not False:raise ValueError('主视口或未知视口拒绝')
   from backends import com_backend as com
   paper=await b._run(lambda:int(com._acad_doc().Layouts.Item(row['layout']).PaperUnits))
   if paper not in [0,1]:raise ValueError('仅支持毫米或英寸纸单位')
   scale=state['mm_per_unit']/(25.4 if paper==0 else 1)/scale_denominator
  elif model_units is not None:raise ValueError('原始scale模式不使用model_units')
  if not math.isfinite(scale) or scale<=0:raise ValueError('scale必须为正有限数')
  result=await b.viewport_set_scale(handle,scale)
  if state:result.update(scale_denominator=scale_denominator,unit_context=state)
  return result
 replace('viewport_set_scale',vp_scale,'按原始数值比例或实际单位设置普通视口出图比例','write',['视口比例','米制视口','出图比例'])
 async def vp_delete(handle:Annotated[str,'普通视口句柄'],force:Annotated[bool,'保留旧参数兼容；不允许绕过主视口保护']=False,ctx:Context=None)->dict:
  """原生Layout.GetViewports识别主视口；主视口和无法确定身份的视口一律拒绝，force=true也不能绕过。普通视口事务删除。"""
  return await s._backend(ctx).viewport_delete(handle,force)
 replace('viewport_delete',vp_delete,'删除普通视口并强制保护纸空间主视口','destructive',['删除视口','主视口保护'])
 async def dims(points:Annotated[list[list[float]],'2–50个WCS模型坐标点'],line_point:Annotated[list[float],'尺寸线经过的WCS模型点'],angle_deg:float=0,plot_scale:Annotated[float,'物理比例分母，例如100']=50,overall:bool=False,overall_spacing:Annotated[float|None,'总尺寸偏移，模型单位；null采用纸上10mm×比例换算']=None,style:str|None=None,layer:str|None=None,model_units:Annotated[Literal['mm','cm','m','inch','ft']|None,'null读取INSUNITS；显式覆盖不改图纸单位']=None,paper_text_height:Annotated[float,'纸上文字/箭头高度mm，默认2.5']=2.5,ctx:Context=None)->dict:
  """按实际单位生成模型空间尺寸链；显示毫米整数、正确纸上字高；每个新尺寸独立覆盖DIMLFAC等，不改原样式。非关联尺寸。仅支持COM原生模块。"""
  if any(not math.isfinite(x) for x in [angle_deg,plot_scale,paper_text_height]) or plot_scale<=0 or paper_text_height<=0:raise ValueError('有限正比例和字高必须提供')
  b=s._backend(ctx);state=await b._run(required_context,model_units);mm=state['mm_per_unit']
  spacing=10*plot_scale/mm if overall_spacing is None else overall_spacing
  if not math.isfinite(spacing) or spacing<=0:raise ValueError('overall_spacing必须为正有限数')
  return await b._run(dispatch,'dimension_chain',points=points,line_point=line_point,angle_deg=angle_deg,plot_scale=plot_scale,overall=overall,overall_spacing=spacing,style=style,layer=layer,mm_per_unit=mm,paper_text_height=paper_text_height)
 replace('dimension_chain',dims,'按图纸实际单位创建毫米显示的尺寸链','write',['尺寸链','米制标注','单位适配标注'])
 # Existing high-level generators contain millimetre constants and serialized
 # records without unit tags: fail before writes rather than scale old records.
 guarded=set()  # Canonical unit adapter is registered by building_units.
 for t in s._local_tool_components():
  if t.name in guarded:
   fn=t.fn;sig=inspect.signature(fn)
   def guard(fn,sig):
    @functools.wraps(fn)
    async def wrapped(*args,**kw):
     b=s._backend(sig.bind_partial(*args,**kw).arguments.get('ctx'))
     if hasattr(b,'_run'):
      state=await b._run(required_context)
      if state['mm_per_unit']!=1:raise ValueError('此高级建筑工具尚限毫米模型；米制/其他单位已在写入前拒绝。可用通用实体工具、arch_rooms_detect、dimension_chain和视口分母模式；不要只改INSUNITS冒充毫米模型。')
     return await fn(*args,**kw)
    return wrapped
   t.fn=guard(fn,sig);t.description+='\n单位前置检查：当前仅毫米模型；其他/未知单位在执行前明确拒绝，不能只改INSUNITS冒充几何换算。'
  if t.name=='entity_list':
   t.description+='\n模型布局采用原生单次快照和分块回传，fields下推减少属性采集，compact不减少属性；count/total同一次快照，分页之间不是持续快照。纸布局保留原COM采集路径。'
  if t.name=='viewport_list':t.description+='\nCOM原生Layout.GetViewports识别is_main；id可为非活动编号且重开会变，持久定位用handle。'
  if t.name=='arch_rooms_detect':
   t.description+='\n单位适配：读取INSUNITS，坐标/area保持图纸单位及其平方，area_m2按实际单位换算；min_area仍为mm²、tol仍为mm。未知单位拒绝；非毫米图中的旧ACADMCP_ARCH记录无单位标记，明确拒绝猜测。外来直线闭合区域不等于法定建筑面积。'
  if t.name in guarded|{'entity_list','viewport_list','arch_rooms_detect'}:
   if t.meta and 'cad' in t.meta:
    t.meta['cad']['limits']=t.description
    t.meta['cad']['catalog_revision']='2026-11-11.project-fix1'

def room_factor_sync():return required_context()['mm_per_unit']
