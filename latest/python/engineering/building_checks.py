"""Building checks distinguish execution completeness from drawing findings."""
import math,hashlib,json,os
from pathlib import Path
from collections import defaultdict
from engineering.building import FACTORS
UNIT_CODES={1:'inch',2:'ft',4:'mm',5:'cm',6:'m'}
CHECKS={'empty_layers','zero_length','duplicate_entities','assets','duplicate_tags'}

def factor(snapshot,override=None):
 name=override or UNIT_CODES.get(snapshot['units'])
 if name not in FACTORS:raise ValueError('单位未知，请核对图纸后提供model_units')
 return FACTORS[name]

def check_snapshot(snapshot,checks=None,tolerance_mm=.001,model_units=None):
 checks=list(dict.fromkeys(checks or ['zero_length','duplicate_entities','empty_layers','assets','duplicate_tags']))
 if set(checks)-CHECKS:raise ValueError('未知检查项: '+','.join(sorted(set(checks)-CHECKS)))
 if not math.isfinite(tolerance_mm) or tolerance_mm<=0:raise ValueError('tolerance_mm须为正有限数')
 mm=factor(snapshot,model_units);findings=[];coverage={};groups=defaultdict(list)
 def finding(check,severity,**data):findings.append({'check':check,'severity':severity,**data})
 if not snapshot.get('complete',True):
  return {'ok':False,'passed':False,'complete':False,'errors':snapshot.get('errors',[]),'findings':[],'checks_run':checks}
 if 'empty_layers' in checks:
  for layer in snapshot['layers']:
   if layer['name']!='0' and not layer['used']:finding('empty_layers','info',layer=layer['name'],message='图层未被实体使用')
 if 'zero_length' in checks:
  checked=0
  for row in snapshot['rows']:
   if row['space'].startswith('block:*'):continue
   if 'length' not in row:continue
   checked+=1
   if float(row['length'])*FACTORS.get(UNIT_CODES.get(row.get('space_units')),mm)<=tolerance_mm:finding('zero_length','error',handles=[row['handle']],space=row['space'],length_mm=float(row['length'])*FACTORS.get(UNIT_CODES.get(row.get('space_units')),mm))
  coverage['zero_length']={'checked':checked,'excluded_generated_block_entities':sum(r['space'].startswith('block:*') for r in snapshot['rows']),'basis':'原生曲线长度包含XYZ；排除表格/尺寸等自动生成的匿名块内部几何。块定义单位另行核对。'}
 if 'duplicate_entities' in checks:
  unsupported=defaultdict(int);checked=0
  for row in snapshot['rows']:
   if row['space'].startswith('block:*'):continue
   t=row['type'];tol=tolerance_mm/FACTORS.get(UNIT_CODES.get(row.get('space_units')),mm)
   def q(value):return round(float(value)/tol)
   def pt(point):return tuple(q(v) for v in point)
   geom=None
   if t=='LINE':geom=tuple(sorted(pt(p) for p in row['points']))
   elif t=='CIRCLE':geom=(pt(row['center']),q(row['radius']),tuple(row.get('normal',[0,0,1])))
   elif t=='ARC':geom=(pt(row['center']),q(row['radius']),round(row['start_angle'],10),round(row['end_angle'],10),tuple(row.get('normal',[0,0,1])))
   elif t=='LWPOLYLINE':
    points=[pt(p) for p in row['points']];bulges=row.get('bulges',[0]*len(points));pairs=list(zip(points,[round(b,12) for b in bulges]));closed=row.get('closed',False)
    if closed:
     forward=[tuple(pairs[i:]+pairs[:i]) for i in range(len(pairs))]
     rev=[(points[i],-round(bulges[(i-1)%len(points)],12)) for i in range(len(points)-1,-1,-1)]
     geom=(True,min(forward+[tuple(rev[i:]+rev[:i]) for i in range(len(rev))]))
    else:
     rev=[(points[i],-round(bulges[i-1],12) if i else 0) for i in range(len(points)-1,-1,-1)]
     if pairs:pairs[-1]=(pairs[-1][0],0)
     geom=(False,min(tuple(pairs),tuple(rev)))
   elif t in ['TEXT','MTEXT']:geom=(row.get('text'),pt(row['position']),q(row['height']),round(row.get('rotation',0),10),row.get('text_style',''))
   elif t=='INSERT':geom=(row.get('block_name'),pt(row['position']),tuple(row.get('scale',[])),round(row.get('rotation',0),10),tuple(sorted(row.get('attributes',{}).items())))
   if geom is None:unsupported[t]+=1;continue
   checked+=1;key=(row['space'],row['layer'],row.get('color'),row.get('linetype'),t,geom);groups[key].append(row['handle'])
  for key,handles in groups.items():
   if len(handles)>1:finding('duplicate_entities','warning',handles=handles,space=key[0],layer=key[1],message='同空间同图层同样式的重合几何')
  coverage['duplicate_entities']={'checked':checked,'unsupported':dict(unsupported),'comparison':'按容差量化几何，保持图层/样式区分；未支持类型单独列出'}
 if 'duplicate_tags' in checks:
  seen=defaultdict(list)
  for row in snapshot['rows']:
   rec=row.get('record') or {}
   if rec.get('kind') in ['door_window','grid_axis','parking_bay']:
    seen[(rec['kind'],rec.get('group',''),rec.get('tag',rec.get('label','')))].append(row['handle'])
  for key,handles in seen.items():
   if key[2] and len(handles)>1:
    records=[r['record'] for r in snapshot['rows'] if r['handle'] in handles]
    same_type=key[0]=='door_window' and all(r.get('numbering')=='type' for r in records) and len({json.dumps({k:v for k,v in r.get('source_values',{}).items() if k!='tag'},sort_keys=True) for r in records})==1
    if not same_type:finding('duplicate_tags','error',handles=handles,tag=key[2],group=key[1])
 assets={}
 if 'assets' in checks:
  assets={'fonts':[dict(f,found=f['found'] or (Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/Path(f['file']).name).is_file()) for f in snapshot.get('fonts',[])],'xrefs':snapshot.get('xrefs',[]),'plot_styles':snapshot.get('layouts',[])}
  for font in snapshot.get('fonts',[]):
   if not font['found'] and not (Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/Path(font['file']).name).is_file():finding('assets','warning',asset_type='font',**font)
  for x in snapshot.get('xrefs',[]):
   if x['status'] not in ['Resolved','Unloaded']:finding('assets','error',asset_type='xref',**x)
   elif x['status']=='Unloaded':finding('assets','warning',asset_type='xref',**x)
  for layout in snapshot.get('layouts',[]):
   if not layout['style_found']:finding('assets','error',asset_type='plot_style',**layout)
 counts={k:sum(f['severity']==k for f in findings) for k in ['error','warning','info']}
 return {'ok':True,'passed':counts['error']==0,'complete':True,'checks_run':checks,'summary':counts,'findings':findings,'coverage':coverage,'assets':assets,'entity_count':len(snapshot['rows']),'model_mm_per_unit':mm,'snapshot_token':snapshot['token']}
