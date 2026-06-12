# CANN Operator Toolbox

[English](README.md) | 简体中文

这是一个面向 Huawei Ascend C / CANN 算子开发工具链的小型桌面工具箱，重点围绕 CANN Operator Development Toolchain 里的 `msopgen`、`msopst`、`msprof`、`mskpp`、`msdebug`、`mssanitizer` 等工具。

第一次从 GitHub 下载使用的同学，建议先看：[同学快速开始](docs/quick_start_zh-CN.md)。

它是给真正拿 Ascend 开发者套件或板子做自定义算子开发的人用的。目标不是替代官方工具，而是把我们在实际开发里反复要跑、反复要解释、反复会踩坑的部分整理成更容易点击、复用和扩展的工作台。

这个项目偏实用：它会把常用 CANN 命令变成表单和按钮，保留可见的生成命令，并附带一些用于 profiling、仿真输出、CSV/JSON 转换和画图的本地脚本。

做这个工具箱，是因为官方工具和文档本身很有用，但在真实板端流程里并不总是够用。有些文档功能并不支持所有板端路径，有些命令必须填特定板子的参数，有些输出也需要额外解析或画图才容易看懂。工具箱会把这些探索结果沉淀成可点击的流程、提醒和小脚本。

它也支持继续扩展。新的脚本可以通过 JSON 插件清单接入，所以后面即使分析脚本继续改，也不需要每次都重写 GUI。

换句话说：这是 CANN 算子开发工具链的实用配套工具。它包含官方工具命令模板、板端实测笔记、我们自己探索补出来的脚本，以及用于新增一键工具的插件格式。

## 主要功能

- 通过 SSH/SFTP 连接板子。
- 为 `msopgen`、`msopst`、`msprof`、`mskpp`、`msdebug`、`mssanitizer` 生成常用命令。
- 提供 JSON 生成器：
  - `msOpGen` 算子描述 JSON。
  - `msOpST` 测试用例 JSON。
- 将部分 profiling / simulator 输出转换成 Excel 报告或图表。
- 在界面里记录 Atlas 200I DK A2 / Ascend310B 路线上的已知注意事项。
- 支持通过 `cann_toolbox/plugins/*.json` 接入插件式脚本。

## 当前状态

这是一个学习和项目实践用工具箱，不是官方 CANN 产品。它适合放在官方 CANN 开发工具旁边，帮助我们把反复使用的算子开发步骤跑得更稳、解释得更清楚。

已知注意事项：

- `msDebug` 实时 NPU kernel 调试在我们当前 Ascend310B4 路线上已标记为不支持，这是本地实测后的结论。
- `msSanitizer` 仍在探索中。界面提供命令模板，但一次干净的“未报错”结果并不能证明算子一定没有内存或竞争问题，前提还包括 kernel 是否正确带了 sanitizer 插桩。
- 很多默认路径来自我们的板端流程，只是示例。换自己的板子或工程时，请在界面里改成自己的路径。

## 环境要求

- Windows。
- Python 3.10 或更高版本。
- Python 包：

```powershell
python -m pip install paramiko openpyxl matplotlib numpy
```

`paramiko` 用于 SSH/SFTP。其他包用于报告和画图脚本。

## 启动

在仓库根目录运行：

```powershell
python .\cann_toolbox\run_toolbox.py
```

如果 `python` 不在 `PATH` 里，可以直接使用 Python 解释器的完整路径：

```powershell
"C:\Path\To\python.exe" .\cann_toolbox\run_toolbox.py
```

## 板端配置

默认板端配置只是示例：

- Host: `192.168.0.2`
- Port: `22`
- User: `HwHiAiUser`
- CANN path: `/usr/local/Ascend/cann-8.5.0`

仓库里不会提交密码。需要时请在界面里输入；只有在自己的本机上才建议使用“保存配置”。

如果使用 USB RNDIS 连接，Windows 侧网卡通常需要配置为：

```text
192.168.0.1 / 255.255.255.0
无网关
```

## 仓库结构

```text
cann_toolbox/                         GUI 应用、配置、插件、文档
官方算子开发工具/msProf/.../tools/     本地 msProf 画图和报告脚本
官方算子开发工具/msOpGen/tools/        本地 trace 报告脚本
agent_tools/                          本地分析用的小辅助脚本
```

中文目录名沿用了原学习项目的组织方式，因为当前工具箱会通过 `{workspace}/...` 占位符引用这些脚本路径。

## 添加自己的脚本

多数本地分析按钮都是插件。想加一个脚本但不改 GUI 代码，可以这样做：

1. 把脚本放到仓库里的某个位置。
2. 在 `cann_toolbox/plugins/` 下新增或修改 JSON 插件清单。
3. 脚本路径使用 `{workspace}/...` 或 `{toolbox}/...`，不要写死本机绝对路径。
4. 填写 `command_template`、输入/输出字段和依赖提示。

当前插件格式见 `cann_toolbox/plugins/PLUGIN_PROTOCOL.md`。

## 安全提醒

- 不要提交 `cann_toolbox/config/toolbox_config.json`，它可能包含本机板端密码。
- Debug、Sanitizer、故意注入 bug 的算子构建都应视为实验构建，不要当作发布版本。
- 发送到板子前，先看一眼生成的命令。

## 许可证

MIT
