"""Versioned metadata overlay. Changes discovery contracts, never tool signatures.

The manually reviewed catalog targets the deployed COM backend. Original
headless descriptions are retained when explicitly running ezdxf.
"""
from pathlib import Path
import copy,json,re,unicodedata
from mcp.types import ToolAnnotations

REVISION='2026-11-11.arch2'
ROWS={}
for line in Path(__file__).with_name('calibrated_catalog.tsv').read_text(encoding='utf-8').splitlines():
    if line.strip():
        name,risk,summary,limits=line.split('|',3)
        if name in ROWS:raise ValueError('Duplicate catalog entry: '+name)
        ROWS[name]={'risk':{'r':'read','w':'write','d':'destructive'}[risk], 'summary':summary,'limits':limits}

COMMON={
'handle':'目标实体句柄，先从查询结果取得。','handles':'实体句柄列表，先确认属于目标图纸。',
'layer':'图层名称；具体为空或省略语义见后文。','layer_name':'需精确匹配的图层名称。',
'fields':'返回字段投影；不是筛选实体的条件。','compact':'是否使用字段/行组成的紧凑返回格式。',
'limit':'最大返回条数；检查分页及截断标志。','offset':'偏移量；实体分页时表示跳过条数。',
'closed':'是否把末点连接回首点。','color':'颜色值；通常为 ACI，具体例外见后文。',
'lineweight':'线宽枚举值；不是任意毫米实数。','linetype':'线型名称，须已加载或可加载。',
'x':'X坐标。','y':'Y坐标。','x1':'第一点X坐标。','y1':'第一点Y坐标。','x2':'第二点X坐标。','y2':'第二点Y坐标。',
'cx':'中心X坐标。','cy':'中心Y坐标。','cz':'中心Z坐标。','center_x':'中心X坐标。','center_y':'中心Y坐标。',
'origin_x':'原点X坐标。','origin_y':'原点Y坐标。','at_x':'放置基点X坐标。','at_y':'放置基点Y坐标。',
'base_x':'操作基点X坐标。','base_y':'操作基点Y坐标。','radius':'半径，使用相应图形单位。',
'text_height':'文字高度，使用相应图形单位。','row_height':'表格行高，使用相应图形单位。',
'landing_gap':'引线落地段与文字的间距。','arrow_size':'箭头尺寸。','module':'齿轮模数，按机械规格单位。',
'teeth':'齿数，正整数并满足模型要求。','pressure_angle':'压力角，单位度。','helix_angle':'螺旋角，单位度。',
'bore_diameter':'孔径。','keyway_width':'键槽宽；省略时仅在已收录标准范围内推导。',
'keyway_depth':'键槽深度；省略时仅在已收录标准范围内推导。','face_width':'齿宽/轴向面宽。',
'part_no':'零件编号文字。','material':'材料名称或目录标识。','drawn_by':'绘图人文字。','checked_by':'审核人文字。',
'date':'日期文字，不会自动核实。','sheet':'图纸张号文字，如1/1。','revision':'修订版本文字。','company':'公司名称文字。',
'units':'单位标识；作为标题文字时不执行单位换算。','view_count':'计划视图数量。',
'max_rounds':'最多修复轮次，仍受Schema范围约束。','min_score':'最低检查分数阈值，不等于工程质量保证。',
'orientation':'纸张方向，landscape横向或portrait纵向。','columns':'列名列表；可用列依工具的返回数据而定。',
'dry_run':'true 仅预览/预检；false 才执行写入分支。','format':'输出格式，需采用该工具支持的枚举。',
'path':'文件路径；读写方向与后端限制见工具说明。','layout':'布局名称；省略语义见该工具说明。',
'name':'对象或条目名称，使用该工具对应目录中的名称。','points':'坐标点数组，维度和附加字段见后文。',
'spec':'结构化业务规格；字段和单位见后文，不接受任意自然语言。',
'scale':'比例参数；不同工具含义不同，必须遵循本字段的具体说明。',
'tolerance':'几何容差，使用相应图纸单位；后端可能只支持指定值。',
'settings':'设置键值映射；省略/空值是否表示读取见工具说明。',
'save':'关闭前是否保存；保存会写文件。','discard':'是否明确放弃未保存修改。',
'prompt':'向操作人员显示的提示文字；工具会等待人工操作。',
'query':'用于检索目录的关键词。','search':'用于筛选已收录条目的关键词。',
}

OVERRIDES={
('drawing_save_as','format'):'按扩展名确定dwg/dxf/dwt；COM默认DWG为R2018格式，DXF为2013，DWT为2018。需要旧版DWG请用drawing_export_dwg显式指定version。',
('entity_extend','target_handle'):'活动布局内要延伸的LINE句柄；目标图层须未锁定，保留句柄及另一端点。',
('entity_extend','boundary_handle'):'同一活动布局、同高WCS XY平面的有限LINE边界；交点须落在边界线段内，不支持隐式延长边界。',
('entity_extend','end_x'):'端点选择点X；须与end_y同时提供，选择离该点较近的源端点；省略时使用朝向有效外部交点的一端。',
('entity_extend','end_y'):'端点选择点Y；等距不明确、选择背离边界的一端或边界位于源线内部均拒绝。',
('entity_fillet','handle1'):'COM：活动布局中的第一条LINE；两条源线须同高且平行WCS XY。新圆弧继承第一条线的图层/颜色/线型/线宽。',
('entity_fillet','handle2'):'COM：同一活动布局中的第二条LINE。保留距直线交点更远的端；等距时选EndPoint方向，反转端点可改变此时选侧。',
('entity_fillet','radius'):'半径，图纸单位；不得超过可用线段长度或在修剪后消耗整条源线。0且trim=true仅连接尖角，无新ARC，返回第一条源线。',
('entity_fillet','trim'):'true将两条源线近端移到切点（必要时向交点延长）；false完全保留源线，只创建圆弧；半径0且false会拒绝。',
('entity_chamfer','handle1'):'COM：活动布局中的第一条LINE，dist1应用于此线；新倒角线继承其图层/颜色/线型/线宽。',
('entity_chamfer','handle2'):'COM：同高XY平面的第二条LINE，dist2应用于此线；按远端选择保留射线，等距时选EndPoint。',
('entity_chamfer','dist1'):'第一条线从理论交点到倒角端点的距离，须为有限正数；过大或修剪后零长度拒绝。',
('entity_chamfer','dist2'):'第二条线的倒角距离；省略/null时等于dist1，须为有限正数。',
('entity_chamfer','trim'):'true修改两源线近端并创建倒角线；false只加倒角线、源线不变。',

('entity_trim','target_handle'):'COM仅平行WCS XY平面的LINE目标；保留原句柄。其他目标类型明确拒绝。',
('entity_trim','cutter_handle'):'与目标同一图纸空间的LINE/ARC/CIRCLE/二维POLYLINE；仅使用真实交点，不隐式延长切割对象。',
('entity_trim','keep_x'):'保留点WCS X；点须位于目标直线上且不能恰在交点，多个交点时保留包含此点的区段。',
('entity_trim','keep_y'):'保留点WCS Y；无内部交点或保留点不明确时拒绝，不假报裁剪成功。',
('image_attach','scale'):'每像素对应的图纸单位，必须为正；20×10像素且scale=2得到40×20图纸单位，不受DPI影响。size_drawing_units为实际值，size_mm按INSUNITS换算，单位未知时为null。',
('entity_create_table','row_height'):'请求行高，图纸单位；先设文字再设行高。CAD可能因最小尺寸调整，实际值见row_heights/bounds和size_adjusted_by_cad。',
('entity_create_table','column_widths'):'每列请求宽度；实际值见column_widths/bounds，CAD样式或内容可能要求更大尺寸。',

('boundary_trace','tolerance'):'COM仅支持默认1e-9，表示要求现有闭环；不支持自定义补缝，且不宣称原生算法精度为1e-9。ezdxf为端点连接容差。',
('boundary_trace','layer'):'COM中为空考虑可见候选几何；给图层则临时限定该层并将生成边界放在该层，调用后恢复显示状态。',
('boundary_from_entities','handles'):'COM：模型空间WCS XY、z=0平面的1–200个不同句柄；LINE/ARC/CIRCLE/二维POLYLINE。必须组成一个闭环；单圆或单闭合线可用。',
('entity_change_space','freeze_dimensions'):'COM当前不支持标注转换，true 也不会开放标注支持；ezdxf仅在其支持范围内冻结测量文字。',
('entity_change_space','handles'):'COM每次1–32个实体；不支持标注、注释性对象、带属性块等。克隆后删除原对象，后续使用 moved 中的新句柄。',
('entity_change_space','viewport_handle'):'COM仅支持无扭转、无透视、正交俯视的矩形模型视口；整体纸空间视口不可用。',
('entity_create_wipeout','points'):'COM模型空间XY简单多边形，至少3个不同有限坐标点，不能自交/零面积；输出遮挡位于绘图顺序顶部。',
('entity_create_revcloud','segment_length'):'近似弧段的弦向分段长度，使用图纸单位，不是精确圆弧长度；COM至少1e-6、不大于最短输入边，总段数≤10000。',
('entity_create_revcloud','closed'):'COM：true闭合，false保留开放末端；ezdxf现有实现仍生成闭合云线，不应依赖closed=false。',
('text_set_background','color'):'COM无法指定遮罩颜色，此值不生效，使用图纸背景色；ezdxf行为依其实现。',
('entity_set_xdata','values'):'直接值列表：字符串、整数、浮点数、[x,y]；不是[组码,值]列表。替换该应用数据，空列表移除。',
('dimension_auto','handles'):'当前COM仅接受LINE句柄；不能直接传矩形多段线并期待完整自动标注。',
('point_from_snap','snap'):'end端点、mid中点、center中心、quad象限、perp垂足、near近点；perp/near需要参考点。',
('dimstyle_create','preset'):'可选预置：iso-25 或 ansi；不是 iso。省略时遵循工具默认行为。',
('std_part_insert','designation'):'使用 std_part_list 返回的完整目录代号，如 ISO 4017 - M8x30；保留标准号、分隔符和尺寸格式。',
('drawing_deliver','formats'):'只接受 dxf/pdf/png；无论请求哪些格式，都会额外生成规范DXF用于回读校验。不接受dwg。',
('drawing_finalize','save_path'):'若给定，可能在校验前另存并改变文档路径；校验失败不代表没有写文件。',
('drawing_finalize','screenshot_path'):'可选PNG输出路径；可能在校验前写入，外部可读性受透明加密影响。',
('view_screenshot','overlay_handles'):'当前COM不支持句柄叠加；使用false。',
('viewport_create','scale'):'纸空间/模型单位比例，如0.5表示1:2；不是比例分母。',
('viewport_set_scale','scale'):'纸空间/模型单位比例，如0.01表示1:100。',
('viewport_create','view_center_x'):'COM写入视口Target的WCS X；实际画面中心还受DCS ViewCenter影响，创建后应核对。',
('viewport_create','view_center_y'):'COM写入视口Target的WCS Y；不保证等于屏幕中央对应的模型点。',
('drawing_export_dxf','path'):'DXF目标路径；COM通过SaveAs写入，可能覆盖文件并改变活动文档路径；不是仅导出副本。',
('drawing_export_dwg','path'):'DWG目标路径；COM通过SaveAs写入，可能覆盖文件并改变活动文档路径。',
('drawing_template_save','path'):'模板输出路径；COM另存可能重新绑定当前文档，存在覆盖风险。',
('analysis_measure_area','points'):'至少3个顶点，[x,y]或[x,y,bulge]；bulge定义从该顶点出发的圆弧。计算的是这些参数，不读取已有图形。',
('analysis_find_in_region','x1'):'矩形角点WCS X，反向角点允许；交叉选择包含穿越矩形边界的实体。',
('analysis_select_by_layer','layer_name'):'按字面精确匹配图层，#等字符不会当作通配符；不存在/空层的返回需核对列表。',
('analysis_select_by_type','entity_type'):'COM按实际ActiveX名称匹配，如LINE、CIRCLE、POLYLINE、BLOCKREFERENCE；不要假定所有DXF别名都支持。可先 entity_list 查看type。',
('drawing_preflight','scale'):'计划几何缩放比例，如1.0表示1:1、0.1表示1:10；不是比例分母。',
('entity_list','compact'):'仅true返回total/truncated/next_offset；false返回普通列表，满页时不能判断是否完整。',
('user_select','mode'):'single等待单个实体并返回点选位置；multiple等待多选。取消/超时有明确标志，不得按成功选中处理。',
}
READPATH_TOOLS={'drawing_understand','drawing_scale_check','drawing_diff','drawing_topology_check','pipe_takeoff','cable_takeoff'}
READPATH_KEYS={'path','reference','old_path','new_path','pid_path','layout_path'}
ARCH_SCALES={'arch_stair','arch_dimension_chains','arch_room','arch_schedule','arch_grid','arch_symbol'}

ALIASES={
'analysis_measure_entity':['已有对象面积','测量现有闭合多段线面积','读取闭合轮廓周长','读取图形周长'],
'analysis_measure_area':['按坐标算面积','顶点面积','多边形面积计算'],
'boundary_trace':['自动识别封闭边界','拾取内部点生成边界','自动找轮廓','边界生成'],
'boundary_from_entities':['线段拼接闭环','连接选定线段成轮廓','线弧围合'],
'entity_create_revcloud':['画云线','修订云线','修改云线','云状线'],
'entity_create_wipeout':['区域覆盖','遮挡底图','消隐遮罩','遮挡区域'],
'entity_change_space':['模型转布局','布局转模型','图纸空间转模型空间','模型空间转图纸空间'],
'drawing_understand':['读图','分析图纸','了解图纸内容','读取加密图纸'],
'drawing_diff':['对比两版图纸','版本差异','图纸比对','找出改动'],
'drawing_scale_check':['核对图纸比例','检查图纸比例','比例一致性'],
'drawing_topology_check':['检查断头线','查找管线缺口','检查网络连接','拓扑检查'],
'pipe_takeoff':['统计管线长度','管道工程量','管线算量'],
'cable_takeoff':['电缆工程量','统计电气负载','电缆算量'],
'user_select':['让我点选对象','人工选择对象','等待用户选择'],
'selection_get':['读取当前选中对象','获取预选对象','已选对象'],
'user_pick_point':['让我点一个位置','人工取点'],
'entity_create_mtext':['多行文本','创建文字段落','写多行字'],
'entity_create_text':['单行文本','写一行字'],
'leader_create_mleader':['箭头说明','带箭头的文字','创建引线标注'],
'analysis_select_by_layer':['按图层查找对象','找出图层上的实体'],
'analysis_find_in_region':['查询区域内对象','交叉选择矩形范围'],
'drawing_export_dxf':['导出dxf','另存dxf'],
'drawing_export_pdf':['导出pdf','打印pdf'],
'drawing_export_dwg':['导出dwg','保存dwg'],
'layer_delete':['删除图层','删掉空图层'],
'entity_delete':['删除对象','删除实体'],
'drawing_save':['保存图纸','保存当前图纸'],
'drawing_save_as':['图纸另存为','另存图纸'],
'block_create_from_entities':['制作块定义','把线做成块'],
'block_insert':['插入图块','插入带属性块'],
'block_explode':['炸开块','炸开图块','分解图块'],
'system_capabilities':['功能支持','支持哪些功能','能力列表','后端能力'],
'view_screenshot':['截图','只截图','当前画面截图'],
'view_zoom_and_screenshot':['缩放并截图','调整显示范围并截图','放大后截图'],
'arch_rooms_detect':['识别房间','统计封闭房间'],
'arch_room':['房间面积标注','房间名称标注'],
'arch_schedule':['生成门窗表','房间明细表'],
'drawing_template_list':['查看图纸模板'],
'template_list':['查看图层模板'],
}

# Common short Chinese commands; explicit aliases outrank fuzzy overlap.
for _name,_phrases in {'entity_create_circle': ['画圆', '圆', '画一个圆', '绘制圆形'], 'entity_create_line': ['画线', '直线', '画直线'], 'entity_create_rectangle': ['矩形', '画矩形', '长方形'], 'entity_create_polyline': ['多段线', '画多段线'], 'entity_create_arc': ['圆弧', '画弧'], 'entity_fillet': ['圆角', '倒圆角'], 'entity_chamfer': ['倒角', '倒斜角'], 'entity_move': ['移动', '平移'], 'entity_copy': ['复制'], 'entity_rotate': ['旋转'], 'entity_trim': ['修剪', '裁剪'], 'entity_extend': ['延伸', '延长线'], 'entity_offset': ['偏移', '偏移线'], 'layer_list': ['读取图层', '图层列表', '列出图层', '查看图层'], 'drawing_purge': ['清理', '清理图纸', '清除未使用定义'], 'drawing_refine': ['自动整理', '自动修复图纸'], 'drawing_scale_check': ['比例检查'], 'drawing_template_save': ['保存模板'], 'entity_create_hatch': ['填充', '图案填充']}.items():
    ALIASES.setdefault(_name,[]).extend(_phrases)

def parameter_description(name,key,field):
    if name.startswith('arch_') and key=='lang':return '输出语言：zh中文、en英文、tr土耳其文；zh门窗自动编号前缀M/C；比例与字体由对应样式决定。默认保持原工具默认语言。'
    if (name,key) in OVERRIDES:base=OVERRIDES[name,key]
    elif name in READPATH_TOOLS and key in READPATH_KEYS:
        base='COM：完整路径必须对应AutoCAD中已打开的DWG/DXF，读取包含未保存修改的内存状态；省略时按本工具约定读取当前文档。ezdxf：直接读取可读DXF文件。'
    elif key=='scale' and name in ARCH_SCALES:base='出图比例分母，如50表示1:50；符号/文字按纸面尺寸乘该数。'
    elif key=='scale' and name in {'titleblock_apply','titleblock_apply_iso_a3'}:base='标题栏比例文字，如1:100；不执行几何缩放。'
    else:
        old=' '.join(field.get('description','').split())
        if not old and key not in COMMON:raise ValueError(f'Unreviewed empty parameter description: {name}.{key}')
        base=COMMON.get(key,'')+old
    suffix=[]
    for k,sign in [('minimum','≥'),('exclusiveMinimum','>'),('maximum','≤'),('exclusiveMaximum','<')]:
        if k in field:suffix.append(sign+str(field[k]))
    if field.get('enum'):suffix.append('枚举='+','.join(map(str,field['enum'])))
    if 'default' in field:suffix.append('默认='+json.dumps(field['default'],ensure_ascii=False,separators=(',',':')))
    return base+(' ['+'；'.join(suffix)+']' if suffix else '')

def apply_catalog(tools,backend='com'):
    names={t.name for t in tools}
    if names!=set(ROWS):raise ValueError(f'Catalog/registry mismatch: missing={names-set(ROWS)}, extra={set(ROWS)-names}')
    for t in tools:
        original_description=t.description
        row=ROWS[t.name];risk=row['risk'];meta=copy.deepcopy(t.meta or {});cad=meta.setdefault('cad',{})
        legacy_search=cad.get('summary','') or original_description.splitlines()[0]
        aliases=ALIASES.get(t.name,[])+[row['summary']]
        cad.update(summary=row['summary'],limits=row['limits'],risk=risk,reviewed_backend='com',catalog_revision=REVISION,zh_aliases=aliases,
                   search_terms_en=legacy_search,
                   cost='escape' if cad.get('cost')=='escape' or t.name in {'system_run_command','system_run_lisp'} else {'read':'read','write':'mutate','destructive':'destructive'}[risk])
        t.meta=meta
        english=t.name.replace('_',' ')
        risk_text={'read':'只读查询，不写入图形或输出文件。','write':'创建/修改实体、图纸设置或交互状态；先确认活动文档。','destructive':'可能删除/替换对象、覆盖文件或执行高影响操作；按可选参数的最高风险标记。'}[risk]
        t.description=f"{row['summary']}。\n限制/副作用：{row['limits']}。\n风险：{risk_text}\n检索：{english}。"
        if backend=='com' and (t.name.startswith('entity_create_') and t.name not in {'entity_create_wipeout','entity_create_revcloud'} or t.name in {'leader_create_mleader','dimension_linear','dimension_aligned','dimension_angular','dimension_radius','dimension_diameter'}):
            t.description+='\nCOM新增图形进入活动布局；坐标仍按WCS，长度按图纸单位。'
        if backend=='ezdxf':
            # COM-only restrictions must not replace a headless contract.
            t.description=f"{row['summary']}。\n当前为ezdxf后端，COM限定条款不适用。\n"+original_description
        schema=copy.deepcopy(t.parameters)
        for key,field in schema.get('properties',{}).items():field['description']=parameter_description(t.name,key,field)
        t.parameters=schema
        previous=t.annotations.model_dump(exclude_none=True) if t.annotations else {}
        previous.update(readOnlyHint=risk=='read',destructiveHint=risk=='destructive',idempotentHint=risk=='read')
        t.annotations=ToolAnnotations(**previous)

def _zh_words(text):
    runs=re.findall(r'[\u3400-\u9fff]+',unicodedata.normalize('NFKC',text))
    return {r[i:i+2] for r in runs for i in range(len(r)-1)}

def zh_score(tool,query):
    cad=(tool.meta or {}).get('cad',{})
    if not re.search(r'[\u3400-\u9fff]',query):return 0.0
    query=unicodedata.normalize('NFKC',query).lower()
    phrases=[unicodedata.normalize('NFKC',p).lower() for p in [cad.get('summary',''),*cad.get('zh_aliases',[])]]
    if query.strip() in [p.lower() for p in phrases]:return 20.0
    score=0.0
    q=_zh_words(query)
    for phrase in phrases:
        phrase=phrase.lower()
        if phrase and phrase in query:score=max(score,8+min(len(phrase),30)/100)
        terms=_zh_words(phrase)
        if terms and q:
            shared=len(terms&q)
            if shared>=2 or (len(q)==1 and shared==1):score=max(score,3*shared/(len(terms)+len(q)-shared))
    # Keep semantic neighbors distinct; these boosts supplement lexical search.
    if '面积' in query and any(w in query for w in ['已有','已经','现有','画好','句柄']):
        if tool.name=='analysis_measure_entity':score+=9
    if '面积' in query and any(w in query for w in ['顶点','坐标']):
        if tool.name=='analysis_measure_area':score+=9
    if any(w in query for w in ['种子','内部点','封闭边界','闭合边界']) and any(w in query for w in ['自动','生成','识别','查找']):
        if tool.name=='boundary_trace':score+=8
    if '模板' in query and '图层' in query and tool.name=='template_list':score+=5
    if '模板' in query and '图纸' in query and tool.name=='drawing_template_list':score+=5
    if '截图' in query:
        if any(w in query for w in ['只截图','不改变','不缩放']):
            if tool.name=='view_screenshot':score+=10
        elif any(w in query for w in ['缩放','调整','范围','放大']):
            if tool.name=='view_zoom_and_screenshot':score+=9
    return score
