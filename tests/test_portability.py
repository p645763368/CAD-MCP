import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from cad_mcp_paths import native_dll, native_payload_root, native_relative, NATIVE_MODULES, system_directories
from cad_mcp_deploy import install_native, client_config

class Portability(unittest.TestCase):
    def test_roaming_user_resolution(self):
        with tempfile.TemporaryDirectory() as t, patch.dict(os.environ, {"APPDATA": t, "CAD_MCP_NATIVE_ROOT": ""}):
            expected = Path(t).resolve()/"Autodesk/ApplicationPlugins"/native_relative(NATIVE_MODULES[0])
            self.assertEqual(native_dll(NATIVE_MODULES[0]), expected)

    def test_explicit_root_overrides_roaming(self):
        with tempfile.TemporaryDirectory() as t, patch.dict(os.environ, {"CAD_MCP_NATIVE_ROOT": t}):
            self.assertEqual(native_dll(NATIVE_MODULES[1]), Path(t).resolve()/native_relative(NATIVE_MODULES[1]))

    def test_relative_override_refused(self):
        with patch.dict(os.environ, {"CAD_MCP_NATIVE_ROOT": "relative/plugins"}):
            with self.assertRaises(ValueError):native_dll(NATIVE_MODULES[0])

    def test_unknown_native_module_refused(self):
        with self.assertRaises(ValueError):native_relative("../../other")

    def test_payload_install_dry_run_and_idempotence(self):
        with tempfile.TemporaryDirectory() as t:
            dest=Path(t)/"different user 中文"/"plugins"
            preview=install_native(dest,True)
            self.assertFalse(dest.exists())
            self.assertEqual({x['status'] for x in preview},{'would_install'})
            actual=install_native(dest)
            self.assertEqual(len(actual),3)
            for name in NATIVE_MODULES:
                self.assertEqual((dest/native_relative(name)).read_bytes(),(native_payload_root()/native_relative(name)).read_bytes())
            unrelated=dest/'user-plugin.txt';unrelated.write_text('keep',encoding='utf-8')
            self.assertEqual({x['status'] for x in install_native(dest)},{'unchanged'})
            self.assertEqual(unrelated.read_text(),'keep')

    def test_generated_config_uses_active_interpreter(self):
        with tempfile.TemporaryDirectory() as t:
            c=client_config([t],"ezdxf",str(Path(t)/'plugins'))['mcp_servers']['autocad-mcp']
            self.assertEqual(Path(c['command']).parent,Path(sys.executable).parent)
            self.assertEqual(c['env']['ALLOWED_PATHS'],str(Path(t).resolve()))
            self.assertEqual(c['env']['AUTOCAD_MCP_BACKEND'],'ezdxf')

    def test_comma_workspace_refused(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(ValueError):client_config([str(Path(t)/'a,b')])

    def test_cli_toml_roundtrip(self):
        with tempfile.TemporaryDirectory() as t:
            workspace=str(Path(t)/'Drawing files 中文')
            cli=Path(sys.executable).parent/('autocad-mcp-config.exe' if os.name=='nt' else 'autocad-mcp-config')
            env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8')
            result=subprocess.check_output([str(cli),'--workspace',workspace,'--backend','ezdxf'],env=env)
            parsed=tomllib.loads(result.decode('utf-8'))
            self.assertEqual(parsed['mcp_servers']['autocad-mcp']['env']['ALLOWED_PATHS'],str(Path(workspace).resolve()))

    def test_missing_workspace_stops_before_server_start(self):
        cli=Path(sys.executable).parent/('autocad-mcp.exe' if os.name=='nt' else 'autocad-mcp')
        env=dict(os.environ,ALLOWED_PATHS='',PYTHONUTF8='1')
        result=subprocess.run([str(cli)],env=env,capture_output=True,timeout=10)
        self.assertNotEqual(result.returncode,0)
        self.assertIn(b'ALLOWED_PATHS',result.stderr)

    @unittest.skipUnless(os.name=='nt','Windows-specific system-directory mapping')
    def test_system_directory_follows_environment(self):
        with tempfile.TemporaryDirectory() as t:
            env={'SystemRoot':str(Path(t)/'Windows'),'ProgramFiles':str(Path(t)/'Apps'),
                 'ProgramW6432':str(Path(t)/'Apps64'),'ProgramFiles(x86)':str(Path(t)/'Apps32')}
            with patch.dict(os.environ,env):self.assertEqual(set(system_directories()),{Path(x).resolve() for x in env.values()})

if __name__=='__main__':unittest.main(verbosity=2)
