"""In-memory status/history shared with the same user's AutoCAD ribbon over pipes.
No drawing data, arguments, result payloads or log files are collected.
"""
from __future__ import annotations
import asyncio, json, os, threading, time, uuid
from collections import deque
from datetime import datetime, timezone
from fastmcp.server.middleware import Middleware
from fastmcp.exceptions import ToolError
from cad_mcp_paths import BUILD_ID
from version import __version__

WRAPPERS={'search_tools','call_tool'}
READ_WHILE_PAUSED=WRAPPERS|{'system_status','system_about','system_capabilities'}


def _user_sid():
    import win32api,win32security
    token=win32security.OpenProcessToken(win32api.GetCurrentProcess(),win32security.TOKEN_QUERY)
    try:return win32security.ConvertSidToStringSid(win32security.GetTokenInformation(token,win32security.TokenUser)[0]).replace('-','')
    finally:token.Close()


def _pipe_exchange(name,payload):
    """Bound every read/write; a closed or busy UI must not hang tool calls."""
    import win32file,win32pipe,win32event,pywintypes,win32con
    path='\\\\.\\pipe\\'+name
    win32pipe.WaitNamedPipe(path,100)
    handle=win32file.CreateFile(path,win32con.GENERIC_READ|win32con.GENERIC_WRITE,0,None,win32con.OPEN_EXISTING,win32con.FILE_FLAG_OVERLAPPED,None)
    def transfer(write,data):
        ov=pywintypes.OVERLAPPED();ov.hEvent=win32event.CreateEvent(None,True,False,None)
        try:
            result=win32file.WriteFile(handle,data,ov) if write else win32file.ReadFile(handle,4096,ov)
            if win32event.WaitForSingleObject(ov.hEvent,700)!=win32event.WAIT_OBJECT_0:
                win32file.CancelIoEx(handle,ov)
                win32event.WaitForSingleObject(ov.hEvent,700)
                raise TimeoutError('CAD status pipe timeout')
            size=win32file.GetOverlappedResult(handle,ov,False)
            return bytes(result[1][:size]) if not write else b''
        finally:ov.hEvent.Close()
    try:
        data=json.dumps(payload,ensure_ascii=True,separators=(',',':')).encode()+b'\n'
        if len(data)>200000:raise ValueError('Status snapshot too large')
        transfer(True,data)
        return json.loads(transfer(False,None))
    finally:handle.Close()


class StatusMonitor:
    def __init__(self):
        self.session=uuid.uuid4().hex;self.pid=os.getpid();self.cad_pid=0
        self.enabled=True;self.initialized=False;self.running=False;self.backend=None
        self.transport='stdio';self.rows=deque(maxlen=200);self.lock=threading.RLock()
        self.io_lock=threading.Lock();self.stop_event=threading.Event();self.thread=None
        self.sid=None;self.last_ui_contact=0.;self.active={}

    def snapshot(self):
        with self.lock:
            return {'protocol':1,'session':self.session,'pid':self.pid,'cad_pid':self.cad_pid,
                    'version':__version__,'build':BUILD_ID,'running':self.running,
                    'client_initialized':self.initialized,'transport':self.transport,'enabled':self.enabled,
                    'cad_connected':bool(self.backend is not None and getattr(self.backend,'_connected',False)),
                    'history':list(self.rows),'inflight':list(self.active.values())}

    def begin(self,name):
        with self.lock:
            row={'id':uuid.uuid4().hex,'tool':name[:100],'started':datetime.now(timezone.utc).isoformat(),
                 'state':'执行中','elapsed_ms':0};self.active[row['id']]=row;return row['id']

    def finish(self,ident,state,elapsed,error_type=''):
        with self.lock:
            row=self.active.pop(ident,None)
            if row:
                self.rows.appendleft(dict(row,state=state,elapsed_ms=round(elapsed,1),error_type=error_type[:80]))

    def exchange(self):
        if os.name!='nt' or not self.running:return
        if self.backend is not None and getattr(self.backend,'name','')!='com':return
        if not self.io_lock.acquire(timeout=.15):return
        try:
            if not self.sid:self.sid=_user_sid()
            prefix='CadMcpStatus-'+self.sid+'-'
            pid=self.cad_pid
            if not pid:
                # When COM initialization failed, show that failure in the sole
                # available CAD UI. Multiple CAD processes require a known target.
                names=[n for n in os.listdir('\\\\.\\pipe\\') if n.startswith(prefix)]
                if len(names)!=1:return
                pid=int(names[0].rsplit('-',1)[1])
            reply=_pipe_exchange(prefix+str(pid),self.snapshot())
            if reply.get('protocol')!=1 or reply.get('cad_pid')!=pid or not isinstance(reply.get('enabled'),bool):return
            with self.lock:self.enabled=reply['enabled'];self.last_ui_contact=time.monotonic()
        except Exception:
            pass  # UI is optional. Keep a user-requested pause until acknowledged resume.
        finally:self.io_lock.release()

    async def start(self,backend):
        self.backend=backend;self.running=True;self.stop_event.clear()
        if backend is not None and getattr(backend,'name','')=='com':
            try:
                from backends import com_backend as com
                import win32process
                self.cad_pid=await backend._run(lambda:win32process.GetWindowThreadProcessId(int(com._acad_app().HWND))[1])
            except Exception:pass
        if os.name=='nt':
            def worker():
                while not self.stop_event.is_set():self.exchange();self.stop_event.wait(1.)
            self.thread=threading.Thread(target=worker,name='cad-mcp-status',daemon=True);self.thread.start()

    async def stop(self):
        # A disappeared heartbeat is the authoritative disconnected state in CAD.
        self.running=False;self.initialized=False;self.stop_event.set()
        if self.thread:await asyncio.to_thread(self.thread.join,2.)


monitor=StatusMonitor()


def failed_result(result):
    if getattr(result,'is_error',False):return True
    data=getattr(result,'structured_content',None)
    return isinstance(data,dict) and (data.get('ok') is False or data.get('success') is False)


class StatusMiddleware(Middleware):
    async def on_initialize(self,context,call_next):
        result=await call_next(context);monitor.initialized=True;return result

    async def on_call_tool(self,context,call_next):
        name=context.message.name
        if name in WRAPPERS:return await call_next(context)
        # Refresh the CAD switch before admitting a new business operation.
        await asyncio.to_thread(monitor.exchange)
        ident=monitor.begin(name);start=time.monotonic();blocked=False
        try:
            if not monitor.enabled and name not in READ_WHILE_PAUSED:
                blocked=True
                raise ToolError('CAD-MCP已在AutoCAD顶部暂停接入；请点击“恢复接入”后再操作。当前正在执行的操作会继续完成。')
            result=await call_next(context)
            monitor.finish(ident,'失败' if failed_result(result) else '成功',(time.monotonic()-start)*1000)
            return result
        except BaseException as exc:
            monitor.finish(ident,'已拦截' if blocked else '失败',
                           (time.monotonic()-start)*1000,type(exc).__name__)
            raise
