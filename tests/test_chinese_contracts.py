"""Chinese intent retrieval and schema-preserving contract regression."""
import copy
import json
from pathlib import Path
import re
import unittest
import server
from discovery.chinese_review import apply_review, PATCHES
from discovery.transform import CadSearchTransform, tool_risk
from discovery.serialize import serialize_search_results

class ChineseContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tools = copy.deepcopy(server._local_tool_components())
        apply_review(cls.tools, "com")
        cls.by = {t.name: t for t in cls.tools}
        cls.search = CadSearchTransform()

    def test_full_registry_and_chinese_parameter_coverage(self):
        self.assertEqual(len(self.tools), 248)
        self.assertEqual(set(self.by), set(PATCHES))
        for t in self.tools:
            self.assertRegex(t.description, r"[\u3400-\u9fff]")
            for key, field in t.parameters["properties"].items():
                desc = re.sub(r"\s*\[[^\]]*默认=.*?\]", "", field.get("description", ""))
                self.assertRegex(desc, r"[\u3400-\u9fff]", f"{t.name}.{key}")

    def test_overlay_preserves_validation_and_is_idempotent(self):
        def strip(value):
            if isinstance(value, dict):
                return {k: strip(v) for k, v in value.items() if k != "description"}
            if isinstance(value, list): return [strip(v) for v in value]
            return value
        after_tools = copy.deepcopy(self.tools)
        apply_review(after_tools, "com")
        for before, after in zip(self.tools, after_tools):
            self.assertEqual(strip(before.parameters), strip(after.parameters))
            self.assertEqual(before.description, after.description)
            self.assertEqual(before.meta, after.meta)

    def test_risk_filter_excludes_table_rebuild(self):
        table = self.by['schedule_update']
        self.assertEqual(tool_risk(table), 'destructive')
        result = self.search.rank(self.tools, '更新门窗表', limit=5, risk='read')
        self.assertNotIn('schedule_update', [t.name for t in result.hits])
        self.assertIn('schedule_update', [t.name for t in result.hidden])

    def test_chinese_tasks_choose_semantically_correct_tool(self):
        cases = {
            '门窗表':'schedule_update', '给这些门窗按型号统计数量':'schedule_update',
            '我想把门窗属性更新到表格':'schedule_update',
            '给既有轴线补上轴号':'grid_label', '把轴号重新编号':'grid_renumber',
            '停车位排布':'parking_layout', '双排车位':'parking_row',
            '检查重合的线但不要删除':'validation_check',
            '清理重复实体':'drawing_refine', '整理图纸碎数':'drawing_round_geometry',
            '按楼层统计建筑面积':'area_schedule',
            '计算这个闭合多段线的面积':'analysis_measure_entity',
            '按这些坐标计算面积':'analysis_measure_area',
            '框选拉伸墙线':'stretch_window',
            '查看我已经选中的对象':'selection_get',
            '让我在图里点选对象':'user_select',
            '只截图不要缩放':'view_screenshot',
            '放大这个范围并截图':'view_zoom_and_screenshot',
            '导出DWG副本和PDF保留原图':'drawing_deliver',
            '另存当前图纸':'drawing_save_as',
            '检查楼梯净高':'stair_check',
            '读取图层模板':'template_list',
            '查看新建图纸模板':'drawing_template_list',
            '识别房间':'arch_rooms_detect', '房间名称':'arch_room',
            '视口比例':'viewport_set_scale', '尺寸链':'dimension_chain',
        }
        for query, expected in cases.items():
            with self.subTest(query=query):
                self.assertEqual(self.search.rank(self.tools, query, limit=1).hits[0].name, expected)

    def test_exact_names_and_brief_cards_are_consistent(self):
        for t in self.tools:
            self.assertEqual(self.search.rank(self.tools, t.name, limit=1).hits[0].name, t.name)
            card = serialize_search_results([t])
            self.assertIn(tool_risk(t), card)
            self.assertTrue(t.meta['cad']['limits'])
            self.assertEqual(t.meta['cad']['risk'], tool_risk(t))

    def test_critical_limits_are_explicit(self):
        self.assertIn('毫米', self.by['arch_dimension_chains'].parameters['properties']['first_offset']['description'])
        self.assertIn('图纸单位', self.by['arch_symbol'].parameters['properties']['params']['description'])
        self.assertIn('通道两侧', self.by['parking_row'].description)
        self.assertNotIn('背靠背', self.by['parking_row'].description)
        self.assertIn('warning', self.by['validation_check'].description)
        self.assertIn('strict_critique', self.by['drawing_deliver'].description)
        self.assertIn('expected_token', self.by['column_place'].description)
        self.assertIn('重建', self.by['schedule_update'].description)
        self.assertIn('600毫米', self.by['arch_rooms_detect'].description)
        self.assertIn('同area_type', self.by['area_schedule'].description)

    def test_no_retired_tool_recommendation(self):
        retired = server.RETIRED_TOOL_NAMES | server.ARCHITECTURE_RETIRED_TOOLS
        for t in self.tools:
            public = t.description + json.dumps(t.parameters, ensure_ascii=False)
            for name in retired:
                self.assertNotRegex(public, r'(?<![a-z_])' + name + r'(?![a-z_])')

if __name__ == '__main__': unittest.main()
