# CAD-MCP

**面向 AutoCAD 2026 建筑二维制图的 AI 工具集。** 通过 MCP（模型上下文协议），让支持 MCP 的 AI 客户端读取当前图纸，并按你的指令调用绘图、编辑、标注和检查工具。

基于 [AutoCAD MCP Pro 1.6.0](https://github.com/U-C4N/Autocad-MCP) 持续维护，重点补充建筑制图能力、中文工具检索和跨主机部署。

当前版本：**1.6.0.post1** · 构建：**portable-20261127.1** · 注册 **239** 项工具，默认启用 **236** 项。

[开发原因](#为什么开发) · [功能介绍](#能做什么) · [适配环境](#适配环境) · [安装使用](#安装与首次使用) · [使用示例](#日常使用示例) · [更新方法](#更新方法)

## 为什么开发

建筑日常制图中，图层整理、实体属性修改、尺寸标注、房间统计和布局检查经常需要反复操作。仅靠对话提供绘图建议，仍然需要设计师逐条执行命令；通用 CAD 工具也未必能准确处理建筑图层习惯、单位差异和现有项目图纸。

本项目希望把明确、可核对的制图任务交给 AI 执行，让设计师把更多时间放在空间组织和设计判断上。维护重点包括：

- **贴近建筑工作流**：围绕二维平面、墙门窗、房间、尺寸、图层与布局组织工具。
- **更容易选对工具**：补充中文搜索，校准用途、参数和风险说明，保留明确的能力边界。
- **能检查实际结果**：支持读取实体、属性、单位和文档状态，方便在修改前后核对。
- **换电脑可以部署**：去除维护者用户名和固定安装路径依赖，提供安装脚本、依赖锁和原生模块。

设计判断和成果审查仍由使用者负责。项目定位是建筑二维制图辅助，不是完整 BIM 建模系统或自动设计审查系统。

## 能做什么

|能力|典型用途|代表工具|
|---|---|---|
|图纸与实体查询|确认活动图纸、保存状态、图层及实体属性；按区域或类型定位对象|`document_list`、`drawing_info`、`analysis_find_in_region`|
|二维绘制与编辑|绘制基础图元，修剪、延伸、连接曲线及局部拉伸|`curve_trim`、`curve_extend`、`curve_join`、`stretch_window`|
|图层、样式与公司标准|整理实体属性，选用公司图层映射，从已打开图纸导入指定标准|`arch_company_profile`、`arch_profile_config`、`drawing_import_standards`|
|建筑平面辅助|按参数生成墙体网络、门窗洞口、楼梯、轴网及建筑符号|`arch_wall`、`arch_opening`、`arch_stair`、`arch_grid`|
|房间与明细|识别闭合房间、标注名称和面积、输出房间或门窗记录表|`arch_rooms_detect`、`arch_room`、`arch_schedule`|
|尺寸与单位|创建线性、对齐、角度和链式尺寸；核对图纸单位|`dimension_chain`、`dimension_aligned`、`drawing_unit_context`|
|块与属性|插入已有块，读取和修改块属性，使用家具及洁具目录|`block_insert`、`block_set_attributes`、`arch_catalogue_insert`|
|布局与输出|查询视口、设置比例、锁定视口、输出 PDF 或批量打印|`viewport_list`、`viewport_set_scale`、`batch_plot`|
|检查与整理|统计对象，检查重复几何及图纸问题，审计图纸数据库|`analysis_entity_stats`、`drawing_critique`、`drawing_audit`|

工具可组合完成多步骤任务，但组合结果取决于图纸质量、参数和 AI 对任务的理解。尤其是“识别客房”“判断门属于哪个房间”等语义任务，需要结合图中标注、几何关系和使用者确认，不能仅凭闭合区域推断用途。

完整列表见 [工具目录](latest/docs/工具目录.md) 和 [参数目录](latest/docs/工具目录.json)。执行时应读取当前连接返回的参数与限制。

## 适配环境

|项目|要求与说明|
|---|---|
|日常 DWG 制图|**Windows x64 + 完整版 AutoCAD 2026**，需可正常使用的 AutoCAD 许可|
|CAD 连接方式|COM 连接已打开的 AutoCAD；默认 `AutoCAD.Application.25.1`|
|AI 客户端|支持本地 **STDIO MCP** 的客户端；本项目已在 Codex 中验证|
|安装工具|Git、uv；安装时需要获取 Python 和依赖的网络条件|
|Python|项目声明 3.11 及以上；当前安装验证使用 **3.14**，建议采用下方命令|
|仓库访问|这是私有仓库，克隆账户必须具备访问权限|
|原生模块|安装包附带三个 AutoCAD 2026 DLL，普通使用不需要自行编译|
|可选源码编译|修改 C# 模块时需 .NET 8 SDK 和 AutoCAD 2026 对应程序集|

**未承诺适配 AutoCAD LT、其他 AutoCAD 年份或其他 CAD 品牌。** macOS/Linux 不支持本项目的 AutoCAD COM 工作流。

另有 `ezdxf` 后端供无 AutoCAD 的 DXF 处理及隔离验证使用；它不等同于 DWG 原生读写，也不覆盖全部建筑工具。当前跨主机安装验证是在同一台 Windows 主机的干净克隆和模拟不同用户路径中完成，尚不能代表所有电脑均已验收。

## 安装与首次使用

### 1. 准备环境和工作目录

安装 Git、uv 和 AutoCAD 2026。在 PowerShell 中确认 `git --version`、`uv --version` 能运行。确保当前 Git 凭据有本私有仓库的读取权限。

准备一个实际使用的本地图纸目录，例如 `D:\CAD_Work`。下文路径只是示例，请替换成自己的**绝对路径**；目录名不能包含逗号。

### 2. 克隆并安装

```powershell
git clone https://github.com/p645763368/CAD-MCP.git
cd CAD-MCP
uv run --no-project --python 3.14 python scripts/install.py --workspace "D:\CAD_Work"
```

安装脚本会：

1. 构建当前仓库代码，并按锁定依赖安装到独立运行环境。
2. 将三个正式 DLL 部署到当前用户的 AutoCAD 插件目录。
3. 检查安装结果，打印命令所在目录和当前主机的 CAD 专用 MCP 配置。

默认运行环境位于 `%LOCALAPPDATA%\CAD-MCP\runtimes\<源码摘要>`，原生模块位于 `%APPDATA%\Autodesk\ApplicationPlugins`。不同代码版本并列安装，避免覆盖正在运行的 Python 环境。

安装器**不会自动修改客户端配置、启动 AutoCAD、调整 CAD 安全设置或修改 PATH**。

### 3. 将配置接入 AI 客户端

将安装结束时打印的 CAD 配置片段合并到客户端的 MCP 配置中，保留其他已有连接。使用脚本生成的绝对 `command` 路径，不要照抄别人的用户名或运行目录。

安装器默认输出 TOML。使用其他客户端时，按该客户端要求映射 `command`、`env` 等字段；仓库提供 [TOML 配置示例](latest/config/autocad-mcp.example.toml)，但其中占位路径不能直接使用。

`--workspace` 会生成 `ALLOWED_PATHS`，指定允许文件操作的目录；它不会自动打开图纸。需要多个项目目录时，可重复传入 `--workspace`。

### 4. 打开 AutoCAD，检查连接

先打开 AutoCAD 2026 和一张准备操作的图纸，再启动或重新加载客户端的 CAD-MCP 连接。向 AI 发送：

> 检查 CAD-MCP 连接，报告版本、活动图纸和保存状态，暂不修改图纸。

当前版本的预期状态：

```text
version:    1.6.0.post1
build:      portable-20261127.1
backend:    com
connected:  true
tool_count: 239
```

默认采用工具搜索模式：客户端可能只直接显示 `search_tools` 和 `call_tool` 两个入口。AI 先检索具体工具，再通过调用入口执行；这不表示其他工具未注册。

首次使用原生功能时，AutoCAD 可能请求加载 DLL。核对名称后按提示处理：`CadMcpNative2026.dll`、`CadMcpArch2026V2Safe.dll`、`CadMcpProjectFix2026.dll`。

### 5. 开始制图

第一次使用建议操作项目副本。指令尽量说明**目标图纸、对象范围、修改规则、单位和是否保存**。操作后要求 AI 读回结果；需要保存时明确说明保存位置。

## 日常使用示例

以下是对 AI 客户端说的话，不是 PowerShell 命令。

**先了解图纸**

> 检查当前图纸的单位、图层和模型空间实体数量。列出未保存状态，先不要修改。

**按已知规则整理图层**

> 在当前项目副本中，把我选中的门短线移到 A-SingleDoor 图层。先核对选中对象，修改后报告数量，暂不保存。

**标注尺寸**

> 根据我指定的这些点生成水平尺寸链。先核对图纸实际单位，尺寸文字按毫米显示，完成后读回检查。

**识别房间**

> 在指定墙线范围内识别闭合房间，先报告候选数量和面积，不确定的区域列出来；确认后再写房间名称。

**检查布局**

> 列出当前布局的普通视口和比例，区分纸空间主视口。将指定普通视口设为 1:100 并锁定，保留其他视口。

## 已知限制

- 默认禁用 `drawing_deliver`、`drawing_finalize`、`validation_check` 三个入口。注册数不代表全部工具及所有参数分支都已验证可用。
- 部分高级建筑生成功能仍要求毫米模型；不能把个别工具的米制适配理解为所有工具支持任意单位。
- 尺寸链为非关联尺寸；修改原几何后不能假定尺寸会自动跟随更新。
- 房间识别依赖边界质量。复杂房间、动态块、外参及既有图纸的语义识别存在限制；部分建筑明细依赖工具自身记录。
- 透明加密环境下，通过 COM 读取已打开图纸可减少对磁盘文件解析的依赖，但不能保证导出的 DWG、DXF、PDF 在其他程序中可读。
- 直接文件操作受允许目录和安全策略限制；当前策略拒绝网络 UNC 路径的直接文件操作。
- 超时不等于没有执行。应先检查当前 CAD 状态和结果，避免重复修改。工具返回成功后也应读回几何或属性。

## 更新方法

在本仓库目录中执行：

```powershell
git pull --ff-only
uv run --no-project --python 3.14 python scripts/install.py --workspace "D:\CAD_Work"
```

把新输出的 `command` 路径更新到 CAD-MCP 连接，再重启该 MCP 连接并核对 `system_status`。如果原生 DLL 有变化且已被 CAD 加载，应先保存自己的工作、关闭 AutoCAD，再安装和启动。

不要用 `uv tool upgrade autocad-mcp-pro` 替代此流程，它可能安装同名上游包，而不是本仓库的维护代码。仅修改 README 等说明文件不需要重新安装服务。

更多配置、多个工作目录、自定义 DLL 位置、诊断命令及 C# 编译方法见 [部署与更新说明](latest/docs/DEPLOYMENT.md)。

## 常见问题

|现象|处理方法|
|---|---|
|无法克隆私有仓库|确认当前 GitHub 账户被授予仓库权限，并已配置 Git 凭据|
|找不到 `uv`|先安装 uv 并确认其命令可在当前 PowerShell 中运行|
|找不到 `autocad-mcp-doctor` 等命令|安装器不修改 PATH；使用安装输出的命令目录中的完整路径，PowerShell 调用带空格路径时使用 `& "完整路径.exe"`|
|连接失败或活动图纸不对|先打开 AutoCAD，检查客户端启动路径和环境变量，再核对 `document_list`；不要直接在错误图纸上重试写入|
|更新后仍显示旧 build|重新加载 CAD-MCP 连接；仅更新磁盘文件不会替换已运行的进程|
|DLL 无法替换|确认自己的图纸已妥善保存后关闭 AutoCAD，再安装；不要关闭安全加载检查|

## 源码与验证资料

|位置|内容|
|---|---|
|`latest/python/`|维护中的 Python 源码及通用资源|
|`latest/native/`、`latest/native-source/`|三个正式 DLL 及对应 C# 源码|
|`scripts/install.py`|安装与更新脚本|
|`pyproject.toml`、`uv.lock`|包元数据与依赖锁|
|`latest/config/`|通用配置示例和安装依赖约束|
|`latest/docs/`|工具目录、部署说明和验证记录|
|`tests/`|路径、安装和无界面协议测试|
|`latest/metadata/`|上游来源信息；当前维护版本以根目录 `pyproject.toml` 为准|

[跨主机部署验证记录](latest/docs/PORTABILITY-VALIDATION.md)记录了干净克隆、独立安装、11 项测试、STDIO 协议和当前 COM 连接的验证范围。无界面测试不代表所有 AutoCAD 功能均通过实机验收。

维护时同步源码、正式运行文件与 GitHub；分别确认磁盘部署和进程实际载入状态。项目图纸、公司项目模板、客户数据、私人配置、备份及测试导出物不提交；通用模板资源可随代码分发。每次测试后恢复原状并核对清理结果。

透明加密环境仅通过已有授权读取获取真实代码，无法读取明文时停止提交，不修改加密服务或权限。普通未加密机器不需要额外配置仓库的内容过滤器。

## 来源与许可

基于 [U-C4N/Autocad-MCP](https://github.com/U-C4N/Autocad-MCP) 维护，保留 MIT 许可及上游声明，详见 [LICENSE](LICENSE) 和 [NOTICE.md](NOTICE.md)。AutoCAD 本身及相关 Autodesk 组件需遵守各自的许可条件。
