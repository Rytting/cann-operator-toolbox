# plugins

后续把较大的功能拆到这里：

- `kpp/`：生成 msKPP DSL、运行建模、解析 `Instruction_statistic.csv` / `Pipe_statistic.csv`。
- `prof/`：msProf 采集、导出、Roofline/瓶颈分析。
- `opgen/`：msOpGen 工程生成与构建辅助。
- `opst/`：msOpST 测试用例生成和运行。

插件接入先看：

- `PLUGIN_PROTOCOL.md`：脚本和工具箱之间的约定。
- `report_tools.example.json`：结果整理类脚本的配置示例。
