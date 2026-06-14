# Changelog

English | 简体中文

All notable changes to this project will be recorded here.

本文件用于记录 CANN Operator Toolbox 的重要更新：新增功能、行为变化、修复内容和已知注意事项。

The format loosely follows Keep a Changelog, and this project uses simple version numbers such as `0.1.0` while it is still young.

## [Unreleased]

Changes that have been made locally but are not part of a tagged release yet.

尚未发布成版本的本地改动会先放在这里。

## [0.1.3] - 2026-06-13

### Added

- Chinese quick-start guide for classmates and first-time users, covering download, Python discovery, dependency installation, board IP/user checks, and first connection troubleshooting.
- Windows setup check script for detecting Python, required Python packages, local network addresses, board ping, SSH port reachability, and the suggested toolbox launch command.
- OPP project completeness checker after `msopgen gen`, with profile-based checks for vector elementwise, Reduce, Gather/Scatter, Scan, Copy/Cast/Layout, MatMul/Cube, and generic skeletons.
- Toolbox version marker and a bottom-right update checker that compares the local version with the GitHub release copy.
- Semi-automatic update script for classmates: clone-based installs use `git pull`, while ZIP installs download the latest GitHub archive, back up the old directory, and copy the new files.
- KPP output reader plugin (`kpp_report.py`): reads `Pipe_statistic.csv` / `Instruction_statistic.csv` and prints a one-click verdict — bottleneck pipe, memory-vs-compute bound, read/write bandwidth asymmetry, and double-buffer ROI upper bound.
- Top "project variables" bar (`op_name` / `board_home`): set the operator name and board home directory once, and tool default paths follow them.
- `.gitattributes` to normalize line endings (LF for code/JSON/Markdown, CRLF for PowerShell).

### Changed

- The board connection button now stays usable while SSH connection is in progress. Clicking it cancels the pending connection request instead of forcing the user to close the whole toolbox window.
- The default board home directory can now be selected with the board-side path picker instead of only being typed by hand.
- The toolbox bottom bar now includes an update-command button, so users can copy a safe PowerShell update command after a newer version is detected.
- The `msopgen gen` flow now calls out that generated projects are only skeletons and must be completed before Release/Debug builds.
- Combo boxes can now show friendly Chinese labels while still emitting the underlying command-line values.
- Tool default paths are now generic, operator-name-based examples (`{op_name}_gen` / `{op_name}_st`) instead of the author's own experiment directories, so first-time users see self-explanatory placeholders.
- The parameters and execution-output areas are now a draggable vertical split, so the output pane can be enlarged freely instead of only collapsed/expanded.
- The setup check now verifies a real SSH banner instead of a bare TCP handshake, so a proxy/VPN can no longer make an absent board look reachable.

### Fixed

- The ZIP update path now explicitly preserves `cann_toolbox/config/toolbox_config.json` before copying new files, then restores it after the update.
- The OPP checker no longer reports missing tiling just because the selected `src/` directory only includes a tiling header from a neighboring generated directory.

### 新增

- 新增同学快速开始文档，说明下载、查找 Python、安装依赖、确认板子 IP/用户名，以及第一次连接失败时的排查步骤。
- 新增 Windows 本机环境体检脚本，可检测 Python、必要 Python 包、本机网卡地址、板子 ping、SSH 端口连通性，并给出工具箱启动命令。
- 新增 `msopgen gen` 后的 OPP 工程完整性检查器，可按 Vector 逐元素、Reduce、Gather/Scatter、Scan、Copy/Cast/Layout、MatMul/Cube、通用骨架等范式检查工程是否仍像空壳。
- 新增工具箱版本标记和右下角检查更新入口，可和 GitHub 发布副本对比本地版本。
- 新增半自动更新脚本：Git 克隆版自动 `git pull`，ZIP 解压版自动下载 GitHub 最新压缩包、备份旧目录并覆盖更新。
- 新增 KPP 输出解读插件（`kpp_report.py`）：读取 `Pipe_statistic.csv` / `Instruction_statistic.csv`，一键判出瓶颈在哪条 pipe、是 memory 还是 compute 受限、读写带宽是否对称、双缓冲收益上限。
- 新增顶部“项目变量”栏（`op_name` / `board_home`）：算子名和板端家目录设一次，各工具默认路径自动跟随。
- 新增 `.gitattributes` 统一换行符（代码/JSON/Markdown 用 LF，PowerShell 用 CRLF）。

### 调整

- SSH 正在连接时，连接按钮会变成“取消连接”，可以取消本次连接请求，不再需要整个退出工具箱。
- 默认板端家目录现在可以用板端路径选择器点选，不再只能手动输入。
- 工具箱底部新增“更新命令”按钮，发现新版后可以复制安全的 PowerShell 更新命令。
- `msopgen gen` 流程现在会明确提示：生成的是工程骨架，必须补完 kernel/host/tiling 后再做 Release 或 Debug 构建。
- 下拉框支持显示友好的中文选项，同时生成命令时仍使用底层命令行参数。
- 工具默认路径改为基于算子名的通用示例（`{op_name}_gen` / `{op_name}_st`），不再是作者自己的实验目录，新人一打开看到的是能看懂的占位路径。
- 参数区与执行输出区之间改成可拖动的纵向分隔条，输出窗口可自由拉大，不再只能整块折叠/展开。
- 体检脚本改为校验真实 SSH banner，而不是只看 TCP 握手，代理/VPN 不会再把没插的板子误报成可连。

### 修复

- ZIP 更新路径现在会在覆盖前显式保存 `cann_toolbox/config/toolbox_config.json`，更新后再恢复，避免用户连接配置被新版文件影响。
- 修复 OPP 检查器误报 tiling 缺失的问题：如果用户只选择 `src/` 目录，而 tiling 头文件是通过 host include 放在相邻生成目录中，现在会识别为注意项而不是缺失项。

## [0.1.0] - 2026-06-12

Initial public release.

第一版公开发布。

### Added

- Desktop GUI for running common CANN operator-development workflows from buttons and forms.
- SSH/SFTP board connection support.
- Command builders for `msopgen`, `msopst`, `msprof`, `mskpp`, `msdebug`, and `mssanitizer`.
- JSON builders for `msOpGen` operator description files and `msOpST` case files.
- Plugin manifest format for adding local scripts without editing the GUI code.
- Local report and plotting scripts for selected profiling and simulator outputs.
- Bilingual README files: English and Simplified Chinese.
- Safety defaults: no committed board password, and local runtime config ignored by Git.

### Notes

- This is not an official CANN product. It is a practical companion for developers using the official CANN operator developer toolkit with a real board.
- `msDebug` real-time NPU kernel debugging is marked unsupported for the current Ascend310B4 path based on local experiments.
- `msSanitizer` integration is still exploratory. Command templates are provided, but successful execution does not by itself prove full memory/race checking coverage.

### 新增

- 提供桌面 GUI，把常用 CANN 算子开发流程整理成按钮和表单。
- 支持通过 SSH/SFTP 连接板端。
- 提供 `msopgen`、`msopst`、`msprof`、`mskpp`、`msdebug`、`mssanitizer` 常用命令生成器。
- 提供 `msOpGen` 算子描述 JSON 和 `msOpST` 测试用例 JSON 生成器。
- 提供插件清单格式，不改 GUI 代码也能接入本地脚本。
- 收录部分 profiling / simulator 输出的本地报告和画图脚本。
- 提供英文和简体中文 README。
- 默认不提交板端密码，并忽略本机运行配置。

### 注意

- 这不是官方 CANN 产品，而是给实际使用官方 CANN 算子开发工具链和真实板子的开发者准备的实用配套工具。
- 基于当前本地实验，`msDebug` 实时 NPU kernel 调试在 Ascend310B4 路线上标记为不支持。
- `msSanitizer` 仍在探索中。工具箱提供命令模板，但命令成功执行本身不等于已经完整覆盖内存或竞争问题检测。
