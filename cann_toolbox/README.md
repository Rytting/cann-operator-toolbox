# CANN 工具箱

这个目录用于放 CANN 工具箱程序本体和后续插件。当前入口：

```powershell
python .\cann_toolbox\run_toolbox.py
```

第一次给同学使用时，先看：

- `docs/同学使用说明.md`：启动、连接板子、跑一个新算子的推荐顺序。

迁移到其他电脑时，建议把整个项目目录一起拷贝，保持 `cann_toolbox/` 和 `官方算子开发工具/` 的相对位置。工具箱会自动按自身所在位置推项目根目录，插件脚本路径不要写死成本机盘符。

## 目录结构

- `run_toolbox.py`：稳定启动入口。
- `src/`：GUI 主程序和核心逻辑。
- `config/`：后续放板端连接配置、默认路径、用户偏好。
- `plugins/`：后续放 KPP、msProf、msOpGen 等可插拔功能模块。
- `scripts/`：工具箱调用的小脚本，例如更新脚本、profiling 摘要、KPP 结果解析。
- `docs/`：工具箱自身设计说明、使用说明和交接记录。

## 当前状态

主程序从仓库根目录迁移到 `src/cann_toolbox_app.py`。后续建议逐步把大文件拆分为：

- `src/app.py`：主窗口和布局。
- `src/tools.py`：工具定义。
- `src/ssh_client.py`：板端 SSH/SFTP。
- `src/config.py`：连接配置读写。
- `plugins/kpp/`：KPP DSL 生成、结果摘要、理论/实测对比。
- `plugins/prof/`：msProf 采集、导出和本地分析。
