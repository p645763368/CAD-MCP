import unittest,json
from pathlib import Path
import server

class ArchitectureScope(unittest.TestCase):
 def test_registry_matches_published_catalog(self):
  root=Path(__file__).resolve().parents[1]
  catalog=json.loads((root/'latest/docs/工具目录.json').read_text(encoding='utf-8'))
  names={t.name for t in server._local_tool_components()}
  self.assertEqual(len(names),248);self.assertEqual(names,{r['name'] for r in catalog});self.assertEqual(sum(r['enabled'] for r in catalog),248)
 def test_retired_endpoints_have_no_callable_entry(self):
  names={t.name for t in server._local_tool_components()}
  for name in server.ARCHITECTURE_RETIRED_TOOLS:
   self.assertNotIn(name,names);self.assertFalse(hasattr(server,name),name)
 def test_all_original_tools_have_a_decision(self):
  root=Path(__file__).resolve().parents[1];rows=json.loads((root/'latest/docs/ARCHITECTURE-TOOL-AUDIT.json').read_text(encoding='utf-8'))
  self.assertEqual(len(rows),240);self.assertEqual(len({r['name'] for r in rows}),240)
  self.assertEqual({r['name'] for r in rows if r['decision']=='删除'},set(server.ARCHITECTURE_RETIRED_TOOLS))
  self.assertEqual({r['name'] for r in rows if r['decision']=='保留禁用'},{'validation_check','drawing_finalize','drawing_deliver'})
 def test_readme_is_for_public_users(self):
  text=(Path(__file__).resolve().parents[1]/'README.md').read_text(encoding='utf-8')
  for forbidden in ['加密','私有仓库','site-packages','源码摘要','统一工作目录']:
   self.assertNotIn(forbidden,text)

if __name__=='__main__':unittest.main()
