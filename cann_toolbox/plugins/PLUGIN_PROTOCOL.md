# CANN 工具箱插件协议草案

目标：工具箱只负责“发现插件、展示表单、拼命令、执行、收集输出、打开结果”，脚本负责具体分析逻辑。这样脚本可以继续迭代，工具箱不用跟着每次改代码。

## 1. 插件类型

第一阶段先支持四类：

- `report`：结果整理。把 CSV/JSON/sqlite/tar.gz 转成 Excel、图片、Markdown 或文字摘要。
- `runner`：命令包装。把常用官方命令或项目脚本做成按钮。
- `analyzer`：输出分析。读取一个目录或文件，给出诊断结论。
- `builder`：文件生成。**不跑脚本**，在工具箱里靠表单直接拼出一个文件（如算子描述 JSON），保存到本地后用现有“文件管理器 / 发送到板子”传上去。

前三类是“填表单 → 拼命令行 → 跑脚本 → 收输出”；`builder` 是“填表单 → 在 GUI 里拼文件 → 保存”，没有命令、没有子进程、没有退出码，所以它的清单字段和前三类不同（见第 10 节）。

## 2. 推荐脚本接口

新脚本推荐支持统一参数：

```powershell
python script.py --input <输入文件或目录> --output <输出文件或目录>
```

可选参数：

```powershell
--format <xlsx|png|svg|md|txt|json>
--label <显示名称>
--config <配置文件>
--open-output
--overwrite
--quiet
```

约定：

- 输入可以是文件或目录，由插件清单声明 `input.kind`。
- 输出可以是文件或目录，由插件清单声明 `output.kind`。
- 插件脚本路径优先写成 `{workspace}/...` 或 `{toolbox}/...`，不要写死 `D:/算子开发/...` 这类本机绝对路径。
- 成功时 stdout 最后一行建议输出：`OUTPUT=<生成物路径>`。
- 失败时 stderr/stdout 要包含明确错误关键词，例如 `ERROR:`、`FileNotFoundError`、`缺少依赖`。
- 脚本退出码必须可靠：成功 `0`，失败非 `0`。
- 脚本内部字段、图表、Sheet 名可以自由变化；工具箱不依赖这些内部结构。

## 3. 兼容旧脚本

旧脚本不强制改成统一参数。工具箱通过 `command_template` 适配：

```json
"command_template": "\"{python}\" \"{script}\" \"{input}\" \"{output}\""
```

常用占位符：

- `{python}`：Python 解释器路径。
- `{script}`：脚本路径。
- `{input}`：用户选择的输入路径。
- `{output}`：用户选择的输出路径。
- `{workspace}`：项目根目录。
- `{toolbox}`：工具箱目录。
- `{label}`：用户填写的标签。
- `{format}`：输出格式。

## 4. 插件清单格式

工具箱从 JSON 文件读取插件。一个文件可以声明多个插件。

```json
{
  "schema_version": 1,
  "plugins": [
    {
      "id": "msprof.prof_report",
      "name": "msProf CSV 生成 Excel 报告",
      "group": "msProf / 结果整理",
      "type": "report",
      "description": "读取 OpBasicInfo.csv、PipeUtilization.csv 等结果，生成带图表的 Excel。",
      "script": "{workspace}/官方算子开发工具/msProf/tools/prof_report.py",
      "input": {
        "kind": "dir",
        "label": "msProf 输出目录",
        "required_files_any": ["OpBasicInfo.csv", "PipeUtilization.csv"]
      },
      "output": {
        "kind": "file",
        "label": "Excel 输出文件",
        "default": "{input}/prof_report.xlsx",
        "extensions": [".xlsx"]
      },
      "command_template": "\"{python}\" \"{script}\" \"{input}\" \"{output}\"",
      "requirements": ["openpyxl"],
      "after_success": {
        "show_output_path": true,
        "offer_open_file": true,
        "offer_open_folder": true
      }
    }
  ]
}
```

## 5. 字段约定

`input.kind` / `output.kind` 可选：

- `file`
- `dir`
- `none`

`input.required_files_any` 表示目录中至少有一个文件存在即可。

`input.required_files_all` 表示目录中必须全部存在。

`output.default` 可用：

- `{input}`：输入路径。
- `{input_dir}`：输入文件所在目录，或输入目录本身。
- `{input_stem}`：输入文件去扩展名后的名字。
- `{timestamp}`：运行时间戳。

## 6. 依赖约定

插件清单可以写：

```json
"requirements": ["openpyxl", "matplotlib", "numpy"]
```

工具箱第一阶段只做检测和提示，不自动安装。提示格式：

```text
缺少 Python 包：openpyxl
可运行：python -m pip install openpyxl
```

## 7. 输出约定

工具箱执行插件后：

- 把 stdout/stderr 放进输出窗口。
- 用现有“问题摘要”提取报错。
- 如果 stdout 中出现 `OUTPUT=<path>`，优先把它作为生成物。
- 如果没有 `OUTPUT=<path>`，使用清单里的 `output` 路径。

## 8. 最小迁移规则

给已有脚本接入工具箱时，优先不改脚本。只写清单：

1. 确认脚本当前命令行参数。
2. 写 `command_template`。
3. 写输入/输出类型和默认路径。
4. 写依赖。
5. 用工具箱跑一次，确认输出和摘要。

只有当脚本参数太混乱、无法稳定包装时，再改脚本支持 `--input/--output`。

## 10. `builder` 类型（文件生成器）

`builder` 不跑脚本，由工具箱根据表单内容在本地拼出一个文件。第一版只生成 JSON（`emit: "json"`）。

清单结构和前三类不同：没有 `script` / `command_template` / `input` / `output`，改用 `basic_fields` + `repeat_sections`。

```json
{
  "id": "msopgen.opdesc_json",
  "type": "builder",
  "name": "算子描述 JSON 生成器",
  "group": "msOpGen / 描述文件",
  "emit": "json",
  "description": "按算子名、输入/输出张量、属性生成 msopgen 可用的算子描述 JSON。",
  "basic_fields": [
    {"key": "op", "label": "算子名", "type": "text", "default": ""},
    {"key": "mode", "label": "模式", "type": "choice",
     "options": ["IR", "MindSpore"], "default": "IR", "control_only": true,
     "rerender_on_change": true}
  ],
  "repeat_sections": [
    {
      "key": "input_desc", "label": "输入张量",
      "fields": [
        {"key": "name", "type": "text", "label": "名字"},
        {"key": "param_type", "type": "choice", "label": "参数类型",
         "options": ["required", "optional", "dynamic"], "default": "required"},
        {"key": "format", "type": "choice", "label": "format",
         "options": ["NCHW", "NHWC", "ND", "NC1HWC0"], "default": "ND",
         "emit": "list", "omit_when": {"basic": "mode", "equals": "MindSpore"}},
        {"key": "type", "type": "choice", "label": "dtype",
         "options": ["fp16", "fp32", "int8", "int32", "uint8", "bool"],
         "default": "fp16", "emit": "list"}
      ]
    }
  ]
}
```

### 字段说明

`basic_fields`：顶层标量字段，渲染成普通输入行。

- `type`：`text`（自由输入框）或 `choice`（只读下拉，锁死合法值）。
- `control_only: true`：该字段只控制界面/输出，不写进生成的 JSON（如 `mode`）。
- `rerender_on_change: true`：值变化时整张表单重绘（让 `omit_when` / `options_by` 生效，比如切到 MindSpore 模式隐藏 format、切换 dtype 选项）。
- `option_hints: {<选项值>: <说明>}`：`choice` 字段专用。选中某个值后，下拉框下方显示对应的灰色注释（如选 IR 显示“通用/TF/ONNX”）。

`repeat_sections`：可“➕加一行 / ✕删一行”的子表单组，每组对应 JSON 里的一个数组（`input_desc` / `output_desc` / `attr`）。

- 每个 `field` 同样支持 `text` / `choice`。
- `emit: "list"`：该字段的值在 JSON 里写成数组（如 `"type": ["fp16"]`）。可逗号分隔填多个。默认按标量写。
- `omit_when: {"basic": <key>, "equals": <值>}`：当某个 basic 字段等于指定值时，这一项不渲染、也不写进 JSON。
- `options_by: {"basic": <key>, "map": {<basic值>: [选项...]}}`：`choice` 字段的选项随某个 basic 字段变化（如 dtype 在 IR 模式给 `fp16/fp32`，在 MindSpore 模式给 `I8_NCHW/F16_NCHW`）。切换后若当前值不在新选项里，自动回退到第一个选项。需要触发它的 basic 字段带 `rerender_on_change: true`。
- `legend: <说明>`：组级注释，显示在组标题下方一行灰字，解释这一组各列/各值的含义。静态常显，专治“忘了这是啥”。

### 合法值（来自官方源码 const_manager.py，锁在清单里）

- 输入/输出 `param_type`：`required` / `optional` / `dynamic`
- 属性 `param_type`：`required` / `optional`（不能用 `dynamic`）
- IR 模式 JSON 带 `format` 字段；MindSpore 模式不带 `format`，`type` 用 `I8_NCHW` 这类合并写法
- 最外层是数组，可含多个算子对象（第一版只生成单个算子）

### 校验（第三层，预留未实现）

下拉框已经锁死了大部分合法值（第二层）。再往上的“生成后主动校验”留作增强：清单里可预留 `validate` 字段声明跨字段规则（如 IR 模式必须有 format、attr 不能 dynamic、自由填的算子名不能为空），工具箱第一版**不实现**，等踩到“下拉锁不住、传上去才报错”的坑再补。

### 出口

生成的文件不自动执行。表单下方提供「💾 保存到本地…」和「📋 复制」；存好后接现有“文件管理器 / 发送到板子”传到板端。

## 9. 未来增强

- 插件清单热加载：放进 `cann_toolbox/plugins/*.json` 即自动出现按钮。
- 插件运行历史：记住最近输入/输出路径。
- 插件结果列表：生成后可直接打开文件或文件夹。
- 插件链路：例如“下载板端结果 -> 生成 Excel -> 画图”。
