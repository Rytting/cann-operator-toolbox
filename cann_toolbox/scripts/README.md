# scripts

工具箱调用的小脚本放这里。原则：

- 能独立运行。
- 输入输出参数明确。
- 不依赖 GUI 状态。
- 适合被按钮命令调用。

## update_toolbox.ps1

半自动更新脚本。工具箱右下角“更新命令”按钮会复制运行它的命令。

使用方式：

```powershell
powershell -ExecutionPolicy Bypass -File .\cann_toolbox\scripts\update_toolbox.ps1
```

注意：

- 先关闭正在运行的 CANN 工具箱窗口，再执行更新命令。
- 如果当前目录是 Git 克隆版，脚本会执行 `git pull --ff-only origin main`。
- 如果当前目录是下载 ZIP 后解压的版本，脚本会下载 GitHub `main.zip`，备份旧目录，再覆盖更新。
- 脚本会检查 `README.md`、`LICENSE`、`cann_toolbox/run_toolbox.py`、`cann_toolbox/VERSION`，避免误把普通项目目录当成工具箱安装目录。
