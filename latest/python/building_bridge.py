"""AutoCAD 2026 transactional building bridge. Compressed, bounded in-memory IPC."""
import base64,gzip,json,time,uuid
from cad_mcp_paths import native_dll

def dispatch(op,**args):
 from backends import com_backend as com
 doc=com._acad_doc();identity=str(doc.FullName or doc.Name)
 if int(doc.GetVariable('CMDACTIVE')):raise RuntimeError('请先结束当前CAD命令')
 old=doc.GetVariable('USERS5');filedia=doc.GetVariable('FILEDIA');background=doc.GetVariable('BACKGROUNDPLOT') if op=='pdf' else None;old_layout=doc.ActiveLayout.Name if op=='pdf' else None
 try:
  doc.SetVariable('FILEDIA',0)
  if background is not None:
   doc.SetVariable('BACKGROUNDPLOT',0)
   target=args.get('layout','Model')
   if old_layout!=target:doc.ActiveLayout=doc.Layouts.Item(target)
  def invoke(expr):
   if str(com._acad_doc().FullName or com._acad_doc().Name)!=identity:raise RuntimeError('活动图纸已改变')
   marker='BUILD_PENDING_'+uuid.uuid4().hex;command='(setvar "USERS5" '+expr+')\n'
   if len(command)>1800:raise ValueError('请求超过命令行安全长度，请缩小批次')
   doc.SetVariable('USERS5',marker);doc.SendCommand(command);end=time.monotonic()+30
   while time.monotonic()<end:
    value=str(doc.GetVariable('USERS5'))
    if value!=marker:return value
    time.sleep(.02)
   raise RuntimeError('原生操作超时，先核对CAD状态再重试')
  if invoke('(if (member "MCPBUILDING2026" (atoms-family 1)) "loaded" "missing")')!='loaded':
   path=native_dll('CadMcpBuilding2026')
   if not path.is_file():raise RuntimeError('建筑模块未安装')
   doc.SendCommand('(command "_.NETLOAD" '+json.dumps(str(path).replace('\\','/'))+')\n');raise RuntimeError('已请求加载CadMcpBuilding2026.dll；确认加载一次后重试。当前未派发业务操作。')
  def request(body):
   raw=json.dumps({'document':identity,**body},ensure_ascii=False,separators=(',',':'),allow_nan=False)
   raw=raw.replace('\u2028','\\u2028').replace('\u2029','\\u2029')
   if len(raw)>1400:raise ValueError('单次请求过大')
   result=json.loads(invoke('(car (MCPBUILDING2026 '+json.dumps(raw,ensure_ascii=False)+'))'))
   if not result.get('ok'):raise ValueError(result.get('error','建筑操作失败'))
   return result
  body={'op':op,**args};raw=json.dumps({'document':identity,**body},ensure_ascii=False,separators=(',',':'),allow_nan=False)
  if len(raw)>800:
   encoded=base64.b64encode(gzip.compress(raw.encode())).decode();token=request({'op':'upload_start'})['upload_token']
   for i in range(0,len(encoded),400):request({'op':'upload_chunk','upload_token':token,'offset':i,'data':encoded[i:i+400]})
   result=request({'op':'uploaded','upload_token':token})
  else:result=request(body)
  if result.get('compressed'):
   content=result['data'];token=result['token'];size=result['length']
   while len(content)<size:
    part=request({'op':'chunk','token':token,'offset':len(content)})
    if part['offset']!=len(content) or not part['data']:raise RuntimeError('返回数据分块错误')
    content+=part['data']
   result=json.loads(gzip.decompress(base64.b64decode(content)))
  if not result.get('ok'):raise ValueError(result.get('error','原生操作失败'))
  return result
 finally:
  if old_layout is not None and doc.ActiveLayout.Name!=old_layout:doc.ActiveLayout=doc.Layouts.Item(old_layout)
  if background is not None:doc.SetVariable('BACKGROUNDPLOT',background)
  doc.SetVariable('FILEDIA',filedia);doc.SetVariable('USERS5',old)
