# 同学快速开始

这份说明给第一次从 GitHub 下载 CANN Operator Toolbox 的同学。目标是先把工具箱打开、连上板子，再开始跑具体算子流程。

## 1. 下载工具箱

打开仓库页面：

```text
https://github.com/Rytting/cann-operator-toolbox
```

如果不熟悉 Git，可以直接点：

```text
Code -> Download ZIP
```

下载后解压到一个路径简单的位置，例如：

```text
D:\cann-operator-toolbox
```

路径里可以有中文，但如果遇到奇怪的脚本路径问题，优先换到纯英文路径再试。

## 2. 找到自己的 Python

最省事的方法是先运行本仓库自带的体检脚本。它会自动查找 Python、检查依赖、列出本机网卡 IP，并测试默认板子地址是否能 ping 通：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check_local_setup.ps1
```

如果你的板子不是 `192.168.0.2`，可以指定：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check_local_setup.ps1 -BoardIP 你的板子IP
```

如果脚本提示找不到 Python，但你知道自己的 `python.exe` 在哪里，也可以指定：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check_local_setup.ps1 -PythonPath "C:\Path\To\python.exe"
```

工具箱需要 Windows 上的 Python 3.10 或更高版本。

先打开 PowerShell，试一下：

```powershell
python --version
```

如果能看到类似 `Python 3.14.0`，说明可以直接用 `python`。

如果提示找不到 `python`，可以在这些位置找：

```text
C:\Users\<你的用户名>\AppData\Local\Programs\Python\
C:\Program Files\Python*
```

也可以在开始菜单里搜索 Python，右键打开文件位置，再找到真正的 `python.exe`。

找到以后，启动命令里把 `python` 换成完整路径，例如：

```powershell
"C:\Users\lv\AppData\Local\Programs\Python\Python314\python.exe" .\cann_toolbox\run_toolbox.py
```

## 3. 安装依赖

在工具箱仓库根目录打开 PowerShell，运行：

```powershell
python -m pip install paramiko openpyxl matplotlib numpy
```

如果你的电脑不能直接用 `python`，就把前面的 `python` 换成自己的完整 `python.exe` 路径。

这些包的用途：

- `paramiko`：连接板子、传文件。
- `openpyxl`：生成 Excel 报告。
- `matplotlib`、`numpy`：画 profiling / Roofline 等分析图。

## 4. 启动工具箱

进入仓库根目录：

```powershell
cd D:\cann-operator-toolbox
```

启动：

```powershell
python .\cann_toolbox\run_toolbox.py
```

如果 Python 不在 PATH 里：

```powershell
"C:\Path\To\python.exe" .\cann_toolbox\run_toolbox.py
```

## 5. 填板子连接信息

工具箱顶部需要填：

- IP：板子的 SSH 地址。
- 端口：一般是 `22`。
- 用户：Atlas 200I DK A2 常见是 `HwHiAiUser`。
- 密码：填你自己板子的密码。

我们这套实验常用值是：

```text
IP: 192.168.0.2
Port: 22
User: HwHiAiUser
CANN path: /usr/local/Ascend/cann-8.5.0
```

但这只是示例，不保证每块板子都一样。

## 6. 不知道板子 IP 怎么办

如果是 USB RNDIS 直连 Atlas 开发板，常见情况是：

- 板子侧 IP：`192.168.0.2`
- Windows 电脑侧 USB 网卡：`192.168.0.1`
- 子网掩码：`255.255.255.0`
- 网关：留空

Windows 侧可以这样看网卡信息：

```powershell
ipconfig
```

重点找类似 `USB RNDIS`、`Remote NDIS`、`Ethernet adapter` 的网卡。

如果电脑侧地址变成了 `169.254.x.x`，通常说明没有手动配好 USB 网卡 IP，需要把对应网卡改成：

```text
192.168.0.1
255.255.255.0
无网关
```

如果板子接在局域网或路由器上，IP 可能完全不同，需要看路由器后台、串口日志，或问负责板子的人。

## 7. 不知道用户名怎么办

Atlas 200I DK A2 常见普通用户是：

```text
HwHiAiUser
```

如果这个用户登不上，先确认：

- 板子是不是被重装过系统。
- SSH 是否打开。
- 是否应该用项目组统一分配的用户。

能用串口登录时，可以在板子上运行：

```bash
whoami
ip addr
systemctl status ssh
```

## 8. 连不上时先查这几件事

也可以直接运行体检脚本，让它帮你做 ping、22 端口和网卡 IP 检查：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check_local_setup.ps1 -BoardIP 192.168.0.2 -BoardUser HwHiAiUser
```

先在 Windows PowerShell 里试：

```powershell
ping 192.168.0.2
```

能 ping 通，再试：

```powershell
ssh HwHiAiUser@192.168.0.2
```

如果 `ping` 不通：

- 检查 USB 网线 / 网口线。
- 检查 Windows USB 网卡 IP。
- 检查板子是否启动完成。
- 检查是不是换了板子 IP。

如果 `ping` 通但 SSH 不通：

- 检查用户名和密码。
- 检查板端 SSH 服务是否启动。
- 检查端口是否还是 `22`。

## 9. 第一次打开工具箱后建议做什么

按这个顺序点：

1. 顶部填 IP、端口、用户名、密码。
2. 点连接。
3. 打开文件管理器，看能不能列出 `/home/HwHiAiUser`。
4. 运行“检查 CANN 工具路径”，确认板端 CANN 路径存在。
5. 再开始使用 `msKPP`、`msOpGen`、`msOpST`、`msProf` 等工具页面。

## 10. 重要提醒

- 不要把自己的 `cann_toolbox/config/toolbox_config.json` 提交到 GitHub，它可能保存本机配置或密码。
- 生成命令后，先看一眼再发到板子。
- 工具箱里有些功能是我们实测稳定路线，有些是探索入口。界面说明里如果写着“探索中”，就不要把它当成最终结论。
