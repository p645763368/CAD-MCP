"""Check-first building finalization and resumable DWG/PDF delivery."""
from __future__ import annotations
from typing import Annotated,Literal
from pathlib import Path
import json,uuid,re,hashlib,hmac,os,tempfile
from fastmcp import Context
from building_tools import snapshot,token
from engineering.building_checks import check_snapshot
from building_bridge import dispatch
from security import validate_path

def readiness(snap,checks,model_units,strict,expected):
 result=check_snapshot(snap,checks,.001,model_units);expected=expected or {}
 allowed={'min_entities','max_entities','required_layers','forbid_layers','required_layouts'}
 if set(expected)-allowed:raise ValueError('建筑expected支持: '+','.join(sorted(allowed)))
 if not result['ok']:return result
 model=[r for r in snap['rows'] if r['space']=='model'];findings=result['findings'];layers={l['name'] for l in snap['layers']};layouts={x['name'] for x in snap['layouts']}
 def error(message):findings.append({'check':'requirements','severity':'error','message':message})
 if len(model)<int(expected.get('min_entities',1)):error('模型对象数量低于要求')
 if 'max_entities' in expected and len(model)>int(expected['max_entities']):error('模型对象数量超过要求')
 for name in expected.get('required_layers',[]):
  if name not in layers:error('缺少要求图层: '+name)
 for name in expected.get('forbid_layers',[]):
  if name in layers:error('存在禁止图层: '+name)
 for name in expected.get('required_layouts',[]):
  if name not in layouts:error('缺少要求布局: '+name)
 result['summary']={k:sum(f['severity']==k for f in findings) for k in ['error','warning','info']}
 result['passed']=result['summary']['error']==0 and (not strict or result['summary']['warning']==0)
 return result

def safe_name(name):
 if not isinstance(name,str) or not 1<=len(name)<=80 or name.strip()!=name or name.endswith('.') or any(c in '<>:"/\\|?*' or ord(c)<32 or c in '\u2028\u2029' for c in name):raise ValueError('名称须符合Windows文件名规则，最多80字')
 stem=name.split('.',1)[0].upper()
 if stem in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]}:raise ValueError('Windows保留文件名')
 return name


def write_json(path,data):
 tmp=None
 try:
  with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,prefix='.manifest-',suffix='.tmp',delete=False) as stream:
   tmp=Path(stream.name);json.dump(data,stream,ensure_ascii=False,indent=2)
  os.replace(tmp,path)
 finally:
  if tmp is not None:tmp.unlink(missing_ok=True)

def register(s):
 def register_tool(name,summary,fn):
  s.mcp._local_provider.remove_tool(name)
  s.mcp.tool(name=name,description=summary+'。\n'+(fn.__doc__ or ''),annotations={'readOnlyHint':False,'destructiveHint':True,'idempotentHint':False},meta={'cad':{'summary':summary,'risk':'destructive','cost':'destructive','zh_aliases':['建筑检查交付',summary],'catalog_revision':'2026-11-27.p01'}},tags={'drawing'})(fn)

 async def drawing_finalize(save_path:Annotated[str|None,'可选DWG副本路径；目标已存在时拒绝']=None,screenshot_path:Annotated[str|None,'可选PNG路径；检查通过后才写出']=None,expected:Annotated[dict|None,'min_entities/max_entities/required_layers/forbid_layers/required_layouts']=None,strict_critique:bool=False,checks:list[str]|None=None,model_units:Literal['mm','cm','m','inch','ft']|None=None,dry_run:bool=True,expected_token:str|None=None,ctx:Context=None)->dict:
  """先只读检查，默认预览；执行必须携带最新token。检查不通过时不输出文件。DWG保存为完整副本并在CAD中重开核验，不改变当前文档路径；截图是当前窗口画面。输出中途失败明确列出已生成文件。"""
  paths=[]
  for path,suffix in [(save_path,'.dwg'),(screenshot_path,'.png')]:
   if path:
    p=Path(validate_path(path,allow_write=True))
    if p.suffix.lower()!=suffix:raise ValueError('文件扩展名必须为'+suffix)
    if p.exists():raise ValueError('目标已存在: '+str(p))
    paths.append(p)
  snap=await snapshot(s,ctx,'all');check=readiness(snap,checks,model_units,strict_critique,expected)
  plan={'save_path':str(next((p for p in paths if p.suffix.lower()=='.dwg'),'')),'screenshot_path':str(next((p for p in paths if p.suffix.lower()=='.png'),'')),'expected':expected,'strict':strict_critique,'checks':checks,'units':model_units};preview=token(snap,plan)
  result={'ok':check['ok'],'passed':check['passed'],'dry_run':dry_run,'preview_token':preview,'validation':check,'outputs':[]}
  if dry_run:return result
  if not expected_token or not hmac.compare_digest(preview,expected_token):raise ValueError('请先按相同参数重新预览')
  if not check['passed']:return dict(result,status='blocked_validation')
  try:
   for p in paths:p.parent.mkdir(parents=True,exist_ok=True)
   if save_path:result['outputs'].append(await s._backend(ctx)._run(dispatch,'save_copy',path=str(paths[0]),scope='all',expected_token=snap['token']))
   if screenshot_path:
    p=next(p for p in paths if p.suffix.lower()=='.png');data=await s._backend(ctx).view_screenshot()
    if not data or not data.startswith(b'\x89PNG\r\n\x1a\n'):raise ValueError('截图未返回有效PNG')
    with p.open('xb') as stream:stream.write(data)
    result['outputs'].append({'path':str(p),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
   return dict(result,status='completed',source_document_preserved=True)
  except Exception as exc:return dict(result,ok=False,status='partial_output',error=str(exc),source_document_preserved=True)
 register_tool('drawing_finalize','先检查建筑图纸，再按明确路径生成DWG副本和截图',drawing_finalize)

 async def drawing_deliver(output_dir:str,formats:Annotated[list[str]|None,'dwg/pdf；null为两者，不强制追加其他格式']=None,prefix:str='drawing',layouts:Annotated[list[str]|None,'PDF布局名称；null输出Model']=None,expected:dict|None=None,strict_critique:bool=False,checks:list[str]|None=None,model_units:Literal['mm','cm','m','inch','ft']|None=None,dry_run:bool=True,expected_token:str|None=None,resume_id:Annotated[str|None,'失败后返回的32位job_id；用于恢复同一图纸、同一参数的暂存交付']=None,ctx:Context=None)->dict:
  """先检查→暂存导出→DWG重开/PDF文件头核验→统一发布。默认预览，执行须带token；拒绝覆盖现有目标。失败保留本任务暂存目录与清单，可用resume_id恢复；图纸或参数变化后拒绝复用。DWG副本修复本工具的句柄关联；依赖清单随结果提供，不自动复制外参/字体/打印样式。原图不保存、不关闭。"""
  root=Path(validate_path(output_dir,allow_write=True)).resolve();prefix=safe_name(prefix);formats=list(dict.fromkeys(x.lower() for x in (['dwg','pdf'] if formats is None else formats)));layouts=list(dict.fromkeys(['Model'] if layouts is None else layouts))
  if not formats or set(formats)-{'dwg','pdf'}:raise ValueError('formats须为非空dwg/pdf列表')
  if 'pdf' in formats and not layouts:raise ValueError('PDF至少需要一个布局')
  if root.exists() and not root.is_dir():raise ValueError('output_dir须为目录')
  snap=await snapshot(s,ctx,'all');check=readiness(snap,checks,model_units,strict_critique,expected);names={x['name'] for x in snap['layouts']}
  if 'pdf' in formats and set(layouts)-names:raise ValueError('布局不存在: '+','.join(set(layouts)-names))
  spec={'output_dir':str(root),'formats':formats,'prefix':prefix,'layouts':layouts,'expected':expected,'strict':strict_critique,'checks':checks,'units':model_units}
  entries=[]
  if 'dwg' in formats:entries.append({'file':prefix+'.dwg','format':'dwg'})
  if 'pdf' in formats:
   for name in layouts:entries.append({'file':prefix+'-'+safe_name(name)+'.pdf','format':'pdf','layout':name})
  preview=token(snap,spec);existing=[str(root/e['file']) for e in entries if (root/e['file']).exists()]
  manifest_name=prefix+'.manifest.json'
  if (root/manifest_name).exists():existing.append(str(root/manifest_name))
  result={'ok':check['ok'],'passed':check['passed'] and not existing,'dry_run':dry_run,'preview_token':preview,'validation':check,'conflicting_outputs':existing,'planned_outputs':entries}
  if dry_run:return result
  if not expected_token or not hmac.compare_digest(preview,expected_token):raise ValueError('交付预览失效或参数改变')
  if not result['passed']:return dict(result,status='blocked_validation_or_existing_output')
  if resume_id and not re.fullmatch('[0-9a-f]{32}',resume_id):raise ValueError('resume_id格式错误')
  job_id=resume_id or uuid.uuid4().hex;stage=root/('.cad-mcp-'+job_id)
  if stage.resolve().parent!=root:raise ValueError('暂存路径发生重定向')
  manifest=stage/'job.json'
  if manifest.resolve().parent!=stage.resolve():raise ValueError('暂存清单路径发生重定向')
  root.mkdir(parents=True,exist_ok=True)
  if resume_id:
   state=json.loads(manifest.read_text(encoding='utf-8'))
   if state['spec']!=spec or state['snapshot_token']!=snap['token']:raise ValueError('源图或参数改变，不能复用暂存交付')
  else:
   stage.mkdir(exist_ok=False);state={'job_id':job_id,'spec':spec,'snapshot_token':snap['token'],'completed':{},'status':'exporting'};write_json(manifest,state)
  try:
   for entry in entries:
    name=entry['file'];path=stage/name
    if path.resolve().parent!=stage.resolve():raise ValueError('暂存文件路径发生重定向')
    if name in state['completed']:
     if not path.is_file():raise ValueError('暂存结果缺失，请使用新任务')
     await s._backend(ctx)._run(dispatch,'verify_output',path=str(path),sha256=state['completed'][name]['sha256'])
     continue
    if path.exists():path.unlink() # Only this job's unverified partial file.
    if entry['format']=='dwg':out=await s._backend(ctx)._run(dispatch,'save_copy',path=str(path),scope='all',expected_token=snap['token'])
    else:out=await s._backend(ctx)._run(dispatch,'pdf',path=str(path),layout=entry['layout'],scope='all',expected_token=snap['token'])
    state['completed'][name]=out;write_json(manifest,state)
   moved=[];owned_manifest=False
   try:
    for entry in entries:
     source=stage/entry['file'];dest=root/entry['file']
     if dest.exists():raise ValueError('发布时目标已出现，停止覆盖')
     source.rename(dest);moved.append(entry['file'])
    final={'ok':True,'job_id':job_id,'outputs':[dict(state['completed'][e['file']],path=str(root/e['file'])) for e in entries],'validation':check,'source_document_preserved':True,'external_resources_copied':False,'dependency_note':'按清单另行提供外参、字体和打印样式；输出目录改变时需核对相对外参路径。'}
    # Exclusive create prevents accidentally replacing a concurrently published manifest.
    with (root/manifest_name).open('x',encoding='utf-8') as stream:
     owned_manifest=True;json.dump(final,stream,ensure_ascii=False,indent=2)
   except Exception:
    if owned_manifest:(root/manifest_name).unlink(missing_ok=True)
    for name in reversed(moved):(root/name).rename(stage/name)
    raise
   cleanup_warning=None
   try:manifest.unlink();stage.rmdir()
   except OSError as exc:cleanup_warning=str(exc)
   return dict(result,status='completed',job_id=job_id,outputs=final['outputs'],manifest=str(root/manifest_name),source_document_preserved=True,cleanup_warning=cleanup_warning)
  except Exception as exc:
   state['status']='failed';state['error']=str(exc);write_json(manifest,state)
   return dict(result,ok=False,status='failed_export',job_id=job_id,resume_id=job_id,staging_directory=str(stage),completed=list(state['completed']),error=str(exc),source_document_preserved=True)
 register_tool('drawing_deliver','检查后生成可恢复的DWG/PDF交付包',drawing_deliver)
