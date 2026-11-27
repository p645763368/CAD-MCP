from typing import Annotated,Literal
from fastmcp import Context
from contextvars import ContextVar
from collections.abc import Mapping
import functools,inspect,json
import arch_tools

def polyline_corner_sync(handle,index,kind,size1,size2=None):
 from backends import com_backend as com
 from backends.corner_geometry import corner_plan
 import math
 d=com._acad_doc();e=com._com_unnarrow(d.HandleToObject(handle))
 if e.ObjectName!='AcDbPolyline' or math.dist(tuple(e.Normal),(0,0,1))>1e-9:raise ValueError('仅支持法向+Z的LWPOLYLINE')
 coords=tuple(e.Coordinates);n=len(coords)//2;closed=bool(e.Closed)
 if index<0 or index>=n or (not closed and index in [0,n-1]):raise ValueError('必须选择有前后两段的内部顶点')
 prev=(index-1)%n;nxt=(index+1)%n
 for i in [prev,index]:
  if abs(e.GetBulge(i))>1e-10:raise ValueError('相邻两段须为直线；相邻圆弧暂不支持')
  if any(abs(x)>1e-10 for x in e.GetWidth(i)):raise ValueError('相邻两段须为零宽，避免改变宽线轮廓')
 def pt(i):return (coords[2*i],coords[2*i+1],float(e.Elevation))
 a,v,b=pt(prev),pt(index),pt(nxt)
 plan=corner_plan(a,v,v,b,kind,float(size1),size2,True)
 if kind=='fillet' and size1<=0:raise ValueError('多段线圆角半径须大于0')
 incoming=(v[0]-a[0],v[1]-a[1]);outgoing=(b[0]-v[0],b[1]-v[1]);turn=math.atan2(incoming[0]*outgoing[1]-incoming[1]*outgoing[0],incoming[0]*outgoing[0]+incoming[1]*outgoing[1])
 bulge=math.tan(turn/4) if kind=='fillet' else 0
 edits=[{'action':'set','index':index,'point':list(plan['tangent1']),'bulge':bulge},{'action':'insert','index':index+1,'point':list(plan['tangent2']),'bulge':0}]
 if tuple(e.Coordinates)!=coords:raise ValueError('多段线在计算期间发生变化，请重新读取')
 result=arch_tools.dispatch('polyline_edit',handle=handle,edits=edits)
 result['corner']={'kind':kind,'index':index,'size1':size1,'size2':size2,'bulge':bulge,'tangent_points':[plan['tangent1'],plan['tangent2']]}
 return result

PROFILE=ContextVar('cad_arch_profile',default={})
def annotation_sync(**args):
 if args.get('scales') is not None:
  from backends import com_backend as com
  d=com._acad_doc()
  for h in args['handles']:
   e=com._com_unnarrow(d.HandleToObject(h))
   if e.ObjectName=='AcDbBlockReference':raise ValueError('暂不支持写入块参照的注释比例；需处理块定义的注释性，当前只支持TEXT/MTEXT/DIMENSION。未执行写入。')
 return arch_tools.dispatch('annotation_scales',**args)
class RoleLayers(Mapping):
 def __init__(self,base):self.base=dict(base)
 def __getitem__(self,key):return PROFILE.get().get('role_layers',{}).get(key,self.base[key])
 def __iter__(self):return iter(self.base)
 def __len__(self):return len(self.base)

def install_profile_context(s):
 from engineering.arch import layers,materials
 if not isinstance(layers.ARCH_ROLE_LAYER,RoleLayers):
  old=layers.ARCH_ROLE_LAYER;new=RoleLayers(old);layers.ARCH_ROLE_LAYER=new
  import sys
  for name,module in list(sys.modules.items()):
   if name.startswith('engineering.') and getattr(module,'ARCH_ROLE_LAYER',None) is old:setattr(module,'ARCH_ROLE_LAYER',new)
  original_hatch=materials.wall_hatch
  def hatch(material):
   base=original_hatch(material);override=PROFILE.get().get('material_hatches',{}).get(materials.normalise_material(material),{})
   return {**base,**{k:override[k] for k in ['pattern','angle','scale'] if k in override}}
  materials.wall_hatch=hatch
 for t in s._local_tool_components():
  if t.name not in ['arch_wall','arch_opening','arch_stair','arch_room','arch_rooms_detect','arch_schedule','arch_grid','arch_symbol','arch_catalogue_insert','arch_dimension_chains','arch_plan_from_spec']:continue
  original=t.fn;signature=inspect.signature(original)
  def wrap(fn,signature):
   @functools.wraps(fn)
   async def wrapped(*args,**kw):
    bound=signature.bind_partial(*args,**kw);ctx=bound.arguments.get('ctx');backend=s._backend(ctx)
    if not hasattr(backend,'_run'):return await fn(*args,**kw)
    state=await backend._run(arch_tools.dispatch,'arch_profile_config');profile=state.get('settings',{})
    if profile.get('textstyle') or profile.get('dimstyle'):
     # Read current choices and validate the saved names; never silently switch
     # user settings merely because a query is called. Drawing setup is explicit.
     pass
    if 'lang' in signature.parameters and bound.arguments.get('lang') is None:kw['lang']=profile.get('default_language',signature.parameters['lang'].default)
    if 'scale' in signature.parameters and bound.arguments.get('scale') is None:kw['scale']=profile.get('plot_scale',signature.parameters['scale'].default)
    if fn.__name__=='arch_plan_from_spec' and 'spec' in kw:
     spec=dict(kw['spec'])
     if profile.get('default_language'):spec.setdefault('lang',profile['default_language'])
     if profile.get('plot_scale') and isinstance(spec.get('sheet'),dict):spec['sheet']=dict(spec['sheet']);spec['sheet'].setdefault('scale',profile['plot_scale'])
     kw['spec']=spec
    token=PROFILE.set(profile)
    try:return await fn(*args,**kw)
    finally:PROFILE.reset(token)
   params=[p.replace(default=None,annotation=str|None if p.name=='lang' else float|None) if p.name in ['lang','scale'] else p for p in signature.parameters.values()]
   wrapped.__signature__=signature.replace(parameters=params)
   return wrapped
  t.fn=wrap(original,signature)
  for key in ['lang','scale']:
   if key in t.parameters.get('properties',{}):
    t.parameters['properties'][key]={'anyOf':[{'type':'string' if key=='lang' else 'number'},{'type':'null'}],'default':None,'description':'省略/null使用当前DWG保存的建筑配置，未配置时保持原默认值；lang=zh/en/tr；scale为正的出图比例分母。'}
  t.description+='\n自动读取当前DWG内建筑配置：角色图层映射、材料填充、默认语言/比例；未配置则使用原默认值。'
 for t in s._local_tool_components():
  if t.name not in ['layer_rename','layer_merge']:continue
  fn=t.fn;sig=inspect.signature(fn);name=t.name
  def guard(fn,sig,name):
   @functools.wraps(fn)
   async def wrapped(*args,**kw):
    bound=sig.bind_partial(*args,**kw);backend=s._backend(bound.arguments.get('ctx'))
    if hasattr(backend,'_run'):
     state=await backend._run(arch_tools.dispatch,'arch_profile_config');mapped={v.lower() for v in state.get('settings',{}).get('role_layers',{}).values()}
     sources=[bound.arguments.get('old','')] if name=='layer_rename' else bound.arguments.get('sources',[])
     if any(n.lower() in mapped for n in sources):raise ValueError('源图层被当前建筑角色配置引用；此操作会使记录失联，需先执行明确的角色迁移方案，当前拒绝修改。')
    return await fn(*args,**kw)
   return wrapped
  t.fn=guard(fn,sig,name);t.description+='\n若源图层被当前建筑角色配置引用，拒绝改名/归并，避免记录失联。'

def register(s):
 async def run(ctx,op,**args):
  b=s._backend(ctx)
  if not hasattr(b,'_run'):raise ValueError('Only AutoCAD 2026 COM backend supported')
  if op=='annotation_scales':return await b._run(annotation_sync,**args)
  return await b._run(arch_tools.dispatch,op,**args)
 def tool(summary,risk,aliases):
  def wrap(fn):
   s.mcp.tool(name=fn.__name__,description=summary+'。\n'+(fn.__doc__ or '')+'\n需CadMcpArch2026V2；当前文档事务内执行，不自动保存。',annotations={'readOnlyHint':risk=='read','destructiveHint':risk=='destructive','idempotentHint':risk=='read'},meta={'cad':{'summary':summary,'limits':fn.__doc__ or '', 'cost':{'read':'read','write':'mutate','destructive':'destructive'}[risk],'risk':risk,'zh_aliases':aliases,'catalog_revision':'2026-11-11.arch2'}},tags={'architecture_edit'})(fn);return fn
  return wrap
 @tool('将多段线的直线顶点改为圆角或倒角','write',['多段线圆角','多段线倒角','圆角顶点'])
 async def polyline_corner(handle:Annotated[str,'当前空间法向+Z的轻量多段线'],index:Annotated[int,'从0起的顶点索引；开放多段线不能选首尾点'],kind:Literal['fillet','chamfer'],size1:Annotated[float,'圆角半径或沿前段的倒角距离，正数'],size2:Annotated[float|None,'倒角沿后段距离；null同size1；圆角不使用']=None,ctx:Context=None)->dict:
  """仅相邻两段均为零宽直线的顶点；保留原句柄和其他顶点，用bulge保存真实圆弧；拒绝过大尺寸、直线平角和相邻弧段。"""
  return await s._backend(ctx)._run(polyline_corner_sync,handle,index,kind,size1,size2)
 @tool('按真实交点修剪直线、弧、圆或多段线','destructive',['曲线修剪','修剪圆弧','修剪多段线'])
 async def curve_trim(handle:Annotated[str,'LINE/ARC/CIRCLE/LWPOLYLINE目标'],boundary:Annotated[str,'同高+Z XY平面LINE/ARC/CIRCLE/LWPOLYLINE有限边界'],keep_point:Annotated[list[float],'必须在目标上且不在切点的WCS保留点'],ctx:Context=None)->dict:
  """以有限边界交点分割目标，只保留包含keep_point的一个子段；删除源对象并返回新句柄，不重建外部关联。"""
  return await run(ctx,'curve_trim',handle=handle,boundary=boundary,keep_point=keep_point)
 @tool('将开放曲线指定端延伸至有限边界','write',['曲线延伸','延伸圆弧','延伸多段线'])
 async def curve_extend(handle:Annotated[str,'开放LINE/ARC/LWPOLYLINE；具体原生类型若不支持会拒绝'],boundary:Annotated[str,'同高+Z XY有限LINE/ARC/CIRCLE/LWPOLYLINE边界'],end:Literal['start','end'],ctx:Context=None)->dict:
  """只选能增长曲线且保留另一端的交点；多候选取最短新增长度；不延长边界，不支持闭合目标。"""
  return await run(ctx,'curve_extend',handle=handle,boundary=boundary,end=end)
 @tool('框选端点或顶点并预览或执行局部拉伸','write',['框选拉伸','拉伸房间','拉伸窗口'])
 async def stretch_window(corner1:Annotated[list[float],'矩形第一角WCS'],corner2:Annotated[list[float],'矩形第二角WCS'],offset:Annotated[list[float],'XY位移[x,y]或[x,y,0]'],layer:Annotated[str|None,'可选精确图层名']=None,move_fully_inside:Annotated[bool,'true时完全包围的圆/弧/块/TEXT/MTEXT整体移动；尺寸始终跳过']=False,dry_run:Annotated[bool,'默认预览；执行必须带最新preview_token']=True,expected_token:Annotated[str|None,'上次相同窗口/位移预览返回的token']=None,ctx:Context=None)->dict:
  """全当前空间数据库按WCS矩形计算，不依赖屏幕视野。LINE/LWPOLYLINE只动框内端/顶点；锁层或非法索引整体拒绝；不自动随动尺寸/约束；报告其他类型跳过。"""
  return await run(ctx,'stretch_window',corner1=corner1,corner2=corner2,offset=offset,layer=layer,move_fully_inside=move_fully_inside,dry_run=dry_run,expected_token=expected_token)
 @tool('按白名单把源实体属性匹配给目标','write',['匹配属性','格式刷','复制图形属性'])
 async def entity_match_properties(source:Annotated[str,'当前空间源实体句柄'],handles:Annotated[list[str],'1–100个目标句柄'],fields:Annotated[list[str],'显式字段：layer/color/linetype/lineweight/linetype_scale/transparency/textstyle/dimstyle'],ctx:Context=None)->dict:
  """不复制几何、内容或标注测量值；textstyle仅TEXT/MTEXT间，dimstyle仅尺寸间；任一不兼容或锁层整次拒绝。"""
  return await run(ctx,'entity_match_properties',source=source,handles=handles,fields=fields)
 @tool('按明确测量点生成连续尺寸及可选总尺寸','write',['连续尺寸链','建筑尺寸链','点列标注'])
 async def dimension_chain(points:Annotated[list[list[float]],'2–50个同高WCS测量点，按方向投影自动排序；不从图形猜点'],line_point:Annotated[list[float],'连续尺寸线经过的WCS点'],angle_deg:Annotated[float,'尺寸方向，从X轴逆时针度']=0,plot_scale:Annotated[float,'正的出图比例分母']=50,overall:Annotated[bool,'是否另加总尺寸']=False,overall_spacing:Annotated[float,'总尺寸沿方向左法向偏移的模型单位距离']=500,style:Annotated[str|None,'已有标注样式名，空用当前']=None,layer:Annotated[str|None,'已有目标图层，空用当前']=None,ctx:Context=None)->dict:
  """创建原生旋转尺寸；真实测量，不建立几何关联，不自动避碰；总尺寸只是点列首尾投影跨度。"""
  return await run(ctx,'dimension_chain',points=points,line_point=line_point,angle_deg=angle_deg,plot_scale=plot_scale,overall=overall,overall_spacing=overall_spacing,style=style,layer=layer)
 @tool('读取注释比例并设置文字或尺寸的比例上下文','write',['注释比例','注释性对象','添加注释比例'])
 async def annotation_scales(handles:Annotated[list[str],'1–100个当前空间对象句柄'],scales:Annotated[list[dict]|None,'null只读；写入列表{name,paper_units:1,drawing_units:50}；同名比例不得冲突']=None,replace:Annotated[bool,'false追加；true移除对象上其他比例，至少保留给定一项']=False,ctx:Context=None)->dict:
  """写入仅支持TEXT/MTEXT/DIMENSION；块参照写入在预检时明确拒绝，读取仍可用。会启用对象注释性；不重建尺寸几何关联。读取返回真实HasContext列表。"""
  return await run(ctx,'annotation_scales',handles=handles,scales=scales,replace=replace)
 @tool('读取或保存当前图纸的建筑角色图层与输出配置','write',['建筑图层映射','保存公司标准','建筑默认语言'])
 async def arch_profile_config(settings:Annotated[dict|None,'null读取；完整替换配置：role_layers角色→已有层，default_language zh/en/tr，plot_scale，textstyle/dimstyle已有名，material_hatches材料→{pattern,scale,angle}，source_document来源说明']=None,ctx:Context=None)->dict:
  """存入当前DWG的XRECORD；不会自动保存文件。已有ACADMCP_ARCH记录时拒绝改变图层映射，避免丢失记录；不会修改公司源模板。默认语言/比例和角色/填充用于后续arch_*调用；文字尺寸样式需用arch_company_profile显式选用。"""
  return await run(ctx,'arch_profile_config',settings=settings)
 @tool('从另一已打开图纸导入指定图层、样式或块定义','write',['导入公司标准','从模板导入图层','导入标注样式'])
 async def drawing_import_standards(source_document:Annotated[str,'源文档完整路径，必须已经打开；不读取磁盘替代内存'],layers:Annotated[list[str],'指定图层名列表']=[],textstyles:Annotated[list[str],'指定文字样式名']=[],dimstyles:Annotated[list[str],'指定尺寸样式名']=[],blocks:Annotated[list[str],'指定本地块定义名，不支持外参或布局']=[],style_prefix:Annotated[str,'给文字/尺寸样式目标名加前缀，避免同名误用；图层/块不加前缀']='',on_conflict:Literal['keep','error']='keep',ctx:Context=None)->dict:
  """源文档只读，向当前文档克隆定义及依赖，不复制模型几何。keep保留目标同名定义并报告，不保证它与源相同；error拒绝冲突；不提供覆盖。"""
  return await run(ctx,'drawing_import_standards',source_document=source_document,layers=layers,textstyles=textstyles,dimstyles=dimstyles,blocks=blocks,style_prefix=style_prefix,on_conflict=on_conflict)

 # Replace two original endpoint contracts with deeper branches; total count unchanged.
 s.mcp._local_provider.remove_tool('entity_modify_where')
 @tool('按通配条件和空间范围批量修改对象属性','write',['批量改属性','按条件归层','通配图层修改'])
 async def entity_modify_where(where:Annotated[dict,'非空layer/type/color条件；layer/type支持字符串或列表及*?通配，color整数或列表；条件之间AND'],changes:Annotated[dict,'layer/color/linetype/lineweight；目标层/线型须已存在'],dry_run:bool=True,expect_count:int|None=None,scope:Literal['current','model','paper','all']='current',include_blocks:Annotated[bool,'是否另处理本地块定义；会影响全部参照，不进入外参']=False,expected_token:Annotated[str|None,'可选预览token，检测匹配对象及旧属性改变']=None,ctx:Context=None)->dict:
  """锁层跳过并报告；include_blocks为额外范围，不限当前布局。属性块的ATTRIB不单独遍历；需要时用块属性工具。修改默认仅预览。"""
  return await run(ctx,'entity_modify_where',where=where,changes=changes,dry_run=dry_run,expect_count=expect_count,scope=scope,include_blocks=include_blocks,expected_token=expected_token)
 s.mcp._local_provider.remove_tool('entity_draw_order')
 @tool('调整当前空间或指定静态块定义的绘图顺序','write',['绘图顺序','置顶','置底','块内绘图顺序'])
 async def entity_draw_order(handles:list[str],position:Literal['top','bottom','above','below'],relative_to:str|None=None,block_name:Annotated[str|None,'空为当前空间；指定本地静态块名则handles必须是块定义内部句柄，影响全部参照']=None,ctx:Context=None)->dict:
  """块定义模式拒绝动态块、外参、布局块；不移动几何、不改变块参照；返回顺序索引。"""
  return await run(ctx,'entity_draw_order',handles=handles,position=position,relative_to=relative_to,block_name=block_name)
 install_profile_context(s)
