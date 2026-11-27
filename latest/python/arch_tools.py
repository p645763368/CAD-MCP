"""Architectural editing endpoints, native database transactions, explicit scope."""
from typing import Annotated,Literal
from pathlib import Path
import json,time,uuid
from fastmcp import Context

from cad_mcp_paths import native_dll
DLL = native_dll('CadMcpArch2026V2Safe')
def check_join_chain(doc,handles):
 from backends import com_backend as com
 import math
 vertices=[];edges=[];degrees=[]
 def vertex(p):
  for i,v in enumerate(vertices):
   if math.dist(p,v)<=1e-7:return i
  vertices.append(p);degrees.append(0);return len(vertices)-1
 for h in handles:
  e=com._com_unnarrow(doc.HandleToObject(str(h)))
  if e.ObjectName=='AcDbPolyline':
   if e.Closed or math.dist(tuple(e.Normal),(0,0,1))>1e-9:raise ValueError('Join requires open +Z XY polylines')
   q=tuple(e.Coordinates);a=(q[0],q[1],e.Elevation);b=(q[-2],q[-1],e.Elevation)
  elif e.ObjectName in ['AcDbLine','AcDbArc']:a=tuple(e.StartPoint);b=tuple(e.EndPoint)
  else:raise ValueError('Join supports LINE/ARC/LWPOLYLINE only')
  i,j=vertex(a),vertex(b)
  if i==j:raise ValueError('Closed or degenerate source is not supported')
  edges.append((i,j));degrees[i]+=1;degrees[j]+=1
 if len(vertices)!=len(edges)+1 or degrees.count(1)!=2 or any(d>2 for d in degrees):raise ValueError('Curves must form one open endpoint chain; gaps, branches and duplicate loops refused')
 reached={0}
 while True:
  before=len(reached)
  for a,b in edges:
   if a in reached or b in reached:reached.update([a,b])
  if len(reached)==before:break
 if len(reached)!=len(vertices):raise ValueError('Curve endpoints are disconnected; no gap filling allowed')

def dispatch(op,**args):
 from backends import com_backend as com
 doc=com._acad_doc()
 if int(doc.GetVariable('CMDACTIVE')):raise RuntimeError('AutoCAD命令未结束，请完成或取消后再调用')
 if op=='curve_join':check_join_chain(doc,args['handles'])
 if not DLL.is_file():raise RuntimeError('Missing CadMcpArch2026V2Safe.dll')
 saved=doc.GetVariable('USERS5');filedia=doc.GetVariable('FILEDIA')
 try:
  doc.SetVariable('USERS5','x'*8192)
  if len(doc.GetVariable('USERS5'))!=8192:raise RuntimeError('USERS5 transport capacity is insufficient')
  doc.SetVariable('FILEDIA',0)
  def invoke(expr):
   marker='ARCH_PENDING_'+uuid.uuid4().hex;doc.SetVariable('USERS5',marker);doc.SendCommand('(setvar "USERS5" '+expr+')\n');end=time.monotonic()+15
   while time.monotonic()<end:
    result=str(doc.GetVariable('USERS5'))
    if result!=marker:return result
    time.sleep(.05)
   raise RuntimeError('Native response timed out; inspect CAD state before retrying')
  if invoke('(if (member "MCPARCH2026V2SAFE" (atoms-family 1)) "loaded" "missing")')!='loaded':
   # Loading is separated from geometry: never dispatch a write after first load.
   doc.SendCommand('(command "_.NETLOAD" '+json.dumps(str(DLL).replace('\\','/'))+')\n')
   raise RuntimeError('新原生模块已请求加载；若CAD提示请选加载一次。确认加载后重新调用，尚未派发几何操作。')
  payload={'op':op,'document':str(doc.FullName),**args};encoded=json.dumps(payload,ensure_ascii=True,separators=(',',':'))
  if len(encoded)>24000:raise ValueError('Request too large; split into smaller explicit batches')
  result=json.loads(invoke('(car (MCPARCH2026V2SAFE '+json.dumps(encoded)+'))'))
  if not result.get('ok'):raise ValueError(result.get('error','Native operation failed'))
  return result
 finally:
  doc.SetVariable('FILEDIA',filedia);doc.SetVariable('USERS5',saved)

def register(s):
 async def run(ctx,op,**args):
  b=s._backend(ctx)
  if not hasattr(b,'_run'):raise ValueError('仅支持AutoCAD 2026 COM后端')
  return await b._run(dispatch,op,**args)
 def tool(summary,risk,aliases):
  def decorate(fn):
   desc=summary+'。\n'+(fn.__doc__ or '')+'\n需CadMcpArch2026原生桥；WCS坐标，作用于活动文档；写入在数据库事务内，失败回滚，不自动保存。'
   s.mcp.tool(name=fn.__name__,description=desc,annotations={'readOnlyHint':risk=='read','destructiveHint':risk=='destructive','idempotentHint':risk=='read'},meta={'cad':{'summary':summary,'limits':fn.__doc__ or '', 'cost':{'read':'read','write':'mutate','destructive':'destructive'}[risk],'risk':risk,'zh_aliases':aliases,'catalog_revision':'2026-11-11.arch2'}},tags={'architecture_edit'})(fn)
   return fn
  return decorate
 @tool('编辑多段线顶点、弧度和宽度','write',['编辑多段线','改顶点','多段线宽度'])
 async def polyline_edit(handle:Annotated[str,'当前空间LWPOLYLINE句柄，法向须+Z'],edits:Annotated[list[dict],'按顺序执行；每项{action:set|insert|remove,index:从0起,point:[x,y,z],bulge:弧段凸度,start_width,end_width}；set字段可省略，insert须point；坐标Z等于多段线标高'],closed:Annotated[bool|None,'是否闭合；null保留']=None,ctx:Context=None)->dict:
  """保留原句柄；仅XY平面轻量多段线，拒绝零长边；不自动消除自交，不保证几何设计合理。"""
  return await run(ctx,'polyline_edit',handle=handle,edits=edits,closed=closed)
 @tool('在指定曲线上点打断曲线','destructive',['打断','分割曲线','打断多段线'])
 async def curve_split(handle:Annotated[str,'LINE/ARC/CIRCLE/LWPOLYLINE句柄'],points:Annotated[list[list[float]],'1–20个位于曲线上的WCS点；不能用附近点猜切点'],replace:Annotated[bool,'true删除源对象，false保留源对象']=True,ctx:Context=None)->dict:
  """生成子曲线并返回新句柄，核对总长度；源有外部关联时须由调用者重建关联，不能假定原标注继续关联。"""
  return await run(ctx,'curve_split',handle=handle,points=points,replace=replace)
 @tool('将首尾相连的开放曲线连接','destructive',['连接曲线','合并线段','连接多段线'])
 async def curve_join(handles:Annotated[list[str],'2–100个句柄；首个为保留目标，混合直线和圆弧应以多段线为首个'],ctx:Context=None)->dict:
  """LINE/ARC/LWPOLYLINE原生JoinEntities；全部连接成功才删除其余源；不自动补缝、不自动转多段线，返回保留句柄。"""
  return await run(ctx,'curve_join',handles=handles)
 @tool('按明确端点或顶点索引局部拉伸','write',['局部拉伸','拉伸墙线','改墙长'])
 async def entity_stretch(items:Annotated[list[dict],'1–100项{handle,indices:[索引]}；LINE端点0/1，LWPOLYLINE顶点从0起；每句柄仅一次'],offset:Annotated[list[float],'WCS位移[x,y,z]；轻量多段线仅XY位移'],ctx:Context=None)->dict:
  """只支持LINE和法向+Z的LWPOLYLINE；保留bulge及索引外顶点，不支持块/圆/尺寸自动随动；结果可能自交，调用者须读回。"""
  return await run(ctx,'entity_stretch',items=items,offset=offset)
 @tool('使用原生多边形窗口或交叉选择','read',['精确多边形选择','交叉框选','多边形框选'])
 async def selection_polygon_exact(points:Annotated[list[list[float]],'3–50个简单不自交多边形WCS顶点'],crossing:Annotated[bool,'true交叉选择；false完全包含']=True,ctx:Context=None)->dict:
  """AutoCAD Editor原生选择；只查当前空间和当前视图可选择对象，不是离屏全库查询；最多返回100句柄并报告截断。"""
  return await run(ctx,'selection_polygon_exact',points=points,crossing=crossing)
 @tool('重命名图层并保持对象引用','write',['重命名图层','图层改名'])
 async def layer_rename(old:Annotated[str,'已有源图层名；0/Defpoints/外参依赖层拒绝'],new:Annotated[str,'未使用的新图层名'],ctx:Context=None)->dict:
  """修改图层表名称；影响所有引用，旧自定义图层状态中的名字不自动迁移。"""
  return await run(ctx,'layer_rename',old=old,new=new)
 @tool('将源图层对象归并到目标图层','destructive',['合并图层','归并图层'])
 async def layer_merge(sources:Annotated[list[str],'源图层名；保护层、外参层、锁层拒绝'],target:Annotated[str,'已有未锁定目标图层'],include_blocks:Annotated[bool,'是否允许修改块定义内对象；会影响所有参照']=False,delete_sources:Annotated[bool,'true删除全部源层；源层仍被引用则整次回滚']=True,ctx:Context=None)->dict:
  """遍历模型/布局及本图块定义（包括属性），跳过外参源；不自动解锁，不自动迁移命名图层状态。"""
  return await run(ctx,'layer_merge',sources=sources,target=target,include_blocks=include_blocks,delete_sources=delete_sources)
 @tool('按精确条件批量修改对象属性','write',['批量改属性','按条件归层','统一ByLayer'])
 async def entity_modify_where(where:Annotated[dict,'非空筛选，支持layer精确层名/type为DXF类型/color为ACI；多条件AND'],changes:Annotated[dict,'允许layer/color/linetype/lineweight；目标层和线型须存在；颜色256为ByLayer'],dry_run:Annotated[bool,'true仅预览数量，false才写入']=True,expect_count:Annotated[int|None,'预览后传matched数；不一致整次拒绝']=None,ctx:Context=None)->dict:
  """当前空间，不展开块；锁层跳过并计数；数量检查不是文档修订锁，外部并发编辑仍须避开。"""
  return await run(ctx,'entity_modify_where',where=where,changes=changes,dry_run=dry_run,expect_count=expect_count)
 @tool('修改已有尺寸样式、文字位置和出图比例','write',['修改尺寸','修改标注','移动尺寸文字'])
 async def dimension_edit(handle:Annotated[str,'当前空间DIMENSION句柄'],style:Annotated[str|None,'已有标注样式名称']=None,plot_scale:Annotated[float|None,'非注释性尺寸的DIMSCALE覆盖；50表示1:50；正数']=None,text_position:Annotated[list[float]|None,'新的文字WCS位置']=None,line_point:Annotated[list[float]|None,'尺寸线WCS定位点；仅旋转/对齐尺寸']=None,ctx:Context=None)->dict:
  """不更改标注显示数值、不建立几何关联；plot_scale拒绝注释性尺寸，尚不支持注释上下文管理。"""
  return await run(ctx,'dimension_edit',handle=handle,style=style,plot_scale=plot_scale,text_position=text_position,line_point=line_point)
 @tool('等距排列平行尺寸线并重置文字居中','write',['排列尺寸','尺寸等距','整理标注'])
 async def dimension_arrange(handles:Annotated[list[str],'按由内到外顺序给平行旋转/对齐尺寸'],origin:Annotated[list[float],'第一条尺寸线经过的WCS点'],spacing:Annotated[float,'正的模型单位间距'],angle_deg:Annotated[float,'尺寸方向角；从X轴逆时针，沿其左法向排列']=0,ctx:Context=None)->dict:
  """仅XY且尺寸方向平行；重置文字为默认居中，不保证复杂文字避碰；测量点和尺寸数值保留。"""
  return await run(ctx,'dimension_arrange',handles=handles,origin=origin,spacing=spacing,angle_deg=angle_deg)
 @tool('调整实体的前后绘图顺序','write',['绘图顺序','置顶','置底','填充置底'])
 async def entity_draw_order(handles:Annotated[list[str],'1–100个当前空间句柄'],position:Literal['top','bottom','above','below'],relative_to:Annotated[str|None,'above/below所需参考实体句柄，不得包含在handles中']=None,ctx:Context=None)->dict:
  """同一图纸空间内排序；不改变几何，不进入块内部；返回读回排序索引。"""
  return await run(ctx,'entity_draw_order',handles=handles,position=position,relative_to=relative_to)
 @tool('读取或选用图中已有公司图层和文字尺寸样式','write',['公司绘图设置','公司模板设置','建筑中文设置'])
 async def arch_company_profile(settings:Annotated[dict,'空字典仅读取；可选current_layer/textstyle/dimstyle为已有名称，plot_scale为正比例分母。不得传字体文件或自动创建样式'],ctx:Context=None)->dict:
  """选择既有公司设置；不改原样式定义/旧实体，不覆盖arch_*内部角色图层规则；中文表/符号另用lang=zh。不是自动套用公司全套标准。"""
  return await run(ctx,'arch_company_profile',settings=settings)
