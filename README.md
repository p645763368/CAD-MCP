# CAD-MCP

面向 AutoCAD 2026 建筑二维制图的本地修改版 MCP 工具集。基于
[AutoCAD MCP Pro 1.6.0](https://github.com/U-C4N/Autocad-MCP)，保留上游 MIT 许可证。

当前实现快照与本机部署文件已于 **2026-11-27** 核对一致。239 项注册、236 项启用；
`drawing_deliver`、`drawing_finalize`、`validation_check` 继续禁用。

## 主要内容

- Windows COM 控制当前 AutoCAD，支持中文工具检索。
- 建筑曲线编辑、局部拉伸、批量属性、尺寸链、绘图顺序和公司配置机制。
- 模型实体批量读取、主视口识别和删除保护。
- 图纸单位校核、米制面积/尺寸及物理视口比例换算。
- 三个 AutoCAD 2026 原生桥接模块及对应 C# 源码。

## 目录

|目录|内容|
|---|---|
|`latest/python/`|当前修改版 Python 源码及基础包模板资源|
|`latest/native/`|三个当前使用的原生 DLL，按 bundle 目录组织|
|`latest/native-source/`|对应 C# 源码和 .NET 项目|
|`latest/docs/`|当前工具摘要及完整参数目录|
|`latest/config/autocad-mcp.example.json`|不含本机或项目路径的配置示例|
|`latest/metadata/`|上游包依赖、入口及许可信息|
|`tools/git_content_filter.py`|本机透明加密环境使用的可选 Git clean driver|

[工具目录](latest/docs/工具目录.md) · [完整参数](latest/docs/工具目录.json) · [许可证](LICENSE)

## 部署范围

本仓库是修改版源码与二进制快照，不包含 Python 解释器、完整第三方环境或 Autodesk SDK。
目前部署针对 Windows、完整 AutoCAD 2026 与 `AutoCAD.Application.25.1`。

1. 先建立兼容的 Python 环境，并安装 `autocad-mcp-pro[full]==1.6.0` 基础依赖。
2. 备份该环境的原有文件，将 `latest/python/` 覆盖到对应 `site-packages`；包括新增的顶层模块。
3. 将 `latest/native/` 中三个 bundle 放入目标用户的 Autodesk ApplicationPlugins 目录。
4. 检查 `arch_tools.py`、`project_fixes.py`、`backends/com_features.py` 中的本机 DLL 路径。
   当前源码保留实际部署路径，换机器时必须调整并同步源码与运行安装。
5. 按配置示例合并 CAD 专用连接设置，修正启动命令和 `ALLOWED_PATHS`，然后重启 MCP。
   配置示例为 JSON 结构说明，不可直接替换 Codex 的整份 TOML 配置。
6. 如 AutoCAD 请求安全加载确认，核对模块后加载；不要关闭安全加载检查。

原生项目使用 .NET 8 Windows/x64，并引用已安装的 AutoCAD 2026 程序集。
不要直接升级基础包覆盖本地修复；本次仅做推送前静态校验，没有重新安装或修改运行环境。

## 已知边界

- 注册成功不代表全部参数分支经过现场验收。
- 部分高级建筑生成功能仍限毫米模型，非毫米单位会在执行前拒绝。
- 尺寸链为非关联尺寸；任意既有线稿的全自动标注及复杂避碰尚未完成。
- 复杂房间边界、动态块、外参等仍存在适用范围限制。
- 使用前确认活动文档、单位和目标句柄。超时可能留下副作用，必须读回后再决定下一步。

## 维护与安全

开发与更新在本地统一 CAD-MCP 工作目录进行。每次更新分别确认：文件同步、MCP进程载入、
AutoCAD模块载入。测试须隔离，结束后恢复原状态并清理测试文件、模板选择和系统设置。

仓库采用提交白名单；业务图纸、项目结果、历史私人配置、迁移备份和测试导出物保留在本地。
`latest/python/templates/` 是基础发行包附带的通用资源，不是项目图纸。

在透明加密环境中，普通 Git 读取可能获得加密包装。本机配置了可选 clean driver：仅通过
已有授权文件读取接口获取源码，不修改加密服务或安全设置；若仍读到包装则拒绝提交。
普通未加密机器无需配置该 driver。首次在另一加密环境提交前，应先验证暂存内容可读。
