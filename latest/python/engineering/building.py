"""Building drafting plans. Pure geometry, explicit project parameters, no CAD writes."""
from __future__ import annotations
import math,uuid
from collections import defaultdict,Counter
from shapely.geometry import Polygon,LineString,Point
from shapely.ops import unary_union

FACTORS={'mm':1.,'cm':10.,'m':1000.,'inch':25.4,'ft':304.8}
def positive(v,name,zero=False):
 v=float(v)
 if not math.isfinite(v) or (v<0 if zero else v<=0):raise ValueError(f'{name}须为有限'+('非负' if zero else '正')+'数')
 return v
def xy(p):
 if len(p) not in (2,3) or any(not math.isfinite(float(v)) for v in p):raise ValueError('坐标须为有限的[x,y]或[x,y,z]')
 return [float(p[0]),float(p[1])]
def ring(points):
 p=Polygon([xy(x) for x in points])
 if p.is_empty or not p.is_valid or p.area<=1e-14:raise ValueError('边界须为有效闭合多边形，不能自交或退化')
 return p
def polygon_row(row):
 if row['type']!='LWPOLYLINE' or not row.get('closed') or any(abs(x)>1e-12 for x in row.get('bulges',[])):raise ValueError('边界要求闭合、直线段轻量多段线: '+row['handle'])
 pts=row['points']
 if max(p[2] for p in pts)-min(p[2] for p in pts)>1e-9:raise ValueError('边界须同高')
 return ring(pts)
def record(kind,group,mm,**kw):
 if not isinstance(group,str) or not group.strip() or len(group)>128:raise ValueError('group须为1–128字的非空标识')
 return {'schema':1,'kind':kind,'group':group,'model_mm_per_unit':mm,**kw}
def poly(points,layer,rec=None):return dict(type='POLYLINE',points=[[*xy(p),p[2] if len(p)>2 else 0] for p in points],closed=True,layer=layer,**({'record':rec} if rec else {}))
def text(label,at,height,layer,rec=None):return dict(type='TEXT',text=str(label),position=[*xy(at),0],height=height,centered=True,layer=layer,**({'record':rec} if rec else {}))
def line(a,b,layer,rec=None):return dict(type='LINE',start=[*xy(a),a[2] if len(a)>2 else 0],end=[*xy(b),b[2] if len(b)>2 else 0],layer=layer,**({'record':rec} if rec else {}))
def table(cells,at,mm,scale,layer,rec):
 if not cells or len(cells)>2000 or len({len(r) for r in cells})!=1:raise ValueError('表格行列不合法或超过2000行')
 return dict(type='TABLE',cells=[[str(v) for v in r] for r in cells],position=[*xy(at),float(at[2]) if len(at)>2 else 0],text_height=2.5*scale/mm,row_height=7*scale/mm,column_width=30*scale/mm,layer=layer,record=rec)
def replacement(rows,kind,group,replace=False):
 found=[r for r in rows if (r.get('record') or {}).get('group')==group and (r.get('record') or {}).get('kind','').startswith(kind)]
 if found and not replace:raise ValueError('该组已存在，请使用新的group或明确replace=true')
 if any(r['locked'] for r in found):raise ValueError('组内有锁层对象')
 return [{'handle':r['handle'],'delete':True} for r in found]
def transform(p,origin,angle):
 t=math.radians(angle);x,y=xy(p);o=xy(origin);return [o[0]+x*math.cos(t)-y*math.sin(t),o[1]+x*math.sin(t)+y*math.cos(t)]

def axis_labels(axis,label,group,mm,scale,extension,sides,layer):
 if sides not in ['start','end','both']:raise ValueError('sides=start/end/both')
 if axis['type']=='LINE':
  a,b=axis['points'];length=math.dist(a,b)
  if length<=1e-9 or abs(a[2]-b[2])>1e-9:raise ValueError('轴线须为非零同高直线')
  t=[(b[0]-a[0])/length,(b[1]-a[1])/length];ends=[(a,[-t[0],-t[1]],'start'),(b,t,'end')]
 elif axis['type']=='ARC':
  if math.dist(axis.get('normal',[0,0,1]),[0,0,1])>1e-9:raise ValueError('弧轴法向须为+Z')
  a,b=axis['points'];sa,ea=axis['start_angle'],axis['end_angle'];ends=[(a,[math.sin(sa),-math.cos(sa)],'start'),(b,[-math.sin(ea),math.cos(ea)],'end')]
 else:raise ValueError('轴线仅支持LINE/ARC')
 result=[];radius=5*positive(scale,'scale')/mm;ext=positive(extension,'extension',True)/mm
 for endpoint,t,side in ends:
  if sides!='both' and side!=sides:continue
  center=[endpoint[0]+t[0]*(ext+radius),endpoint[1]+t[1]*(ext+radius),endpoint[2]]
  base=record('grid_label',group,mm,source=axis['handle'],label=str(label),side=side)
  if ext:result.append(line(endpoint,[center[0]-t[0]*radius,center[1]-t[1]*radius,center[2]],layer,dict(base,kind='grid_extension')))
  result.append(dict(type='CIRCLE',center=center,radius=radius,layer=layer,record=dict(base,kind='grid_bubble')))
  label_entity=text(label,center,3.5*scale/mm,layer,base);label_entity['position'][2]=center[2];result.append(label_entity)
 return result

def grid_plan(x_axes,y_axes,arcs,labels,origin,rotation,extension,scale,sides,mm,group,layers):
 if not x_axes and not y_axes and not arcs:raise ValueError('请提供正交轴网或弧轴')
 if (x_axes or y_axes) and (not x_axes or not y_axes):raise ValueError('正交轴网需要x_axes和y_axes')
 if len(x_axes)+len(y_axes)+len(arcs)>200:raise ValueError('轴线最多200条')
 if len(set(x_axes))!=len(x_axes) or len(set(y_axes))!=len(y_axes):raise ValueError('轴线位置重复')
 labels=labels or {};entities=[];used=set();info=[];ext=positive(extension,'extension',True)/mm
 for direction,positions in [('x',x_axes),('y',y_axes)]:
  custom=labels.get(direction)
  if custom is not None and len(custom)!=len(positions):raise ValueError('编号数量须与轴线一致')
  if custom is None:positions=sorted(positions)
  for i,pos in enumerate(positions):
   label=str(custom[i] if custom is not None else i+1 if direction=='x' else alpha(i))
   if not label.strip() or label in used:raise ValueError('轴号为空或重复: '+label)
   used.add(label)
   ends=([[pos,min(y_axes)-ext],[pos,max(y_axes)+ext]] if direction=='x' else [[min(x_axes)-ext,pos],[max(x_axes)+ext,pos]])
   a,b=[transform(p,origin,rotation) for p in ends];ident=f'axis{len(info)}';e=line(a,b,layers['axis'],record('grid_axis',group,mm,label=label));e['id']=ident;entities.append(e)
   axis={'type':'LINE','handle':'@'+ident,'points':[[*a,0],[*b,0]]};entities+=axis_labels(axis,label,group,mm,scale,0,sides,layers['label']);info.append({'id':ident,'label':label})
 for i,spec in enumerate(arcs):
  center=xy(spec['center']);radius=positive(spec['radius'],'radius');sa=float(spec['start_angle_deg']);ea=float(spec['end_angle_deg']);sweep=(ea-sa)%360
  if not 0<sweep<360:raise ValueError('弧轴角度范围错误')
  label=str(spec['label']);
  if not label.strip() or label in used:raise ValueError('弧轴编号重复/为空')
  used.add(label);sa,ea=math.radians(sa),math.radians(sa+sweep);ident=f'axis{len(info)}'
  entities.append(dict(type='ARC',id=ident,center=[*center,0],radius=radius,start_angle=sa,end_angle=ea,layer=layers['axis'],record=record('grid_axis',group,mm,label=label)))
  axis={'type':'ARC','handle':'@'+ident,'points':[[center[0]+radius*math.cos(t),center[1]+radius*math.sin(t),0] for t in (sa,ea)],'start_angle':sa,'end_angle':ea}
  entities+=axis_labels(axis,label,group,mm,scale,extension,sides,layers['label']);info.append({'id':ident,'label':label})
 return {'entities':entities,'updates':[],'result':{'axes':info,'group':group}}

def alpha(i):
 s=''
 while True:
  i,r=divmod(i,26);s=chr(65+r)+s
  if not i:return s
  i-=1

def parking_plan(specs,boundary,obstacles,mm,group,clearance,layer,label_layer,text_height):
 bound=ring(boundary) if boundary else None;obs=unary_union([ring(p) for p in obstacles]) if obstacles else None
 clearance=positive(clearance,'clearance',True)/mm;accepted=[];omitted=[];entities=[];occupied=[];driveways=[];seen=set();next_numbers={}
 for row_index,s in enumerate(specs):
  count=int(s['count']);width=positive(s['width_mm'],'width')/mm;length=positive(s['length_mm'],'length')/mm;aisle=positive(s['aisle_mm'],'aisle')/mm;ang=float(s.get('angle_deg',90));direction=float(s.get('direction_deg',0));origin=xy(s['origin']);sides=s.get('sides','single')
  if not 1<=count<=500 or not(ang==0 or 15<=ang<=90) or sides not in ['single','double']:raise ValueError('count=1..500，angle=0或15..90，sides=single/double')
  overrides=s.get('bay_overrides',{});pitch_cursor=0.;t=math.radians(ang);prefix=str(s.get('prefix','P'));next_number=int(s.get('start_number',next_numbers.get(prefix,1)))
  for i in range(count):
   override=overrides.get(str(i),{});w=positive(override.get('width_mm',width*mm),'bay width')/mm;access=positive(override.get('access_strip_mm',0),'access strip',True)/mm
   pitch=(w+access)/math.sin(t) if ang else length
   for side in ([1,-1] if sides=='double' else [1]):
    x=pitch_cursor;y=aisle/2
    if ang:
     bay=[[x,y],[x+w/math.sin(t),y],[x+w/math.sin(t)+length*math.cos(t),y+length*math.sin(t)],[x+length*math.cos(t),y+length*math.sin(t)]]
     foot=[[x,y],[x+pitch,y],[x+pitch+length*math.cos(t),y+length*math.sin(t)],[x+length*math.cos(t),y+length*math.sin(t)]]
    else:bay=[[x,y],[x+length,y],[x+length,y+w],[x,y+w]];foot=[[x,y],[x+length,y],[x+length,y+w+access],[x,y+w+access]]
    bay=[transform([p[0],p[1]*side],origin,direction) for p in bay];foot=[transform([p[0],p[1]*side],origin,direction) for p in foot]
    driveway=[transform(p,origin,direction) for p in [[x,-aisle/2],[x+pitch,-aisle/2],[x+pitch,aisle/2],[x,aisle/2]]]
    footprint=ring(foot);drive=ring(driveway);reason=None
    if bound is not None and (not bound.covers(footprint) or not bound.covers(drive)):reason='超出边界或通道不完整'
    elif obs is not None and (footprint.buffer(clearance).intersects(obs) or drive.intersects(obs)):reason='车位/通道与障碍或净距冲突'
    elif any(footprint.intersection(p).area>1e-10 for p in occupied):reason='与其他车位重叠'
    elif any(drive.intersection(p).area>1e-10 for p in occupied) or any(footprint.intersection(p).area>1e-10 for p in driveways):reason='与其他停车行通道冲突'
    if reason:omitted.append({'row':row_index,'index':i,'side':side,'reason':reason});continue
    label=prefix+str(next_number)
    if label in seen:raise ValueError('车位编号重复: '+label)
    seen.add(label);next_number+=1;next_numbers[prefix]=next_number
    occupied.append(footprint);driveways.append(drive);kind=str(override.get('kind','ordinary'));rec=record('parking_bay',group,mm,label=label,bay_kind=kind,row=row_index,index=i,side=side,width_mm=w*mm,length_mm=length*mm)
    entities.append(poly(bay,layer,rec));c=ring(bay).centroid;entities.append(text(label,[c.x,c.y],text_height/mm,label_layer,dict(rec,kind='parking_label')))
    if access:entities.append(poly(foot,layer,dict(rec,kind='parking_access_extent')))
    accepted.append({'label':label,'kind':kind,'row':row_index,'side':side,'points':bay,'width_mm':w*mm,'length_mm':length*mm})
   pitch_cursor+=pitch
 if len(entities)>5000:raise ValueError('排布过大，请分批')
 return {'entities':entities,'updates':[],'result':{'count':len(accepted),'counts_by_kind':dict(Counter(r['kind'] for r in accepted)),'bays':accepted,'omitted':omitted,'group':group,'turning_swept_path_checked':False}}

def area_rows(zones,rules,mm):
 if not zones or not rules:raise ValueError('需要明确区域及项目计算规则')
 seen=set();out=[];geometry=[]
 for z in zones:
  ident=str(z['id']);floor=str(z['floor']);area_type=str(z.get('area_type','building'));rule=rules[z['rule']]
  if ident in seen:raise ValueError('区域id重复')
  seen.add(ident);outer=ring(z['boundary']);cuts=[ring(p) for p in z.get('deductions',[])]
  if any(not outer.covers(p) for p in cuts):raise ValueError('扣减边界必须在区域内: '+ident)
  deduction=unary_union(cuts) if cuts else Polygon();net=outer.difference(deduction)
  for old_floor,old_type,old_id,old in geometry:
   if old_floor==floor and old_type==area_type and outer.intersection(old).area>1e-9:raise ValueError(f'同层区域重叠: {old_id}/{ident}')
  geometry.append((floor,area_type,ident,outer));factor=positive(rule['factor'],'area factor',True)
  if not str(rule.get('basis','')).strip() or not str(rule.get('version','')).strip():raise ValueError('规则须注明basis及version')
  gross=outer.area*mm*mm/1e6;ded=deduction.area*mm*mm/1e6;value=net.area*mm*mm/1e6
  out.append({'id':ident,'area_type':area_type,'floor':floor,'zone':str(z.get('zone','')),'name':str(z.get('name','')),'rule':z['rule'],'gross_m2':gross,'deduction_m2':ded,'net_m2':value,'factor':factor,'counted_m2':value*factor,'basis':rule['basis'],'version':rule['version']})
 totals={}
 for row in out:
  key=row['area_type']+'/'+row['floor']+'/'+row['zone'];totals[key]=totals.get(key,0)+row['counted_m2']
 totals_by_type={}
 for row in out:totals_by_type[row['area_type']]=totals_by_type.get(row['area_type'],0)+row['counted_m2']
 return {'rows':out,'totals_m2':totals,'totals_by_type_m2':totals_by_type,'total_m2':next(iter(totals_by_type.values())) if len(totals_by_type)==1 else None}

def ramp_plan(path,width_mm,elevations_mm,landings,mm,group,layer,max_slope=None):
 points=[xy(p) for p in path]
 if len(points)<2 or len(points)!=len(elevations_mm):raise ValueError('坡道路径和每个点的标高须一一对应')
 width=positive(width_mm,'width')/mm;entities=[];segments=[]
 for i,(a,b) in enumerate(zip(points,points[1:])):
  run=math.dist(a,b)*mm;rise=float(elevations_mm[i+1])-float(elevations_mm[i])
  if run<=1e-6:raise ValueError('坡道段水平长度为0')
  slope=abs(rise)/run
  if max_slope is not None and slope>positive(max_slope,'max_slope'):raise ValueError(f'第{i+1}段坡度超过给定上限')
  u=[(b[0]-a[0])*mm/run,(b[1]-a[1])*mm/run];n=[-u[1]*width/2,u[0]*width/2]
  ring_points=[[a[0]+n[0],a[1]+n[1]],[b[0]+n[0],b[1]+n[1]],[b[0]-n[0],b[1]-n[1]],[a[0]-n[0],a[1]-n[1]]]
  entities.append(poly(ring_points,layer,record('ramp_segment',group,mm,index=i,start_elevation_mm=elevations_mm[i],end_elevation_mm=elevations_mm[i+1])))
  center=[(a[0]+b[0])/2,(a[1]+b[1])/2];entities.append(text(f'{slope*100:.2f}% ↑',center,150/mm,layer,record('ramp_label',group,mm,index=i)))
  segments.append({'index':i,'run_mm':run,'rise_mm':rise,'slope':slope})
 for i,p in enumerate(landings):
  footprint=ring(p['boundary']);elevation=float(p['elevation_mm'])
  if not math.isfinite(elevation) or not any(footprint.covers(Point(point)) and abs(float(z)-elevation)<1e-6 for point,z in zip(points,elevations_mm)):raise ValueError('平台须连接同标高路径点')
  entities.append(poly(list(footprint.exterior.coords)[:-1],layer,record('ramp_landing',group,mm,index=i,elevation_mm=elevation)))
 return {'entities':entities,'updates':[],'result':{'segments':segments,'landings':len(landings),'group':group}}

def stair_check(risers,riser_height,going,width,limits,profile,obstacles):
 count=int(risers);r=positive(riser_height,'riser_height');g=positive(going,'going');w=positive(width,'width')
 if count<1:raise ValueError('risers须为正整数')
 if not limits:raise ValueError('需要明确提供检查限值')
 if set(limits)-{'riser_height_mm','going_mm','width_mm','blondel_mm','headroom_mm'}:raise ValueError('未知楼梯检查字段')
 for limits_for_field in limits.values():
  if not isinstance(limits_for_field,dict) or not limits_for_field or set(limits_for_field)-{'min','max'} or any(not math.isfinite(float(v)) for v in limits_for_field.values()):raise ValueError('限值必须为有限数')
 findings=[]
 for field,value in [('riser_height_mm',r),('going_mm',g),('width_mm',w),('blondel_mm',2*r+g)]:
  bounds=limits.get(field,{})
  if 'min' in bounds and value<float(bounds['min']):findings.append({'field':field,'value':value,'rule':'min','limit':bounds['min']})
  if 'max' in bounds and value>float(bounds['max']):findings.append({'field':field,'value':value,'rule':'max','limit':bounds['max']})
 clearances=[]
 if profile:
  pts=[xy(p) for p in profile]
  if len(pts)<2 or any(b[0]<a[0] or a==b for a,b in zip(pts,pts[1:])):raise ValueError('断面里程须非递减且相邻点不能相同')
  for o in obstacles:
   a,b=float(o['start_mm']),float(o['end_mm']);bottom=float(o['underside_mm'])
   if b<a:raise ValueError('障碍里程范围倒置')
   candidates=[]
   for p,q in zip(pts,pts[1:]):
    lo=max(a,p[0]);hi=min(b,q[0])
    if lo<=hi:
     if q[0]==p[0]:candidates.extend([p[1],q[1]])
     else:candidates.extend(p[1]+(t-p[0])*(q[1]-p[1])/(q[0]-p[0]) for t in [lo,hi])
   if candidates:
    h=bottom-max(candidates);clearances.append({'id':o.get('id',''),'clearance_mm':h})
    for rule,limit in limits.get('headroom_mm',{}).items():
     if rule=='min' and h<float(limit) or rule=='max' and h>float(limit):findings.append({'field':'headroom_mm','value':h,'obstacle':o.get('id',''),'rule':rule,'limit':limit})
 hc=bool(profile) and bool(obstacles) and all(float(o['start_mm'])>=profile[0][0] and float(o['end_mm'])<=profile[-1][0] for o in obstacles)
 complete='headroom_mm' not in limits or hc
 return {'ok':True,'passed':not findings and complete,'complete':complete,'unverified':[] if complete else ['headroom_mm'],'findings':findings,'total_rise_mm':count*r,'blondel_mm':2*r+g,'clearances':clearances,'headroom_complete':hc}

def columns_plan(points,width_mm,depth_mm,shape,rotation,mm,group,layer):
 w=positive(width_mm,'width')/mm;depth=positive(depth_mm,'depth')/mm
 if shape not in ['rectangle','circle'] or not points or len(points)>1000:raise ValueError('柱类型rectangle/circle；位置1–1000个')
 centers=[xy(p) for p in points]
 if len({tuple(p) for p in centers})!=len(centers):raise ValueError('柱位置重复')
 entities=[]
 for i,c in enumerate(centers):
  rec=record('column',group,mm,index=i,center=c,width_mm=width_mm,depth_mm=depth_mm,shape=shape,rotation_deg=rotation)
  if shape=='circle':entities.append(dict(type='CIRCLE',center=[*c,0],radius=w/2,layer=layer,record=rec))
  else:entities.append(poly([transform(p,c,rotation) for p in [[-w/2,-depth/2],[w/2,-depth/2],[w/2,depth/2],[-w/2,depth/2]]],layer,rec))
 return {'entities':entities,'updates':[],'result':{'count':len(entities),'centers':centers,'group':group}}

def beams_plan(axes,width_mm,mm,group,layer):
 width=positive(width_mm,'width')/mm;entities=[]
 for i,axis in enumerate(axes):
  if len(axis)!=2:raise ValueError('每根梁轴线提供两个端点')
  a,b=[xy(x) for x in axis]
  if math.dist(a,b)<=1e-9:raise ValueError('梁轴线长度为0')
  footprint=LineString([a,b]).buffer(width/2,cap_style=2,join_style=2)
  entities.append(poly(list(footprint.exterior.coords)[:-1],layer,record('beam',group,mm,index=i,axis=[a,b],width_mm=width_mm)))
 return {'entities':entities,'updates':[],'result':{'count':len(entities),'group':group}}

def wall_join_plan(walls,columns,mode,ends,max_shift,mm,group):
 entities=[];updates=[];relations=[]
 if any(r['locked'] or r.get('arch_values') for r in walls):raise ValueError('锁层或已有ACADMCP_ARCH墙记录拒绝直接改线；请使用墙网络工具')
 if mode=='corner':
  if len(walls)!=2 or len(ends)!=2 or any(r['type']!='LINE' for r in walls):raise ValueError('corner需要两条直线及两个端点索引0/1')
  a,b=walls[0]['points'];c,d=walls[1]['points'];u=[b[0]-a[0],b[1]-a[1]];v=[d[0]-c[0],d[1]-c[1]];den=u[0]*v[1]-u[1]*v[0]
  if abs(den)<=1e-12:raise ValueError('轴线平行，不能求角点')
  t=((c[0]-a[0])*v[1]-(c[1]-a[1])*v[0])/den;p=[a[0]+u[0]*t,a[1]+u[1]*t,a[2]]
  if any(abs(q[2]-a[2])>1e-9 for r in walls for q in r['points']):raise ValueError('墙线不在同一XY平面')
  for r,index in zip(walls,ends):
   if index not in [0,1]:raise ValueError('端点索引0/1')
   pts=[list(q) for q in r['points']];shift=math.dist(pts[index],p)*mm
   if shift>max_shift or math.dist(pts[1-index],p)<1e-10:raise ValueError('延伸超限或产生零长度')
   pts[index]=p;updates.append({'handle':r['handle'],'points':pts,'record':record('wall_join',group,mm,mode=mode,related=[x['handle'] for x in walls])})
  return {'entities':[],'updates':updates,'result':{'corner':p,'related':[r['handle'] for r in walls]}}
 if mode!='columns' or not columns:raise ValueError('mode=corner/columns；columns模式需要柱边界')
 shapes=[]
 for r in columns:
  if r['type']=='CIRCLE':
   n=128;radius=r['radius']/math.cos(math.pi/n);c=r['center'];shapes.append(ring([[c[0]+radius*math.cos(i*math.tau/n),c[1]+radius*math.sin(i*math.tau/n)] for i in range(n)]))
  else:shapes.append(polygon_row(r))
 obstacle=unary_union(shapes)
 for r in walls:
  if r['type']=='LWPOLYLINE' and (r.get('record') or {}).get('kind')=='beam':
   if any(c['type']=='CIRCLE' for c in columns):raise ValueError('闭合梁边界收口当前使用多边形柱；圆柱可对直线墙面处理')
   original=polygon_row(r);remaining=original.difference(obstacle)
   if remaining.equals(original):continue
   width=float(r['record']['width_mm'])/mm
   if (original.area-remaining.area)/width>max_shift/mm:raise ValueError('梁边界裁剪量超过max_shift_mm')
   parts=list(remaining.geoms) if remaining.geom_type=='MultiPolygon' else [remaining] if remaining.geom_type=='Polygon' and not remaining.is_empty else []
   updates.append({'handle':r['handle'],'delete':True})
   for i,part in enumerate(parts):
    for role,loop in [('outer',part.exterior)]+[('hole',h) for h in part.interiors]:
     rec=dict(r['record'],join_group=group,columns=[c['handle'] for c in columns],source=r['handle'],part=i,ring_role=role)
     e=poly(list(loop.coords)[:-1],r['layer'],rec)
     for field in ['color','linetype','lineweight']:
      if field in r:e[field]=r[field]
     entities.append(e)
   relations.append({'source':r['handle'],'pieces':len(parts),'columns':[x['handle'] for x in columns]});continue
  if r['type']!='LINE':raise ValueError('选择直线墙面或beam_place生成的闭合梁边界')
  a,b=r['points']
  if abs(a[2]-b[2])>1e-9:raise ValueError('墙线不在XY平面')
  original=LineString([xy(a),xy(b)]);dx=b[0]-a[0];dy=b[1]-a[1];length2=dx*dx+dy*dy
  if length2<=1e-20:raise ValueError('墙线长度为0')
  intervals=[]
  def interval_parts(shape):
   if shape.is_empty:return
   if shape.geom_type=='LineString':
    values=[((p[0]-a[0])*dx+(p[1]-a[1])*dy)/length2 for p in shape.coords];intervals.append((max(0.,min(values)),min(1.,max(values))))
   elif hasattr(shape,'geoms'):
    for part in shape.geoms:interval_parts(part)
  for col in columns:
   z=col['center'][2] if col['type']=='CIRCLE' else col['points'][0][2]
   if abs(z-a[2])>1e-9:raise ValueError('柱与墙线须在同一XY平面')
   if col['type']=='CIRCLE':
    if abs(abs(col.get('normal',[0,0,1])[2])-1)>1e-9:raise ValueError('柱圆须在XY平面')
    c=col['center'];fx=a[0]-c[0];fy=a[1]-c[1];bb=2*(fx*dx+fy*dy);cc=fx*fx+fy*fy-col['radius']**2;disc=bb*bb-4*length2*cc
    if disc>=0:
     lo=max(0.,(-bb-math.sqrt(disc))/(2*length2));hi=min(1.,(-bb+math.sqrt(disc))/(2*length2))
     if hi>lo:intervals.append((lo,hi))
   else:interval_parts(original.intersection(polygon_row(col)))
  merged=[]
  for lo,hi in sorted(intervals):
   if hi-lo<=1e-12:continue
   if merged and lo<=merged[-1][1]+1e-12:merged[-1]=(merged[-1][0],max(merged[-1][1],hi))
   else:merged.append((lo,hi))
  if not merged:continue
  removed=sum(hi-lo for lo,hi in merged)*math.sqrt(length2)
  if removed>max_shift/mm:raise ValueError('裁剪长度超过max_shift_mm')
  keep=[];cursor=0.
  for lo,hi in merged:
   if lo-cursor>1e-12:keep.append((cursor,lo))
   cursor=hi
  if 1-cursor>1e-12:keep.append((cursor,1.))
  parts=[LineString([[a[0]+dx*t,a[1]+dy*t] for t in pair]) for pair in keep]
  updates.append({'handle':r['handle'],'delete':True})
  for p in parts:
   coords=list(p.coords);e=line([*coords[0],a[2]],[*coords[-1],a[2]],r['layer'],record('wall_join',group,mm,source=r['handle'],columns=[x['handle'] for x in columns]));
   for field in ['color','linetype','lineweight']:
    if field in r:e[field]=r[field]
   entities.append(e)
  relations.append({'source':r['handle'],'pieces':len(parts),'columns':[x['handle'] for x in columns]})
 return {'entities':entities,'updates':updates,'result':{'relations':relations,'circle_columns':'直线与圆柱边界使用解析交点'}}
