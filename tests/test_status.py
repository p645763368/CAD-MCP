import asyncio,unittest
from types import SimpleNamespace
from unittest.mock import patch
import cad_mcp_status as status

class StatusTests(unittest.TestCase):
 def test_history_is_bounded_and_private(self):
  m=status.StatusMonitor()
  for i in range(250):
   ident=m.begin('tool_'+str(i));m.finish(ident,'成功',12.345)
  payload=m.snapshot();self.assertEqual(len(payload['history']),200)
  self.assertEqual(payload['history'][0]['tool'],'tool_249')
  self.assertNotIn('arguments',str(payload));self.assertNotIn('document',str(payload));self.assertEqual(payload['history'][0]['elapsed_ms'],12.3)
 def test_inflight_becomes_finished(self):
  m=status.StatusMonitor();i=m.begin('drawing_info');self.assertEqual(len(m.snapshot()['inflight']),1)
  m.finish(i,'失败',2,'RuntimeError');self.assertFalse(m.snapshot()['inflight']);self.assertEqual(m.snapshot()['history'][0]['error_type'],'RuntimeError')
 def test_payload_error_detection(self):
  for r in [SimpleNamespace(is_error=True),SimpleNamespace(structured_content={'ok':False}),SimpleNamespace(structured_content={'success':False})]:self.assertTrue(status.failed_result(r))
  self.assertFalse(status.failed_result(SimpleNamespace(structured_content={'ok':True})))
 def test_ui_reply_pause_and_resume(self):
  m=status.StatusMonitor();m.running=True;m.sid='test';m.cad_pid=42
  for allowed in [False,True]:
   with patch.object(status,'_pipe_exchange',return_value={'protocol':1,'cad_pid':42,'enabled':allowed}):m.exchange()
   self.assertEqual(m.enabled,allowed)
 def test_headless_does_not_contact_cad_ui(self):
  m=status.StatusMonitor();m.running=True;m.backend=SimpleNamespace(name='ezdxf');m.cad_pid=42
  with patch.object(status,'_pipe_exchange') as exchange:m.exchange();exchange.assert_not_called()
 def test_wrong_target_ignored(self):
  m=status.StatusMonitor();m.running=True;m.sid='test';m.cad_pid=42
  with patch.object(status,'_pipe_exchange',return_value={'protocol':1,'cad_pid':43,'enabled':False}):m.exchange()
  self.assertTrue(m.enabled)
 def test_disconnect_keeps_requested_pause(self):
  m=status.StatusMonitor();m.running=True;m.sid='test';m.cad_pid=42;m.enabled=False
  with patch.object(status,'_pipe_exchange',side_effect=TimeoutError):m.exchange()
  self.assertFalse(m.enabled)

class MiddlewareTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.m=status.StatusMonitor();self.patch=patch.object(status,'monitor',self.m);self.patch.start();self.middleware=status.StatusMiddleware()
 async def asyncTearDown(self):self.patch.stop()
 def context(self,name):return SimpleNamespace(message=SimpleNamespace(name=name,arguments={'private':'secret'}))
 async def test_initialize_handshake(self):
  async def nxt(c):return 'ok'
  self.assertEqual(await self.middleware.on_initialize(None,nxt),'ok');self.assertTrue(self.m.initialized)
 async def test_pause_blocks_before_business_call(self):
  self.m.enabled=False;called=[]
  async def nxt(c):called.append(True)
  with self.assertRaises(status.ToolError):await self.middleware.on_call_tool(self.context('entity_delete'),nxt)
  self.assertFalse(called);self.assertEqual(self.m.snapshot()['history'][0]['state'],'已拦截')
 async def test_pause_still_allows_status(self):
  self.m.enabled=False
  async def nxt(c):return SimpleNamespace(is_error=False)
  await self.middleware.on_call_tool(self.context('system_status'),nxt);self.assertEqual(self.m.snapshot()['history'][0]['state'],'成功')
 async def test_wrapper_not_duplicate_history(self):
  async def nxt(c):return SimpleNamespace(is_error=False)
  for name in ['call_tool','search_tools']:await self.middleware.on_call_tool(self.context(name),nxt)
  self.assertFalse(self.m.snapshot()['history'])
 async def test_exception_records_type_only(self):
  async def nxt(c):raise RuntimeError('private project path')
  with self.assertRaises(RuntimeError):await self.middleware.on_call_tool(self.context('drawing_info'),nxt)
  row=self.m.snapshot()['history'][0];self.assertEqual(row['error_type'],'RuntimeError');self.assertNotIn('private',str(row))
 async def test_inflight_failure_after_pause_stays_failure(self):
  async def nxt(c):
   self.m.enabled=False
   raise RuntimeError('operation failed after user paused')
  with self.assertRaises(RuntimeError):await self.middleware.on_call_tool(self.context('drawing_info'),nxt)
  self.assertEqual(self.m.snapshot()['history'][0]['state'],'失败')
 async def test_returned_failure_recorded(self):
  async def nxt(c):return SimpleNamespace(structured_content={'ok':False})
  await self.middleware.on_call_tool(self.context('drawing_info'),nxt);self.assertEqual(self.m.snapshot()['history'][0]['state'],'失败')

class PipeTests(unittest.TestCase):
 def test_real_pipe_roundtrip(self):
  import threading,uuid,json
  import win32pipe,win32file
  name='CadMcpStatus-Test-'+uuid.uuid4().hex
  handle=win32pipe.CreateNamedPipe('\\\\.\\pipe\\'+name,win32pipe.PIPE_ACCESS_DUPLEX,win32pipe.PIPE_TYPE_MESSAGE|win32pipe.PIPE_READMODE_MESSAGE|win32pipe.PIPE_WAIT,1,8192,8192,0,None)
  received=[];errors=[]
  def serve():
   try:
    win32pipe.ConnectNamedPipe(handle,None);_,data=win32file.ReadFile(handle,8192);received.append(json.loads(data))
    win32file.WriteFile(handle,b'{"protocol":1,"cad_pid":42,"enabled":false}\n');win32file.FlushFileBuffers(handle)
   except Exception as exc:errors.append(str(exc))
   finally:handle.Close()
  thread=threading.Thread(target=serve,daemon=True);thread.start()
  reply=status._pipe_exchange(name,{'protocol':1,'history':[]})
  thread.join(2);self.assertFalse(thread.is_alive());self.assertFalse(errors);self.assertFalse(reply['enabled']);self.assertEqual(received,[{'protocol':1,'history':[]}])

if __name__=='__main__':unittest.main()
