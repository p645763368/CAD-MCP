"""A fresh installed server, explicit headless backend, temporary private paths.
No AutoCAD connection, template selection, NETLOAD, or file export is performed.
"""
import asyncio,json,os,sys,tempfile,tomllib
from pathlib import Path
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

def unpack(r):
    if r.data is not None:return r.data
    return json.loads('\n'.join(x.text for x in r.content if x.type=='text'))

async def main():
    with tempfile.TemporaryDirectory(prefix='cad-mcp-wire-') as t:
        root=Path(t)
        env=dict(os.environ,AUTOCAD_MCP_BACKEND='ezdxf',ALLOWED_PATHS=t,CAD_MCP_NATIVE_ROOT=str(root/'unused-plugins'),
                 APPDATA=str(root/'fake-roaming'),TOOL_PROFILE='full',TOOL_PACKS='all',DISCOVERY_MODE='search',
                 DISABLED_TOOLS='drawing_deliver,drawing_finalize,validation_check',PYTHONDONTWRITEBYTECODE='1')
        command=str(Path(sys.executable).parent/('autocad-mcp.exe' if os.name=='nt' else 'autocad-mcp'))
        async with Client(StdioTransport(command=command,args=[],env=env)) as client:
            names={x.name for x in await client.list_tools()}
            assert names=={'search_tools','call_tool'},names
            async def call(name,args=None):
                r=await client.call_tool('call_tool',{'name':name,'arguments':args or {}},timeout=60)
                data=unpack(r)
                assert not r.is_error and not (isinstance(data,dict) and data.get('ok') is False),(name,data)
                return data
            status=await call('system_status')
            assert status['backend']=='ezdxf' and status['build']=='icons-20261127.1',status
            assert status['version']=='1.6.0.post4' and status['tool_count']==240,status
            for name in ['drawing_unit_context','viewport_list','dimension_chain','drawing_round_geometry']:
                r=unpack(await client.call_tool('search_tools',{'query':name,'limit':1,'detail':True}))
                assert r['tools'][0]['name']==name
            r=unpack(await client.call_tool('search_tools',{'query':'碎数','limit':1,'detail':True}));assert r['tools'][0]['name']=='drawing_round_geometry'
            for name in ['drawing_deliver','drawing_finalize','validation_check']:
                r=await client.call_tool('call_tool',{'name':name,'arguments':{}},raise_on_error=False)
                assert r.is_error,name
            # Inspect schemas before invoking the supported headless drawing path.
            for name in ['drawing_new','entity_create_line','entity_list']:
                r=unpack(await client.call_tool('search_tools',{'query':name,'limit':1,'detail':True}));assert r['tools'][0]['name']==name
            await call('drawing_new',{'bootstrap':False})
            line=await call('entity_create_line',{'x1':0,'y1':0,'x2':20,'y2':0})
            rows=await call('entity_list',{'type_filter':'LINE','compact':True})
            assert rows['total']==1 and rows['rows'][0][0]==line['handle'],rows
        assert not (root/'unused-plugins').exists(),'Unexpected native deployment'
        print(json.dumps({'ok':True,'backend':'ezdxf','build':status['build'],'version':status['version'],
                          'registered':240,'disabled_checked':3,'in_memory_line_verified':True,'autocad_contacted':False}))
if __name__=='__main__':asyncio.run(main())
