# CAD-MCP

面向 AutoCAD 2026 建筑二维制图的 MCP 工具集，基于
[AutoCAD MCP Pro 1.6.0](https://github.com/U-C4N/Autocad-MCP) 的维护版本，保留上游 MIT 许可。

当前版本：**1.6.0.post1**，构建标识 **portable-20261127.1**。
239 项注册、236 项启用；`drawing_deliver`、`drawing_finalize`、`validation_check`继续禁用。

## 安装与启动

需要Git、uv；实际DWG操作需要Windows x64和完整AutoCAD 2026。

```powershell
git clone https://github.com/p645763368/CAD-MCP.git
cd CAD-MCP
uv run --no-project --python 3.14 python scripts/install.py --workspace "D:\CAD_Work"
```

将工作目录换成你自己的路径。安装脚本会构建本仓库代码、按锁定依赖安装、部署三个正式DLL，
并打印当前主机可用的CAD专用配置。**不会改写客户端配置、启动CAD或调整安全设置。**
将生成片段合并到客户端，先打开AutoCAD，再启动MCP连接。

```powershell
autocad-mcp-doctor --require-native
autocad-mcp-config --workspace "D:\CAD_Work"
```

详细说明：[部署与更新](latest/docs/DEPLOYMENT.md)。无需再手工覆盖site-packages或改用户名路径。
自定义原生模块位置可用`--native-root`，SDK编译位置可用`AutoCADInstallDir`/`CAD_MCP_AUTOCAD_DIR`。

## 功能与目录

- 中文检索、COM图纸控制、曲线编辑、局部拉伸、批量属性、尺寸链、绘图顺序及公司配置机制。
- 模型实体批量读取、主视口识别/删除保护、米制面积/尺寸和物理视口比例换算。
- DLL路径按当前用户解析，预编译原生模块随安装包提供。

|位置|内容|
|---|---|
|`pyproject.toml`、`uv.lock`|安装元数据及依赖锁|
|`scripts/install.py`|安装/升级脚本，临时构建环境自动清理|
|`latest/python/`|完整维护源码及通用资源|
|`latest/native/`|三个正式原生模块|
|`latest/native-source/`|对应C#源代码、可配置SDK路径|
|`latest/config/`|通用配置示例、依赖约束；实际本机配置不提交|
|`latest/docs/`|工具目录、部署说明和验证范围|
|`tests/`|隔离路径/安装测试和强制DXF后端协议测试|
|`tools/git_content_filter.py`|可选透明加密授权读取过滤器|

[工具目录](latest/docs/工具目录.md) · [完整参数](latest/docs/工具目录.json) · [许可证](LICENSE)

## 验证和边界

安装及协议验证必须使用干净克隆和独立环境。`tests/test_wire.py`强制`ezdxf`，只创建内存图元，
不启动CAD、不加载DLL、不写项目图或更改默认模板。原生CAD运行仍需目标主机具备兼容软件及许可；
无界面测试不等于所有AutoCAD功能在所有主机均验收通过。

部分高级建筑生成功能仍限毫米模型；尺寸链为非关联尺寸，复杂房间、动态块、外参存在既有能力边界。
工具返回无错误不等于几何正确，写入后应读回；超时须先查状态再决定是否重试。

## 维护约定

本地统一工作目录、运行安装和GitHub对应源码/正式DLL同步维护。分别确认磁盘版本与已载入进程版本，
更新后按需重启MCP；原生DLL有变化时需重新加载或重启CAD。

采用提交白名单，项目图纸、公司项目模板、客户数据、私人配置、迁移备份和测试导出物不入库。
基础包自带的通用模板资源可以随代码分发。每次测试结束后恢复原状并核对清理结果。

透明加密环境只通过已有授权读取获取真实代码；无法得到可读内容就停止提交，不修改加密服务或权限。
普通未加密机器无需配置clean driver。新版本更新使用`git pull --ff-only`后重跑安装脚本，
不要用升级同名上游包替换此维护版本。
