# 克隆、安装与升级

## 前提

- 实际DWG/COM制图：Windows x64、完整AutoCAD 2026及相应许可，先手动打开AutoCAD。
- 无界面验证：DXF后端不需要AutoCAD；它不能替代DWG原生读写或所有建筑原生操作。
- 安装Git和uv，私有仓库需要你自己的GitHub访问权限。不要共享个人令牌。
- 项目支持Python 3.11及以上；本轮现场安装验证使用Python 3.14。优先按下方命令使用3.14。

## 新主机安装（PowerShell）

```powershell
git clone https://github.com/p645763368/CAD-MCP.git
cd CAD-MCP
uv run --no-project --python 3.14 python scripts/install.py --workspace "D:\CAD_Work"
```

把工作目录换成该主机实际绝对路径。脚本构建当前检出的代码，按锁定依赖安装为uv工具，
部署三个正式DLL，并在末尾打印当前主机的**CAD专用TOML片段**。将该片段合并到MCP客户端，
不要覆盖其他连接或上传生成的本机配置。安装脚本不自动改客户端文件、不启动CAD、不改注册表。

安装脚本使用独立版本目录：Windows默认在`%LOCALAPPDATA%\CAD-MCP\runtimes\<源码摘要>`，
不同源码/依赖版本使用不同环境，避免删除正在运行的MCP文件。同一版本重复安装会核对源码并复用环境。
如果指定的`UV_TOOL_DIR`已有未知或不匹配的安装，脚本在写入前拒绝覆盖。

脚本不修改PATH，因此下文工具命令未在PATH时，请使用输出的命令目录或生成片段里的绝对路径。
更新后把生成的新`command`合并到CAD连接，再重启该连接。不要手动对运行中的旧环境执行强制替换。

可重复指定允许的项目根目录：

```powershell
autocad-mcp-config --workspace "D:\CAD_Work" --workspace "E:\SharedCAD"
```

`ALLOWED_PATHS`不支持包含逗号的路径。此设置限制工具文件访问，不会自动打开或保存图纸。
现有安全策略仍拒绝网络UNC文件路径的直接文件操作；已打开CAD文档的COM读取有其原有边界。

## DLL路径

默认使用当前用户 `%APPDATA%\Autodesk\ApplicationPlugins`；APPDATA未设置时从当前用户home推导。
三个模块分别为CadMcpNative2026、CadMcpArch2026V2Safe、CadMcpProjectFix2026。

指定其他位置时，安装和启动配置必须使用同一根目录：

```powershell
uv run --no-project --python 3.14 python scripts/install.py --workspace "D:\CAD_Work" --native-root "E:\CAD_Plugins"
```

生成的配置会写明`CAD_MCP_NATIVE_ROOT`。此变量必须是绝对路径；设置错误不会静默回退到另一套DLL。
DLL随wheel携带，无需从维护者机器另拷文件。安装器只复制这三个DLL，内容相同则不覆盖，不删除其他插件。
如果DLL被AutoCAD占用，先保存自己的工作并关闭AutoCAD，再重新执行安装；安装器不会替你关闭CAD。

首次调用原生功能可能请求AutoCAD加载确认。核对模块名称后按CAD提示加载，绝不能关闭安全加载检查。
已载入程序集不能原位换版本；Python进程也不会自动热更新，更新后按需重启CAD与MCP客户端。

## 安装检查与启动

```powershell
autocad-mcp-doctor --require-native
autocad-mcp --help
```

doctor只读文件及版本，不连接CAD。实际COM连接需在MCP客户端调用`system_status`，检查
`version=1.6.0.post1`、`build=portable-20261127.1`以及实际后端状态。
注册数量239不代表239项工具在每台机器上所有分支均可用。

命令行直接启动示例：

```powershell
$env:AUTOCAD_MCP_BACKEND = "com"
$env:ALLOWED_PATHS = "D:\CAD_Work"
autocad-mcp
```

STDIO服务等待MCP协议输入，不应直接把普通文字输进去；日志走stderr。

## 无CAD的隔离检查

安装时可使用`--backend ezdxf --skip-native`。实际独立验证应设置独立的`UV_TOOL_DIR`、
`UV_TOOL_BIN_DIR`和`CAD_MCP_NATIVE_ROOT`，避免替换你正在使用的安装。运行`tests/test_wire.py`
必须使用待验证安装自己的Python，而不是维护者原环境。测试强制DXF后端，仅创建内存图元，
结束后关闭子进程并删除临时目录，不触碰AutoCAD或模板选择。

## 更新

工作目录保持干净后`git pull --ff-only`，再执行同一安装命令，并合并新启动路径。脚本按当前checkout构建，
不会从PyPI安装未包含这些修复的同名上游包。不要用普通`uv tool upgrade autocad-mcp-pro`
替代本仓库更新流程；uv收据中构建wheel的临时路径在完成后会删除。

依赖主约束在pyproject.toml，传递版本记录在uv.lock及latest/config/dependencies.lock.txt。
安装脚本默认使用后者，逐项传递精确依赖以兼容带空格的路径；改变依赖时重新解析、验证并同步两份锁记录。
旧正式运行环境不自动删除；确认没有客户端再使用且无需回退后再清理。验证使用的隔离环境则应在结束后删除。

## 编译原生桥（可选）

预编译DLL可直接部署，只有修改C#时才需要.NET 8 SDK和AutoCAD 2026程序集：

```powershell
dotnet build latest/native-source/CadMcpProjectFix2026/ProjectFix.csproj -c Release -p:AutoCADInstallDir="E:\Autodesk\AutoCAD 2026"
```

也可设置环境变量`CAD_MCP_AUTOCAD_DIR`。默认从`ProgramW6432`推导AutoCAD 2026路径；缺少程序集会明确报错。
Autodesk SDK DLL不随本仓库分发。构建后须同时更新对应latest/native中的DLL及实际部署，并验证三方一致。

## 私人文件与测试恢复

白名单仅提交代码、正式模块、通用资源、说明和示例配置。项目DWG、私人配置、迁移回退资料及
测试导出图不入库。透明加密环境只能通过已授权读取获取真实代码；若仍是TSD包装应停止提交。

任何CAD现场测试开始前记录原图、模板、变量和加载状态；结束或失败恢复后清理测试残留。
此次克隆验证不修改正式CAD，不能把无界面协议测试宣称为另一台物理主机上的完整AutoCAD验收。
