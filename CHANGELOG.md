# Changelog

English | 简体中文

All notable changes to this project will be recorded here.

本文件用于记录 CANN Operator Toolbox 的重要更新：新增功能、行为变化、修复内容和已知注意事项。

The format loosely follows Keep a Changelog, and this project uses simple version numbers such as `0.1.0` while it is still young.

## [Unreleased]

Changes that have been made locally but are not part of a tagged release yet.

尚未发布成版本的本地改动会先放在这里。

### Added

- Chinese quick-start guide for classmates and first-time users, covering download, Python discovery, dependency installation, board IP/user checks, and first connection troubleshooting.

### 新增

- 新增同学快速开始文档，说明下载、查找 Python、安装依赖、确认板子 IP/用户名，以及第一次连接失败时的排查步骤。

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
