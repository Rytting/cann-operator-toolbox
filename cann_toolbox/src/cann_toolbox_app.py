#!/usr/bin/env python3
"""CANN 工具箱 - 命令构建器 + SSH 板端直连 + SFTP 文件管理器"""
import json
import re
import stat as _stat
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, scrolledtext, ttk
import subprocess
from pathlib import Path
from datetime import datetime

try:
    import paramiko
    HAS_PARAMIKO = True
except ImportError:
    HAS_PARAMIKO = False

# ── 路径 / 默认配置 ───────────────────────────────────────────────────────────
APP_DIR = Path(__file__).resolve().parents[1]
CONFIG_DIR = APP_DIR / "config"
PLUGIN_DIR = APP_DIR / "plugins"
DEFAULT_CONFIG_PATH = CONFIG_DIR / "default_config.json"
USER_CONFIG_PATH = CONFIG_DIR / "toolbox_config.json"
DEFAULT_CONFIG = {
    "board": {
        "host": "192.168.0.2",
        "port": 22,
        "user": "HwHiAiUser",
        "password": "",
        "remember_password": False,
        "default_remote_dir": "/home/HwHiAiUser/work",
    },
    "cann": {
        "path": "/usr/local/Ascend/cann-8.5.0",
    },
    "paths": {
        "work_dir": "/home/HwHiAiUser/work",
        "custom_opp_opgen": "/home/HwHiAiUser/custom_opp_opgen_v1",
        "custom_opp_dim8_g": "/home/HwHiAiUser/custom_opp_dim8_g",
        "custom_opp_addcustom_cann85": "/home/HwHiAiUser/custom_opp_ascendc_addcustom_cann85",
        "kpp_out": "/home/HwHiAiUser/kpp_out",
    },
}
CANN_ENV = "source /usr/local/Ascend/cann-8.5.0/set_env.sh"
LOCAL_PYTHON = sys.executable
LOCAL_ROOT = str(APP_DIR.parent).replace("\\", "/")

FONT_UI = ("Microsoft YaHei UI", 11)
FONT_UI_BOLD = ("Microsoft YaHei UI", 11, "bold")
FONT_TITLE = ("Microsoft YaHei UI", 15, "bold")
FONT_MONO = ("Consolas", 12)
FONT_MONO_SMALL = ("Consolas", 11)
FORM_LABEL_WIDTH = 16
FORM_LABEL_WRAP = 150


def _deep_merge(base, override):
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_toolbox_config():
    config = DEFAULT_CONFIG
    for path in (DEFAULT_CONFIG_PATH, USER_CONFIG_PATH):
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8") as f:
                config = _deep_merge(config, json.load(f))
        except Exception:
            pass
    return config


def save_toolbox_config(config):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    safe_config = {
        "board": {
            "host": config["board"].get("host", ""),
            "port": int(config["board"].get("port", 22) or 22),
            "user": config["board"].get("user", ""),
            "password": config["board"].get("password", ""),
            "remember_password": bool(config["board"].get("remember_password", True)),
            "default_remote_dir": config["board"].get("default_remote_dir", ""),
        },
        "cann": {
            "path": config["cann"].get("path", "/usr/local/Ascend/cann-8.5.0"),
        },
        "paths": config.get("paths", DEFAULT_CONFIG["paths"]),
    }
    with USER_CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(safe_config, f, ensure_ascii=False, indent=2)


def config_cann_path(config):
    return config.get("cann", {}).get("path", "/usr/local/Ascend/cann-8.5.0").rstrip("/")


def config_cann_env(config):
    return f"source {config_cann_path(config)}/set_env.sh"


def _plugin_default_input(plugin):
    input_meta = plugin.get("input", {})
    kind = input_meta.get("kind", "file")
    if kind == "dir":
        return LOCAL_ROOT
    return ""


def _plugin_default_output(plugin):
    output_meta = plugin.get("output", {})
    return output_meta.get("default", "")


def _plugin_field_kind(kind):
    return kind if kind in ("file", "dir") else "text"


def _plugin_manifest_values():
    return {
        "workspace": LOCAL_ROOT,
        "toolbox": str(APP_DIR).replace("\\", "/"),
    }


def _format_plugin_manifest_value(value):
    if not isinstance(value, str) or "{" not in value:
        return value
    try:
        return value.format(**_plugin_manifest_values())
    except KeyError:
        return value


def _remote_mtime_text(entry):
    try:
        return datetime.fromtimestamp(entry.st_mtime).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "---- -- -- --:--"


def _remote_size_text(entry):
    if _stat.S_ISDIR(entry.st_mode):
        return "<DIR>"
    size = int(getattr(entry, "st_size", 0) or 0)
    units = ["B", "KB", "MB", "GB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024


def _remote_list_label(icon, name, entry):
    return f"{icon}  {_remote_mtime_text(entry)}  {_remote_size_text(entry):>8}  {name}"


def _form_label(parent, text, *, required=False, empty=False):
    if empty:
        text = ""
    label = ttk.Label(
        parent,
        text=text,
        anchor="e",
        justify="right",
        width=FORM_LABEL_WIDTH,
        wraplength=FORM_LABEL_WRAP,
        foreground="#b00020" if required else "black",
    )
    return label


def _combo_display_options(field):
    labels = field.get("option_labels", {})
    return [labels.get(value, value) for value in field.get("options", [])]


def _combo_display_value(field, value):
    if field.get("type") != "combo":
        return value
    return field.get("option_labels", {}).get(value, value)


def _combo_emit_value(field, value):
    if field.get("type") != "combo":
        return value
    labels = field.get("option_labels", {})
    if value in field.get("options", []):
        return value
    reverse = {label: raw for raw, label in labels.items()}
    return reverse.get(value, value)


def _plugin_to_builder_tool(plugin, manifest_path):
    return {
        "name": _plugin_display_name(plugin),
        "target": "builder",
        "desc": plugin.get("description", "文件生成器。"),
        "builder": {
            "emit": plugin.get("emit", "json"),
            "basic_fields": plugin.get("basic_fields", []),
            "repeat_sections": plugin.get("repeat_sections", []),
        },
        "plugin_id": plugin.get("id", ""),
    }


def _plugin_to_tool(plugin, manifest_path):
    if plugin.get("type") == "builder":
        return _plugin_to_builder_tool(plugin, manifest_path)
    input_meta = plugin.get("input", {})
    output_meta = plugin.get("output", {})
    requirements = plugin.get("requirements", [])
    note_parts = [
        "这是插件清单动态生成的按钮；脚本逻辑仍在脚本文件里，工具箱只负责选择路径、拼命令和收集输出。"
    ]
    if requirements:
        note_parts.append("依赖：" + "、".join(requirements) + "。缺依赖时先按问题摘要提示安装。")
    note_parts.append(f"清单：{manifest_path.name}")
    fields = [
        {"type": "note", "text": "\n".join(note_parts)},
        {"key": "python", "label": "Python 解释器", "type": "file", "default": LOCAL_PYTHON},
        {"key": "script", "label": "脚本文件", "type": "file",
         "default": _format_plugin_manifest_value(plugin.get("script", ""))},
    ]
    if input_meta.get("kind", "file") != "none":
        fields.append({
            "key": "input",
            "label": input_meta.get("label", "输入路径"),
            "type": _plugin_field_kind(input_meta.get("kind", "file")),
            "default": input_meta.get("default", _plugin_default_input(plugin)),
        })
    if output_meta.get("kind", "file") != "none":
        fields.append({
            "key": "output",
            "label": output_meta.get("label", "输出路径"),
            "type": _plugin_field_kind(output_meta.get("kind", "file")),
            "default": _plugin_default_output(plugin),
        })
    fields.extend([
        {"key": "label", "label": "标签/备注", "type": "text", "default": plugin.get("label", "")},
        {"key": "format", "label": "输出格式", "type": "text",
         "default": (output_meta.get("extensions", [""])[0].lstrip(".") if output_meta.get("extensions") else "")},
    ])
    return {
        "name": _plugin_display_name(plugin),
        "target": "local",
        "desc": plugin.get("description", "插件工具。"),
        "template": plugin.get("command_template", '"{python}" "{script}" --input "{input}" --output "{output}"'),
        "fields": fields,
        "plugin_id": plugin.get("id", ""),
    }


def _plugin_display_name(plugin):
    name = plugin.get("name", plugin.get("id", "未命名插件"))
    if name.startswith("【插件】"):
        return name
    return f"【插件】{name}"


def _plugin_group_hint(plugin):
    plugin_id = plugin.get("id", "")
    group = plugin.get("group", "")
    if plugin_id == "msopgen.trace_report":
        return "msProf"
    if group.startswith("msOpGen"):
        return "msOpGen"
    if group.startswith("msProf"):
        return "msProf"
    if group.startswith("msOpST"):
        return "msOpST"
    if group.startswith("msKPP"):
        return "msKPP"
    return group or "插件 / 未分类"


def load_plugin_tool_groups():
    groups = {}
    if not PLUGIN_DIR.exists():
        return []
    for manifest_path in sorted(PLUGIN_DIR.glob("*.json")):
        if manifest_path.name.endswith(".example.json"):
            continue
        try:
            with manifest_path.open("r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception:
            continue
        for plugin in manifest.get("plugins", []):
            group = _plugin_group_hint(plugin)
            groups.setdefault(group, []).append(_plugin_to_tool(plugin, manifest_path))
    return [{"group": group, "items": items} for group, items in groups.items()]


GROUP_ORDER_KEYWORDS = [
    "板端环境",
    "msKPP",
    "msOpGen",
    "msOpST",
    "msProf",
    "本地分析",
    "待探索",
]

PLUGIN_INSERT_RULES = {
    "msopgen.opdesc_json": ("msOpGen", "before", "生成算子工程（gen）"),
    "msopst.case_json": ("msOpST", "after", "生成测试用例骨架（create）"),
    "msprof.prof_report": ("msProf", "after", "导出传统 db 采集结果"),
    "msprof.roofline_plot": ("msProf", "after", "【插件】msProf CSV 转 Excel"),
    "msopgen.trace_report": ("msProf", "after", "msOpGen sim 转时间线"),
}


def _group_order_key(group):
    name = group.get("group", "")
    for index, keyword in enumerate(GROUP_ORDER_KEYWORDS):
        if keyword in name:
            return index
    return len(GROUP_ORDER_KEYWORDS)


def _renumber_group_name(name, index):
    return re.sub(r"^\d+\.\s*", f"{index}. ", name)


def _sort_and_renumber_tool_groups(groups):
    ordered = sorted(groups, key=_group_order_key)
    for index, group in enumerate(ordered, start=1):
        group["group"] = _renumber_group_name(group["group"], index)
    return ordered


def _find_group_by_hint(groups, hint):
    for group in groups:
        if hint in group.get("group", ""):
            return group
    return None


def _find_item_index(items, name_fragment):
    for index, item in enumerate(items):
        if name_fragment in item.get("name", ""):
            return index
    return None


def _insert_tool_item(items, item):
    rule = PLUGIN_INSERT_RULES.get(item.get("plugin_id", ""))
    if not rule:
        items.append(item)
        return
    _, mode, anchor = rule
    anchor_index = _find_item_index(items, anchor)
    if anchor_index is None:
        items.append(item)
    elif mode == "before":
        items.insert(anchor_index, item)
    else:
        items.insert(anchor_index + 1, item)


def _merge_tool_groups(base_groups, plugin_groups):
    for plugin_group in plugin_groups:
        target = _find_group_by_hint(base_groups, plugin_group["group"])
        if target is None:
            base_groups.append(plugin_group)
            continue
        for item in plugin_group.get("items", []):
            _insert_tool_item(target["items"], item)
    return base_groups


# ── 工具定义 ──────────────────────────────────────────────────────────────────
# target: "board" = 在板子上执行  |  "local" = 在本机 PowerShell 执行
TOOLS = [
    {
        "group": "1. 板端环境 / 文件",
        "items": [
            {
                "name": "检查 CANN 工具路径",
                "target": "board",
                "desc": "确认板端 CANN 8.5 环境和 msopgen/msopst/msprof/msdebug/mssanitizer 等入口是否可用。",
                "template": (
                    "{cann_env} && "
                    "echo CANN=$ASCEND_HOME_PATH && "
                    "for t in msopgen msopst msprof msdebug mssanitizer opc msobjdump; do "
                    "printf '%-14s' $t; command -v $t || true; done && "
                    "echo mskpp_dir={cann_path}/tools/msopt/mskpp"
                ),
                "fields": [],
            },
            {
                "name": "盘点 work 目录",
                "target": "board",
                "desc": "只读查看 /home/HwHiAiUser/work 下目录数量、最大目录和最近修改项，清理前先看它。",
                "template": (
                    "cd {path} && "
                    "echo TOTAL=$(find . -maxdepth 1 -mindepth 1 | wc -l) && "
                    "echo DIRS=$(find . -maxdepth 1 -mindepth 1 -type d | wc -l) && "
                    "echo FILES=$(find . -maxdepth 1 -mindepth 1 -type f | wc -l) && "
                    "echo '--- TOP SIZE ---' && du -sh ./* 2>/dev/null | sort -h | tail -20 && "
                    "echo '--- RECENT ---' && find . -maxdepth 1 -mindepth 1 -printf '%TY-%Tm-%Td %TH:%TM %y %f\\n' | sort | tail -30"
                ),
                "fields": [
                    {"key": "path", "label": "板端目录", "type": "text",
                     "default": "{work_dir}"},
                ],
            },
            {
                "name": "查看 CANN / 仿真进程",
                "target": "board",
                "desc": "查看板端是否还有 msprof、msopprof、msopgen sim、runner main 等相关进程在跑。",
                "template": (
                    "echo '--- CANN / simulator processes ---' && "
                    "ps -eo pid,ppid,stat,etime,cmd | "
                    "grep -E 'msprof|msopprof|msopgen sim|simulator|RgbToGrayCustom|AddCustom|ReduceSumCustom|/main' | "
                    "grep -v grep || echo '未发现匹配进程'"
                ),
                "fields": [
                    {"type": "note",
                     "text": "这是只读检查。停止按钮会给当前 SSH 会话发 Ctrl+C；如果这里还能看到残留进程，再决定是否需要单独清理。"},
                ],
            },
            {
                "name": "盘点仿真输出目录",
                "target": "board",
                "desc": "查看 sim_out_toolbox 里最近的 OPPROF 目录、大小，以及 tmp_dump 里是否有非空 dump 文件。",
                "template": (
                    "BASE={sim_dir}; "
                    "echo BASE=$BASE; "
                    "if [ ! -d \"$BASE\" ]; then echo '目录不存在'; exit 0; fi; "
                    "echo '--- RECENT OPPROF ---'; "
                    "find \"$BASE\" -maxdepth 1 -mindepth 1 -type d -name 'OPPROF*' "
                    "-printf '%T@ %TY-%Tm-%Td %TH:%TM %p\\n' | sort -nr | head -10; "
                    "echo '--- SIZE ---'; "
                    "du -sh \"$BASE\"/OPPROF* 2>/dev/null | sort -h | tail -10; "
                    "echo '--- NONEMPTY TMP_DUMP FILES ---'; "
                    "find \"$BASE\" -path '*tmp_dump*' -type f "
                    "\\( -name '*instr_popped_log.dump' -o -name '*instr_log.dump' -o -name 'aicore_binary.o' \\) "
                    "-printf '%s bytes %p\\n' | sort -nr | head -30"
                ),
                "fields": [
                    {"type": "note",
                     "text": "如果能看到非 0 字节的 core0.veccore0.instr_popped_log.dump，就可以去“msOpGen sim 转时间线”选对应 OPPROF 的 device0/tmp_dump。"},
                    {"key": "sim_dir", "label": "仿真输出根目录", "type": "text",
                     "default": "/home/HwHiAiUser/sim_out_toolbox", "remote": True},
                ],
            },
        ],
    },
    {
        "group": "2. msOpGen — 工程生成 / 构建",
        "items": [
            {
                "name": "生成算子工程（gen）",
                "target": "board",
                "desc": "按我们跑通的 CANN 8.5 路线生成 Ascend C OPP 工程骨架。注意：gen 之后还要补算子实现代码，不能直接当成已完成工程。",
                "template": (
                    "cd {workdir} && "
                    "{cann_env} && "
                    "chmod 600 {json} && "
                    "msopgen gen -i {json}{options} -out {output}"
                ),
                "fields": [
                    {"type": "note",
                     "text": "⚠️ 重要断点：msopgen gen 只生成“工程骨架”，不是完整可用的算子。生成后请先进入输出目录，补 op_kernel 里的 kernel 计算逻辑、op_host/tiling 里的切分和参数推导，再去构建 OPP 包。AddCustom 示例里通常要确认 x/y/z 输入输出、TilingData、SetBlockDim、CopyIn/Compute/CopyOut 这些位置。"},
                    {"type": "note",
                     "text": "常用成功路线：JSON 放在板端工作目录，生成 Ascend C/C++ 工程时必须带 -lan cpp；-c 这里用 ai_core-ascend310b，和 msOpST run 的 -soc Ascend310B1 不是同一种写法。"},
                    {"key": "workdir", "label": "板端工作目录", "type": "text",
                     "default": "{work_dir}"},
                    {"key": "json", "label": "算子描述 JSON", "type": "text",
                     "default": "add_custom.json"},
                    {"key": "output", "label": "输出目录", "type": "text",
                     "default": "./opgen_out"},
                    {"key": "use_framework", "label": "我要明确告诉 msOpGen 这个 JSON 按哪个框架解析", "type": "check",
                     "default": True},
                    {"key": "framework", "label": "框架类型", "type": "combo",
                     "default": "tf",
                     "options": ["tf", "tensorflow", "aclnn", "onnx", "pytorch", "ms", "mindspore", "caffe"],
                     "enabled_by": "use_framework", "option": "-f {framework}"},
                    {"key": "compute_unit", "label": "板子芯片对应的计算单元", "type": "combo",
                     "default": "ai_core-ascend310b",
                     "options": ["ai_core-ascend310b", "ai_core-ascend310", "ai_core-ascend910b", "aicpu"],
                     "required": True, "option": "-c {compute_unit}"},
                    {"key": "language", "label": "Ascend C 工程语言", "type": "combo",
                     "default": "cpp", "options": ["cpp", "py"],
                     "required": True, "option": "-lan {language}"},
                    {"key": "append_mode", "label": "我要把算子追加到已有工程（否则默认新建工程）", "type": "check",
                     "default": False, "option": "-m 1"},
                    {"key": "pick_op", "label": "JSON 里有多个算子，我只生成某一个", "type": "check",
                     "default": False},
                    {"key": "op_type", "label": "算子类型名", "type": "text",
                     "default": "AddCustom", "enabled_by": "pick_op", "option": "-op {op_type}"},
                ],
            },
            {
                "name": "检查 OPP 工程完整性（gen 后）",
                "target": "local",
                "desc": "读取 msopgen gen 生成的 OPP 工程目录，检查 kernel、host、tiling 是否仍像空壳。适合在 build 前做一次本地体检。",
                "template": "\"{python}\" \"{toolbox}/scripts/opp_project_check.py\" \"{project}\" --op-profile {op_profile}{options}",
                "fields": [
                    {"type": "note",
                     "text": "这是只读检查，不会修改工程文件。第一版检查本机目录；如果工程在板端，请先用文件管理器下载到本机，或把工程同步到本地后再运行。请按算子的编程范式选择检查模板；检查通过不代表算子数学结果一定正确，只说明关键阶段不像空壳。"},
                    {"key": "python", "label": "Python 解释器", "type": "file",
                     "default": LOCAL_PYTHON},
                    {"key": "project", "label": "OPP 工程目录（本机）", "type": "dir",
                     "default": f"{LOCAL_ROOT}/官方算子开发工具/msOpGen/RgbToGrayCustom/src"},
                    {"key": "op_profile", "label": "算子编程范式", "type": "combo",
                     "default": "elementwise_binary",
                     "options": [
                         "elementwise_binary",
                         "elementwise_vector",
                         "reduce",
                         "gather_scatter",
                         "scan",
                         "copy_cast_layout",
                         "matmul_cube_basic",
                         "generic",
                     ],
                     "option_labels": {
                         "elementwise_binary": "Vector 二元逐元素（Add/Sub/Mul 类）",
                         "elementwise_vector": "Vector 逐元素/图像简单变换（RgbToGray 类）",
                         "reduce": "Reduce 聚合类（Sum/Max/Mean）",
                         "gather_scatter": "Gather/Scatter 索引寻址类",
                         "scan": "Scan 前缀计算类",
                         "copy_cast_layout": "Copy/Cast/Layout 转换类",
                         "matmul_cube_basic": "MatMul/Cube 基础检查",
                         "generic": "通用基础检查（不确定时选这个）",
                     }},
                    {"key": "strict_tiling", "label": "我想严格检查 tiling 字段是否足够描述 block/tile 切分",
                     "type": "check", "default": True, "option": " --strict-tiling"},
                ],
            },
            {
                "name": "构建 OPP 工程 — Release（安装/验证）",
                "target": "board",
                "desc": "切到 Release 编译，生成用于安装、自测、普通 msOpST 验证的 custom_opp_ubuntu_aarch64.run。",
                "template": (
                    "cd {project} && "
                    "{cann_env} && "
                    "python3 -c 'import json,pathlib; p=pathlib.Path(\"CMakePresets.json\"); d=json.loads(p.read_text()); "
                    "[preset.setdefault(\"cacheVariables\", {{}}).__setitem__(\"CMAKE_BUILD_TYPE\", \"Release\") for preset in d.get(\"configurePresets\", [])]; "
                    "p.write_text(json.dumps(d, indent=4, ensure_ascii=False)+\"\\n\")' && "
                    "echo CMAKE_BUILD_TYPE=Release && "
                    "bash build.sh"
                ),
                "fields": [
                    {"type": "note",
                     "text": "Release 是默认的交付/验证模式：包更小、运行更贴近日常验证，但 kernel .o 通常没有调试信息，不能拿来做 msOpGen sim 的源码行映射。注意：如果工程只是刚用 msopgen gen 生成的骨架，还没有补 kernel/tiling/host 实现，请先写代码再构建。"},
                    {"key": "project", "label": "OPP 工程目录", "type": "text",
                     "default": "/home/HwHiAiUser/work/rgb_to_gray_gen"},
                ],
            },
            {
                "name": "构建 OPP 工程 — Debug（仿真/源码映射）",
                "target": "board",
                "desc": "切到 Debug 编译，生成带调试信息的 kernel .o，供 msOpGen sim -reloc、msDebug 或热点分析使用。",
                "template": (
                    "cd {project} && "
                    "{cann_env} && "
                    "python3 -c 'import json,pathlib; p=pathlib.Path(\"CMakePresets.json\"); d=json.loads(p.read_text()); "
                    "[preset.setdefault(\"cacheVariables\", {{}}).__setitem__(\"CMAKE_BUILD_TYPE\", \"Debug\") for preset in d.get(\"configurePresets\", [])]; "
                    "p.write_text(json.dumps(d, indent=4, ensure_ascii=False)+\"\\n\")' && "
                    "echo CMAKE_BUILD_TYPE=Debug && "
                    "bash build.sh"
                ),
                "fields": [
                    {"type": "note",
                     "text": "Debug 是仿真/调试模式：后面做 msOpGen sim 的 -reloc 时，要选 build_out/op_kernel/binary/... 下面的 Debug kernel .o，不要选 run/out/main。若仍提示没有 debug info，再检查 op_kernel/CMakeLists.txt 是否需要按官方说明额外加 -g。注意：Debug 也不能替代手写实现；刚 gen 出来的骨架仍要先补 kernel/tiling/host 代码。"},
                    {"key": "project", "label": "OPP 工程目录", "type": "text",
                     "default": "/home/HwHiAiUser/work/rgb_to_gray_gen"},
                ],
            },
            {
                "name": "官方 compile 入口（备用校验，不是 Debug 模式）",
                "target": "board",
                "desc": "调用 msopgen compile 对工程进行官方编译校验。该入口用于备用排查，不负责切换 Release/Debug 构建模式。",
                "template": "{cann_env} && msopgen compile -i {project} -c {cann_path_arg}{options}",
                "fields": [
                    {"type": "note",
                     "text": "适用范围：备用编译校验或对照官方 compile 子命令行为。常规安装验证请优先使用 Release 构建；需要 msOpGen sim -reloc 源码/指令映射时，请使用 Debug 构建。若这里提示 CANN 安装路径 read permission，请检查 -c 指向的 CANN 路径是否可读，或改用上方 build.sh 构建入口。"},
                    {"key": "project", "label": "OPP 工程目录", "type": "text",
                     "default": "/home/HwHiAiUser/work/add_custom_opgen_v1"},
                    {"key": "cann_path_arg", "label": "CANN 安装路径", "type": "text",
                     "default": "{cann_path}", "required": True},
                    {"key": "quiet", "label": "我想跳过交互询问", "type": "check",
                     "default": True, "option": "-q"},
                ],
            },
            {
                "name": "安装自定义 OPP 包",
                "target": "board",
                "desc": "把 build_out 里的 .run 安装到指定自定义 OPP 目录。安装目录后续给 msOpST/msProf source。",
                "template": "cd {build_out} && bash {run_pkg} --quiet --install-path={install_dir}",
                "fields": [
                    {"type": "note",
                     "text": "安装目录可以直接输入一个不存在的新目录，安装脚本会创建它。建议不同算子/不同模式分开，例如 /home/HwHiAiUser/custom_opp_rgb_debug，避免和 AddCustom 旧包混在一起。"},
                    {"key": "build_out", "label": "build_out 目录", "type": "text",
                     "default": "/home/HwHiAiUser/work/add_custom_opgen_v1/build_out"},
                    {"key": "run_pkg", "label": ".run 包名", "type": "text",
                     "default": "custom_opp_ubuntu_aarch64.run"},
                    {"key": "install_dir", "label": "安装目录", "type": "text",
                     "default": "{custom_opp_opgen}"},
                ],
            },
        ],
    },
    {
        "group": "3. msOpST — 功能测试",
        "items": [
            {
                "name": "生成测试用例骨架（create）",
                "target": "board",
                "desc": "从 op_host/*.cpp 解析算子原型，生成 case JSON 骨架；shape 和 golden 函数需要再补。",
                "template": "cd {workdir} && {cann_env} && {pre}msopst create -i {op_host_cpp} -out {output_dir}{options}",
                "fields": [
                    {"type": "note",
                     "text": "create 是从 op_host/*.cpp 生成 case 骨架。官方的 -q 静默模式必须配合 -m 模型文件使用；没有模型时勾静默会报错，所以这里自动绑定。"},
                    {"key": "workdir", "label": "板端工作目录", "type": "text",
                     "default": "/home/HwHiAiUser/work/msopst_create_run_addcustom_20260608_official"},
                    {"key": "op_host_cpp", "label": "op_host cpp 路径", "type": "text",
                     "default": "/home/HwHiAiUser/work/add_custom_opgen_v1/op_host/add_custom.cpp"},
                    {"key": "output_dir", "label": "输出目录", "type": "text",
                     "default": "./create_out"},
                    {"key": "src_opp", "label": "create 前先加载自定义 OPP 运行环境（source + export，算子已编译安装后勾选，省去手动补这几行）", "type": "check",
                     "default": False},
                    {"key": "opp_set_env", "label": "自定义 OPP set_env.bash 路径", "type": "text",
                     "default": "{custom_opp_opgen}/vendors/customize/bin/set_env.bash",
                     "enabled_by": "src_opp",
                     "prefix_option": "source {opp_set_env} && export DDK_PATH={cann_path} && export NPU_HOST_LIB={cann_path}/aarch64-linux/devlib && "},
                    {"key": "use_model", "label": "我有模型文件，希望按模型生成/筛选测试用例", "type": "check",
                     "default": False},
                    {"key": "model_path", "label": "模型文件路径", "type": "text",
                     "default": "./model.pb", "enabled_by": "use_model", "option": "-m {model_path}"},
                    {"key": "quiet", "label": "模型模式下静默生成，不交互询问", "type": "check",
                     "default": False, "enabled_by": "use_model", "option": "-q"},
                ],
            },
            {
                "name": "运行算子自测（run）",
                "target": "board",
                "desc": "加载自定义 OPP 后执行 msopst run。AddCustom/ReduceSum/RgbToGray 都走过这条线。",
                "template": (
                    "cd {workdir} && "
                    "{cann_env} && "
                    "source {opp_dir}/vendors/customize/bin/set_env.bash && "
                    "export DDK_PATH={cann_path} && "
                    "export NPU_HOST_LIB={cann_path}/aarch64-linux/devlib && "
                    "msopst run -i {case_json} -soc {soc} -out {output}{options}"
                ),
                "fields": [
                    {"type": "note",
                     "text": "run 是我们现在最稳的功能测试入口。310B 板端这里写 Ascend310B1；需要失败 diff、指定 case、设备号、误差阈值或高级配置时，直接勾需求即可。"},
                    {"key": "workdir", "label": "板端工作目录", "type": "text",
                     "default": "/home/HwHiAiUser/work/msopst_opgen_v1_test"},
                    {"key": "opp_dir", "label": "自定义 OPP 安装目录", "type": "text",
                     "default": "{custom_opp_opgen}"},
                    {"key": "case_json", "label": "case JSON", "type": "text",
                     "default": "./addcustom_opgen_case.json"},
                    {"key": "soc", "label": "板端 SOC 名称", "type": "combo",
                     "default": "Ascend310B1",
                     "options": ["Ascend310B1", "Ascend310B4", "Ascend910B1"],
                     "required": True},
                    {"key": "output", "label": "输出目录", "type": "text",
                     "default": "./run_out"},
                    {"key": "pick_case", "label": "我只想跑某个 case，不跑全部", "type": "check",
                     "default": False},
                    {"key": "case_name", "label": "case 名称", "type": "text",
                     "default": "all", "enabled_by": "pick_case", "option": "-c {case_name}"},
                    {"key": "set_device", "label": "我需要指定 NPU 设备号", "type": "check",
                     "default": False},
                    {"key": "device_id", "label": "device id", "type": "text",
                     "default": "0", "enabled_by": "set_device", "option": "-d {device_id}"},
                    {"key": "set_err_thr", "label": "我需要临时覆盖精度误差阈值", "type": "check",
                     "default": False},
                    {"key": "err_thr", "label": "误差阈值", "type": "text",
                     "default": "[0.001, 0.001]", "enabled_by": "set_err_thr", "option": "-err_thr \"{err_thr}\""},
                    {"key": "need_err_report", "label": "我需要失败时导出差异报告 CSV", "type": "check",
                     "default": True, "option": "-err_report true"},
                    {"key": "use_conf", "label": "我有高级配置文件", "type": "check",
                     "default": False},
                    {"key": "conf_file", "label": "配置文件", "type": "text",
                     "default": "./config.json", "enabled_by": "use_conf", "option": "-conf {conf_file}"},
                ],
            },
            {
                "name": "ascendc_test 生成（仅探路）",
                "target": "board",
                "desc": "仅保留为 kernel 直跑/调试脚手架实验入口；不要把它当成功能正确性主线，也不要用它证明 blockDim/tiling。",
                "template": "cd {workdir} && {cann_env} && msopst ascendc_test -i {case_json} -kernel {kernel_cpp} -out {output}",
                "fields": [
                    {"type": "note",
                     "text": "为什么只探路：ascendc_test 不是完整 OPP 工程验证，也不做 golden 自动比对；它生成的是调用 Ascend C kernel 的测试脚手架。官方限制里明确不支持 addr/tiling 参数，我们的工程化 kernel 若带 workspace/tiling 需要改包装函数甚至砍参数。CANN 8.5 生成器还对 C++ 排版很敏感：kernel 签名跨行会被截断，参数要写成 uint8_t* x 这种“星号贴类型”的形式。生成的 main.cpp 里 blockDim 也写死为 1，所以不能用来证明多 block/切分策略。功能验证请优先走 create + case JSON + run。"},
                    {"key": "workdir", "label": "板端工作目录", "type": "text",
                     "default": "/home/HwHiAiUser/work/msopst_addcustom_probe_20260607"},
                    {"key": "case_json", "label": "case JSON", "type": "text",
                     "default": "./addcustom_case.json"},
                    {"key": "kernel_cpp", "label": "核函数包装 cpp", "type": "text",
                     "default": "./add_custom_msopst.cpp"},
                    {"key": "output", "label": "输出目录", "type": "text",
                     "default": "./out"},
                ],
            },
        ],
    },
    {
        "group": "4. msProf — 上板采集 / 仿真",
        "items": [
            {
                "name": "op 上板采集（算子性能细分析）",
                "target": "board",
                "desc": "真实 310B4 硬件采集。按想看的分析图勾选，工具箱自动追加采集指标。",
                "template": (
                    "cd {workdir} && "
                    "{cann_env} && "
                    "source {opp_dir}/vendors/customize/bin/set_env.bash && "
                    "mkdir -p {output} && chmod 700 {output} && "
                    "msprof op{options} --aic-metrics={metrics} --output={output} {app}"
                ),
                "fields": [
                    {"type": "note",
                     "text": "这页按“想分析什么”来勾：Roofline 瓶颈分析图、计算内存热力图、缓存热力图、通算流水图、内存通路吞吐率波形图，对应的采集指标由工具箱自动拼到命令里。需要只采某个核函数或排除预热影响时，再勾下面的过滤项。"},
                    {"key": "workdir", "label": "板端工作目录", "type": "text",
                     "default": "/home/HwHiAiUser/work/msopst_opgen_v1_test/run_out/20260609033550/AddCustom/run/out"},
                    {"key": "opp_dir", "label": "自定义 OPP 安装目录", "type": "text",
                     "default": "{custom_opp_dim8_g}"},
                    {"key": "app", "label": "可执行文件", "type": "text",
                     "default": "./main"},
                    {"key": "output", "label": "输出目录（建议 home 下）", "type": "text",
                     "default": "/home/HwHiAiUser/prof_add_toolbox"},
                    {"key": "metric_pipe", "label": "我要看通算流水图和各流水单元占用", "type": "check",
                     "default": True, "metric": "PipeUtilization"},
                    {"key": "metric_arith", "label": "我要看计算侧数据，用于计算内存热力图和 Roofline 瓶颈分析图", "type": "check",
                     "default": True, "metric": "ArithmeticUtilization"},
                    {"key": "metric_mem", "label": "我要看内存通路吞吐率波形图", "type": "check",
                     "default": True, "metric": "Memory"},
                    {"key": "metric_l2", "label": "我要看缓存热力图和二级缓存命中情况", "type": "check",
                     "default": True, "metric": "L2Cache"},
                    {"key": "metric_ub", "label": "我要细看统一缓冲区读写情况", "type": "check",
                     "default": False, "metric": "MemoryUB"},
                    {"key": "metric_l0", "label": "我要细看零级缓存读写情况", "type": "check",
                     "default": False, "metric": "MemoryL0"},
                    {"key": "metric_conflict", "label": "我要看资源冲突比例", "type": "check",
                     "default": False, "metric": "ResourceConflictRatio"},
                    {"key": "use_custom_metrics", "label": "我要自己补充高级采集指标", "type": "check",
                     "default": False},
                    {"key": "custom_metrics", "label": "高级指标原文", "type": "text",
                     "default": "Custom:xx,xx", "enabled_by": "use_custom_metrics", "metric_from_value": True},
                    {"key": "filter_kernel", "label": "我只想采某个核函数", "type": "check",
                     "default": False},
                    {"key": "kernel_name", "label": "核函数名称", "type": "text",
                     "default": "AddCustom", "enabled_by": "filter_kernel", "option": "--kernel-name={kernel_name}"},
                    {"key": "limit_launch", "label": "我想限制采集启动次数", "type": "check",
                     "default": False},
                    {"key": "launch_count", "label": "采集次数", "type": "text",
                     "default": "1", "enabled_by": "limit_launch", "option": "--launch-count={launch_count}"},
                    {"key": "skip_before", "label": "我想匹配到核函数后先跳过若干次", "type": "check",
                     "default": False},
                    {"key": "launch_skip", "label": "跳过次数", "type": "text",
                     "default": "1", "enabled_by": "skip_before", "option": "--launch-skip-before-match={launch_skip}"},
                    {"key": "warmup", "label": "我想先预热再正式采集", "type": "check",
                     "default": False},
                    {"key": "warmup_count", "label": "预热次数", "type": "text",
                     "default": "1", "enabled_by": "warmup", "option": "--warm-up={warmup_count}"},
                    {"key": "set_replay", "label": "我需要指定重放模式", "type": "check",
                     "default": False},
                    {"key": "replay_mode", "label": "重放模式", "type": "combo",
                     "default": "kernel", "options": ["kernel", "task"],
                     "enabled_by": "set_replay", "option": "--replay-mode={replay_mode}"},
                    {"key": "need_mstx", "label": "我的程序里用了用户事件标记，采集时也打开", "type": "check",
                     "default": False, "option": "--mstx=on"},
                ],
            },
            {
                "name": "传统 db 采集（4.1 粗粒度）",
                "target": "board",
                "desc": "对应 4.1 早期 msprof --type=db 路线，只看核函数任务总时间。",
                "template": (
                    "cd {workdir} && "
                    "{cann_env} && "
                    "source {opp_dir}/vendors/customize/bin/set_env.bash && "
                    "mkdir -p {output} && chmod 700 {output} && "
                    "msprof --application={app} --type=db --output={output}"
                ),
                "fields": [
                    {"type": "note",
                     "text": "这是 4.1 用过的粗粒度路线，重点看 AI Core 任务总时长、block_dim 等 sqlite 汇总；不适合替代 op 模式里的通算流水、内存通路和 Roofline 细分析。"},
                    {"key": "workdir", "label": "板端工作目录", "type": "text",
                     "default": "/home/HwHiAiUser/work/acl_online_addcustom_verify"},
                    {"key": "opp_dir", "label": "自定义 OPP 安装目录", "type": "text",
                     "default": "{custom_opp_addcustom_cann85}"},
                    {"key": "app", "label": "运行命令/脚本", "type": "text",
                     "default": "./run.sh 0"},
                    {"key": "output", "label": "输出目录", "type": "text",
                     "default": "/home/HwHiAiUser/prof_db_toolbox"},
                ],
            },
            {
                "name": "导出传统 db 采集结果",
                "target": "board",
                "desc": "对已经采到的 msprof --type=db 输出补执行 export，便于本地 sqlite/CSV 分析。",
                "template": "{cann_env} && msprof --export=on --output={output} --type=db",
                "fields": [
                    {"type": "note",
                     "text": "如果传统 db 目录里没有导出的 sqlite/CSV，就对同一个 output 目录跑这个按钮。注意这里不是重新采集，只是导出。"},
                    {"key": "output", "label": "已有 profiling 输出目录", "type": "text",
                     "default": "/home/HwHiAiUser/prof_db_toolbox"},
                ],
            },
            {
                "name": "op 软件仿真生成仿真数据",
                "target": "board",
                "desc": "软件仿真指令流水。输出仿真数据后，再用 msOpGen sim 转成可视化时间线。",
                "template": (
                    "cd {workdir} && "
                    "{cann_env} && "
                    "mkdir -p {output} && chmod 700 {output} && "
                    "msprof op simulator --soc-version={soc}{options} --output={output} {app}"
                ),
                "fields": [
                    {"type": "note",
                     "text": "软件仿真适合看指令流水图，不代表真实 310B4 绝对性能。生成仿真数据后，再用 msOpGen sim 转成可视化时间线。"},
                    {"key": "workdir", "label": "main 所在目录", "type": "text",
                     "default": "/home/HwHiAiUser/work/msopst_rsc_test/run_out_debug/20260609061927/ReduceSumCustom/run/out"},
                    {"key": "app", "label": "可执行文件", "type": "text",
                     "default": "./main"},
                    {"key": "soc", "label": "仿真 SOC", "type": "combo",
                     "default": "Ascend310B1", "options": ["Ascend310B1", "Ascend310B4", "Ascend910B1"],
                     "required": True},
                    {"key": "output", "label": "仿真输出目录", "type": "text",
                     "default": "/home/HwHiAiUser/sim_out_toolbox"},
                    {"key": "need_dump", "label": "我要生成仿真数据，供 msOpGen sim 转可视化时间线", "type": "check",
                     "default": True, "option": "--dump=on"},
                ],
            },
            {
                "name": "msOpGen sim 转时间线",
                "target": "board",
                "desc": "把仿真数据转为 Chrome tracing 可读的时间线文件。",
                "template": (
                    "{cann_env} && "
                    "mkdir -p {output} && chmod 700 {output} && "
                    "msopgen sim -c {core} -d {dump_dir}{options} -out {output}"
                ),
                "fields": [
                    {"type": "note",
                     "text": "源码参数表确认必填 core、dump-dir、output；我们板子上优先选 simulator 生成的 device0/tmp_dump 目录。310B 矢量算子优先用 veccore0。普通时间线可以不勾 -reloc；如果要关联源码/指令位置，必须先 Debug 编译，再选 build_out/op_kernel/binary/... 里的 kernel .o，不能选 run/out/main 或 ./main。"},
                    {"key": "dump_dir", "label": "仿真数据目录", "type": "text",
                     "default": "/home/HwHiAiUser/sim_out_toolbox/OPPROF_xxx/device0/tmp_dump"},
                    {"key": "core", "label": "AI Core 编号", "type": "combo",
                     "default": "core0", "options": ["core0", "core1", "core2", "core3"]},
                    {"key": "use_subcore", "label": "我需要指定子核/向量核（310B 默认需要）", "type": "check",
                     "default": True},
                    {"key": "subcore", "label": "子核/向量核", "type": "combo",
                     "default": "veccore0", "options": ["veccore0", "cubecore0", "mixcore"],
                     "enabled_by": "use_subcore", "option": "-subc {subcore}"},
                    {"key": "mixcore", "label": "这是 910B 混合核 dump，需要按 mixcore 模式解析", "type": "check",
                     "default": False, "option": "-mix"},
                    {"key": "use_reloc", "label": "我已经 Debug 编译，并且想用 kernel .o 关联源码/指令位置", "type": "check",
                     "default": False},
                    {"key": "relocatable_file", "label": "Debug kernel .o（板端绝对路径）", "type": "text",
                     "default": "/home/HwHiAiUser/work/rgb_to_gray_gen/build_out/op_kernel/binary/ascend310b/rgb_to_gray_custom/RgbToGrayCustom_95ad72606637cc6014ec58666087e716.o",
                     "enabled_by": "use_reloc", "option": "-reloc {relocatable_file}", "remote": True,
                     "required": True},
                    {"key": "output", "label": "时间线输出目录", "type": "text",
                     "default": "/home/HwHiAiUser/trace_out_toolbox"},
                ],
            },
        ],
    },
    {
        "group": "5. msKPP — 理论建模",
        "items": [
            {
                "name": "运行 KPP 脚本",
                "target": "board",
                "desc": "KPP 用 910B 参数看趋势，不代表 310B4 绝对时间。输出目录不能 group-writable。",
                "template": (
                    "mkdir -p {outdir} && chmod 755 {outdir} && "
                    "cd {outdir} && "
                    "{cann_env} && "
                    "python3 {script}"
                ),
                "fields": [
                    {"key": "script", "label": "板端 KPP 脚本", "type": "text",
                     "default": "/home/HwHiAiUser/work/rgb_to_gray_kpp.py"},
                    {"key": "outdir", "label": "KPP 输出目录", "type": "text",
                     "default": "{kpp_out}"},
                ],
            },
            {
                "name": "查看 KPP 公开 API",
                "target": "board",
                "desc": "快速确认 mskpp 模块是否能 import，并列出顶层对象和 apis。",
                "template": (
                    "{cann_env} && "
                    "python3 -c \"import mskpp, mskpp.apis as apis; "
                    "print(mskpp.__file__); "
                    "print([x for x in dir(mskpp) if not x.startswith('_')]); "
                    "print([x for x in dir(apis) if not x.startswith('_')][:80])\""
                ),
                "fields": [],
            },
        ],
    },
    {
        "group": "6. 本地分析 / 下载",
        "items": [
            {
                "name": "生成 Roofline 瓶颈分析图（多规格对比）",
                "target": "local",
                "desc": "任意添加/删除规格行，把多个 msprof 目录的点画到同一张 Roofline 图上。",
                "template": '"{python}" "{script}" {cases} --vec-flop-per-elem {vec_flop} --op-name "{op_name}" --output "{output}"',
                "fields": [
                    {"key": "python", "label": "Python 解释器", "type": "file",
                     "default": LOCAL_PYTHON},
                    {"key": "script", "label": "roofline_plot.py", "type": "file",
                     "default": "{workspace}/官方算子开发工具/msProf/Roofline调研/tools/roofline_plot.py"},
                    {"key": "cases", "type": "case_list", "label": "规格列表（目录 | 总像素数 | blockdim | 标签）",
                     "default_rows": [
                         {"dir": f"{LOCAL_ROOT}/官方算子开发工具/msProf/RgbToGrayCustom实测/64x64",
                          "elements": "4096", "blockdim": "1", "label": "RGB 64×64"},
                         {"dir": f"{LOCAL_ROOT}/官方算子开发工具/msProf/RgbToGrayCustom实测/128x128",
                          "elements": "16384", "blockdim": "1", "label": "RGB 128×128"},
                         {"dir": f"{LOCAL_ROOT}/官方算子开发工具/msProf/RgbToGrayCustom实测/256x256",
                          "elements": "65536", "blockdim": "1", "label": "RGB 256×256"},
                     ]},
                    {"key": "vec_flop", "label": "每元素向量 FLOP", "type": "text", "default": "5"},
                    {"key": "op_name", "label": "算子名称", "type": "text", "default": "RgbToGrayCustom"},
                    {"key": "output", "label": "输出图片", "type": "text",
                     "default": f"{LOCAL_ROOT}/官方算子开发工具/msProf/RgbToGrayCustom实测/分析数据/02_Roofline瓶颈分析图/rgb_roofline_compare.png"},
                ],
            },
            {
                "name": "生成 PIPE 利用率热力图（01_计算内存热力图）",
                "target": "local",
                "desc": "读取各规格的 PipeUtilization.csv，画出 PIPE × case 的利用率热力图（颜色深浅=利用率高低）。",
                "template": '"{python}" "{script}" --mode heatmap {cases} --op-name "{op_name}" --output "{output}"',
                "fields": [
                    {"key": "python", "label": "Python 解释器", "type": "file", "default": LOCAL_PYTHON},
                    {"key": "script", "label": "pipe_util_plot.py", "type": "file",
                     "default": "{workspace}/官方算子开发工具/msProf/Roofline调研/tools/pipe_util_plot.py"},
                    {"key": "cases", "type": "case_list", "label": "规格列表（目录 | 标签）",
                     "default_rows": [
                         {"dir": f"{LOCAL_ROOT}/官方算子开发工具/msProf/RgbToGrayCustom实测/64x64",
                          "elements": "0", "blockdim": "1", "label": "RGB 64×64"},
                         {"dir": f"{LOCAL_ROOT}/官方算子开发工具/msProf/RgbToGrayCustom实测/128x128",
                          "elements": "0", "blockdim": "1", "label": "RGB 128×128"},
                         {"dir": f"{LOCAL_ROOT}/官方算子开发工具/msProf/RgbToGrayCustom实测/256x256",
                          "elements": "0", "blockdim": "1", "label": "RGB 256×256"},
                     ]},
                    {"key": "op_name", "label": "算子名称", "type": "text", "default": "RgbToGrayCustom"},
                    {"key": "output", "label": "输出图片", "type": "text",
                     "default": f"{LOCAL_ROOT}/官方算子开发工具/msProf/RgbToGrayCustom实测/分析数据/01_计算内存热力图/pipe_heatmap.png"},
                ],
            },
            {
                "name": "生成通算流水图（04_通算流水图）",
                "target": "local",
                "desc": "读取各规格的 PipeUtilization.csv，画出各 PIPE 绝对耗时的堆叠柱状图（μs）。",
                "template": '"{python}" "{script}" --mode stacked {cases} --op-name "{op_name}" --output "{output}"',
                "fields": [
                    {"key": "python", "label": "Python 解释器", "type": "file", "default": LOCAL_PYTHON},
                    {"key": "script", "label": "pipe_util_plot.py", "type": "file",
                     "default": "{workspace}/官方算子开发工具/msProf/Roofline调研/tools/pipe_util_plot.py"},
                    {"key": "cases", "type": "case_list", "label": "规格列表（目录 | 标签）",
                     "default_rows": [
                         {"dir": f"{LOCAL_ROOT}/官方算子开发工具/msProf/RgbToGrayCustom实测/64x64",
                          "elements": "0", "blockdim": "1", "label": "RGB 64×64"},
                         {"dir": f"{LOCAL_ROOT}/官方算子开发工具/msProf/RgbToGrayCustom实测/128x128",
                          "elements": "0", "blockdim": "1", "label": "RGB 128×128"},
                         {"dir": f"{LOCAL_ROOT}/官方算子开发工具/msProf/RgbToGrayCustom实测/256x256",
                          "elements": "0", "blockdim": "1", "label": "RGB 256×256"},
                     ]},
                    {"key": "op_name", "label": "算子名称", "type": "text", "default": "RgbToGrayCustom"},
                    {"key": "output", "label": "输出图片", "type": "text",
                     "default": f"{LOCAL_ROOT}/官方算子开发工具/msProf/RgbToGrayCustom实测/分析数据/04_通算流水图/pipe_stacked.png"},
                ],
            },
            {
                "name": "生成 L2 Cache 命中率图（03_Cache热力图）",
                "target": "local",
                "desc": "读取各规格的 L2Cache.csv，画出写/读/总命中率的分组柱状图。",
                "template": '"{python}" "{script}" {cases} --op-name "{op_name}" --output "{output}"',
                "fields": [
                    {"key": "python", "label": "Python 解释器", "type": "file", "default": LOCAL_PYTHON},
                    {"key": "script", "label": "l2cache_plot.py", "type": "file",
                     "default": "{workspace}/官方算子开发工具/msProf/Roofline调研/tools/l2cache_plot.py"},
                    {"key": "cases", "type": "case_list", "label": "规格列表（目录 | 标签）",
                     "default_rows": [
                         {"dir": f"{LOCAL_ROOT}/官方算子开发工具/msProf/RgbToGrayCustom实测/64x64",
                          "elements": "0", "blockdim": "1", "label": "RGB 64×64"},
                         {"dir": f"{LOCAL_ROOT}/官方算子开发工具/msProf/RgbToGrayCustom实测/128x128",
                          "elements": "0", "blockdim": "1", "label": "RGB 128×128"},
                         {"dir": f"{LOCAL_ROOT}/官方算子开发工具/msProf/RgbToGrayCustom实测/256x256",
                          "elements": "0", "blockdim": "1", "label": "RGB 256×256"},
                     ]},
                    {"key": "op_name", "label": "算子名称", "type": "text", "default": "RgbToGrayCustom"},
                    {"key": "output", "label": "输出图片", "type": "text",
                     "default": f"{LOCAL_ROOT}/官方算子开发工具/msProf/RgbToGrayCustom实测/分析数据/03_Cache热力图/l2cache.png"},
                ],
            },
            {
                "name": "生成内存通路带宽图（07_内存通路吞吐率波形图）",
                "target": "local",
                "desc": "读取各规格的 Memory.csv，画出读/写带宽对比和总带宽利用率图。",
                "template": '"{python}" "{script}" {cases} --peak-bw {peak_bw} --op-name "{op_name}" --output "{output}"',
                "fields": [
                    {"key": "python", "label": "Python 解释器", "type": "file", "default": LOCAL_PYTHON},
                    {"key": "script", "label": "mem_bw_plot.py", "type": "file",
                     "default": "{workspace}/官方算子开发工具/msProf/Roofline调研/tools/mem_bw_plot.py"},
                    {"key": "cases", "type": "case_list", "label": "规格列表（目录 | 标签）",
                     "default_rows": [
                         {"dir": f"{LOCAL_ROOT}/官方算子开发工具/msProf/RgbToGrayCustom实测/64x64",
                          "elements": "0", "blockdim": "1", "label": "RGB 64×64"},
                         {"dir": f"{LOCAL_ROOT}/官方算子开发工具/msProf/RgbToGrayCustom实测/128x128",
                          "elements": "0", "blockdim": "1", "label": "RGB 128×128"},
                         {"dir": f"{LOCAL_ROOT}/官方算子开发工具/msProf/RgbToGrayCustom实测/256x256",
                          "elements": "0", "blockdim": "1", "label": "RGB 256×256"},
                     ]},
                    {"key": "peak_bw", "label": "峰值带宽 GB/s", "type": "text", "default": "34"},
                    {"key": "op_name", "label": "算子名称", "type": "text", "default": "RgbToGrayCustom"},
                    {"key": "output", "label": "输出图片", "type": "text",
                     "default": f"{LOCAL_ROOT}/官方算子开发工具/msProf/RgbToGrayCustom实测/分析数据/07_内存通路吞吐率波形图/mem_bw.png"},
                ],
            },
            {
                "name": "生成代码热点图（06_算子代码热点图）",
                "target": "local",
                "desc": "读取 msprof op simulator 生成的 code_exe_prof.csv，按 cycles 画横向柱状图，区分用户代码和框架代码。数据来自软件仿真。",
                "template": '"{python}" "{script}" --csv "{csv}" --op-name "{op_name}" --top {top} --output "{output}"',
                "fields": [
                    {"key": "python", "label": "Python 解释器", "type": "file", "default": LOCAL_PYTHON},
                    {"key": "script", "label": "code_hotspot_plot.py", "type": "file",
                     "default": "{workspace}/官方算子开发工具/msProf/Roofline调研/tools/code_hotspot_plot.py"},
                    {"key": "csv", "label": "code_exe_prof.csv", "type": "file",
                     "default": f"{LOCAL_ROOT}/官方算子开发工具/msProf/RgbToGrayCustom实测/分析数据/05_指令流水图/core0_veccore0_code_exe_prof_310B4.csv"},
                    {"key": "op_name", "label": "算子名称", "type": "text", "default": "RgbToGrayCustom 128×128（仿真）"},
                    {"key": "top", "label": "显示前 N 行", "type": "text", "default": "15"},
                    {"key": "output", "label": "输出图片", "type": "text",
                     "default": f"{LOCAL_ROOT}/官方算子开发工具/msProf/RgbToGrayCustom实测/分析数据/06_算子代码热点图/code_hotspot.png"},
                ],
            },
            {
                "name": "读取 4.1 profiling tar/sqlite 摘要",
                "target": "local",
                "desc": "复用 agent_tools/profiling_sqlite_summary.py，读取 tar.gz 或 sqlite 的 block_dim 和任务时间。",
                "template": '"{python}" "{script}" "{profile}"',
                "fields": [
                    {"key": "python", "label": "Python 解释器", "type": "file",
                     "default": LOCAL_PYTHON},
                    {"key": "script", "label": "摘要脚本", "type": "file",
                     "default": "{workspace}/agent_tools/profiling_sqlite_summary.py"},
                    {"key": "profile", "label": "profiling tar/sqlite/目录", "type": "file",
                     "default": f"{LOCAL_ROOT}/4.算子实现-矢量编程/4.1profiling/add_perf_orig_100_20260605155505.tar.gz"},
                ],
            },
        ],
    },
    {
        "group": "7. 待探索 — msDebug / msSanitizer",
        "items": [
            {
                "name": "msDebug help/version（310B4 已判定不支持实时调试）",
                "target": "board",
                "desc": "只保留 help/version。310B4 上 msDebug 能启动，但缺 NPU 调试通道，实时断点/单步/变量查看已实测不可用。",
                "template": "{cann_env} && msdebug --version && msdebug --help | head -80",
                "fields": [
                    {"type": "note",
                     "text": "当前统一口径：Atlas 200I DK A2 / Ascend310B4 上，msDebug 实时调试 NPU kernel 已结案为不支持。现象是 run 阶段报 please install HDK / 0x20102；升级到驱动 25.5.0 + 固件 7.8.0.5.216 后仍无 /proc/debug_switch 和 ts_debug*.ko。这里保留 help/version 只是确认工具存在，不代表能调 kernel。"},
                ],
            },
            {
                "name": "msSanitizer 异常检测",
                "target": "board",
                "desc": "探索中的异常检测入口。这里按官方功能给出命令行，不保证当前算子已经能被稳定检测。",
                "template": "cd {workdir} && {cann_env} && source {opp_dir}/vendors/customize/bin/set_env.bash && mssanitizer --tool={check_type}{options} -- {app}",
                "fields": [
                    {"type": "note",
                     "text": "注意：这块仍在探索，不是稳定教程。当前按钮只是按官方 msSanitizer 功能给出命令行入口；我们已确认工具能启动并包住 runner，但还没结案证明 msOpGen binary kernel 的 -g/-sanitizer 插桩链路稳定生效。若没报错，不代表算子一定没有越界/竞争；可能只是当前 OPP 没带插桩。只是想查语法时，请用 build.sh 或 msopgen compile。"},
                    {"key": "workdir", "label": "runner 所在目录", "type": "text",
                     "default": "/home/HwHiAiUser/work/msopst_opgen_v1_test/run_out/20260609033550/AddCustom/run/out"},
                    {"key": "opp_dir", "label": "自定义 OPP 安装目录", "type": "text",
                     "default": "{custom_opp_opgen}"},
                    {"key": "check_type", "label": "我要检查的问题类型", "type": "combo",
                     "default": "memcheck", "options": ["memcheck", "racecheck", "initcheck"]},
                    {"key": "filter_kernel", "label": "我只想检查某个核函数", "type": "check",
                     "default": True},
                    {"key": "kernel_name", "label": "核函数名称", "type": "text",
                     "default": "AddCustom", "enabled_by": "filter_kernel", "option": "--kernel-name={kernel_name}"},
                    {"key": "app", "label": "可执行文件", "type": "text",
                     "default": "./main"},
                ],
            },
        ],
    },
    {
        "group": "8. 文件传输（SCP）",
        "items": [
            {
                "name": "上传到开发板",
                "target": "local",
                "desc": "把本地目录上传到板子。也可以优先用右上角 SFTP 文件管理器。",
                "template": 'scp -r "{local}" {board_user}@{board_host}:{remote}',
                "fields": [
                    {"key": "local", "label": "本地路径", "type": "dir",
                     "default": f"{LOCAL_ROOT}/"},
                    {"key": "remote", "label": "板端目标路径", "type": "text",
                     "default": "{work_dir}/"},
                ],
            },
            {
                "name": "从开发板下载数据",
                "target": "local",
                "desc": "把板端性能采集、软件仿真、时间线输出拉回本地。",
                "template": 'scp -r {board_user}@{board_host}:{remote} "{local}"',
                "fields": [
                    {"key": "remote", "label": "板端路径", "type": "text",
                     "default": "/home/HwHiAiUser/prof_add_toolbox/"},
                    {"key": "local", "label": "本地保存到", "type": "dir",
                     "default": f"{LOCAL_ROOT}/官方算子开发工具/msProf/AddCustom实测/"},
                ],
            },
        ],
    },
]

TOOLS = _sort_and_renumber_tool_groups(TOOLS)
TOOLS = _merge_tool_groups(TOOLS, load_plugin_tool_groups())


# ── SFTP 文件管理器窗口 ────────────────────────────────────────────────────────

class FileBrowser(tk.Toplevel):
    """板端 SFTP 文件浏览器 + 内嵌编辑器，支持查看、编辑、保存、下载。"""

    def __init__(self, parent, ssh_client, board_host, board_user, default_remote_dir):
        super().__init__(parent)
        self.title(f"板端文件管理器  —  {board_host}")
        self.geometry("1220x780")
        self.minsize(960, 620)
        self._sftp = ssh_client.open_sftp()
        self._cwd = default_remote_dir or f"/home/{board_user}/work"
        self._open_path = None
        self._dirty = False
        self._loaded_content = ""    # 打开时的内容快照，用于保存前的覆盖检测
        self._highlight_job = None
        self._find_dlg = None
        self._entries = []          # [(kind, name), ...]，与列表框行一一对应
        self._build()
        self._refresh()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _confirm_discard(self):
        """有未保存改动时弹窗确认。返回 True 表示可以继续（放弃改动或无改动）。"""
        if not self._dirty:
            return True
        name = self._open_path.split("/")[-1] if self._open_path else "当前文件"
        ans = messagebox.askyesnocancel(
            "未保存的改动",
            f"“{name}” 有未保存的改动。\n\n是 = 先保存再继续\n否 = 放弃改动\n取消 = 留在当前文件",
            parent=self)
        if ans is None:          # 取消
            return False
        if ans:                  # 是：先保存
            self._save()
            return not self._dirty   # 保存失败则不继续
        return True              # 否：放弃改动

    def _on_close(self):
        if not self._confirm_discard():
            return
        try:
            self._sftp.close()
        except Exception:
            pass
        self.destroy()

    # ── 界面构建 ──────────────────────────────────────────────────────────────

    def _build(self):
        # 导航栏
        nav = ttk.Frame(self)
        nav.pack(fill=tk.X, padx=8, pady=(8, 0))
        ttk.Label(nav, text="路径：", font=FONT_UI).pack(side=tk.LEFT)
        self._path_var = tk.StringVar(value=self._cwd)
        pe = ttk.Entry(nav, textvariable=self._path_var, width=54)
        pe.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 6))
        pe.bind("<Return>", lambda _: self._navigate(self._path_var.get().strip()))
        ttk.Button(nav, text="↑ 上级",  command=self._up,      width=7).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(nav, text="🔄 刷新", command=self._refresh, width=7).pack(side=tk.LEFT)

        ttk.Separator(self).pack(fill=tk.X, padx=8, pady=4)

        # 左右分栏
        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=8)

        # ── 左：文件列表
        left = ttk.Frame(paned, width=360)
        paned.add(left, weight=1)
        self._lb = tk.Listbox(
            left, selectmode="single", font=FONT_MONO,
            activestyle="none",
            bg="#252526", fg="#cccccc",
            selectbackground="#094771", selectforeground="white",
            relief="flat",
        )
        vsb = ttk.Scrollbar(left, orient="vertical", command=self._lb.yview)
        self._lb.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._lb.pack(fill=tk.BOTH, expand=True)
        self._lb.bind("<Double-Button-1>", self._on_dclick)
        self._lb.bind("<Return>",          self._on_dclick)

        # ── 右：编辑器
        right = ttk.Frame(paned)
        paned.add(right, weight=3)

        self._file_label = ttk.Label(
            right, text="（未打开文件）",
            foreground="gray", font=FONT_MONO_SMALL)
        self._file_label.pack(anchor="w", pady=(0, 2))

        editor_wrap = ttk.Frame(right)
        editor_wrap.pack(fill=tk.BOTH, expand=True)
        self._line_numbers = tk.Text(
            editor_wrap, width=5, padx=4, pady=6,
            font=FONT_MONO, relief="flat",
            bg="#252526", fg="#858585",
            state="disabled", takefocus=False,
        )
        self._line_numbers.pack(side=tk.LEFT, fill=tk.Y)
        self._editor = tk.Text(
            editor_wrap, wrap=tk.NONE, undo=True, maxundo=200,
            font=FONT_MONO, relief="flat",
            bg="#1e1e1e", fg="#d4d4d4", insertbackground="white",
            padx=8, pady=6,
        )
        self._editor.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb = ttk.Scrollbar(editor_wrap, orient="vertical",
                            command=self._editor_yview)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        xsb = ttk.Scrollbar(right, orient="horizontal",
                             command=self._editor.xview)
        xsb.pack(fill=tk.X)
        self._editor.configure(
            xscrollcommand=xsb.set,
            yscrollcommand=lambda first, last: self._on_editor_scroll(first, last, vsb),
        )
        self._editor.tag_configure("current_line", background="#2a2d2e")
        self._editor.tag_configure("find_match", background="#725e00", foreground="white")
        self._editor.tag_configure("kw", foreground="#569cd6")
        self._editor.tag_configure("comment", foreground="#6a9955")
        self._editor.bind("<<Modified>>", self._on_modified)
        self._editor.bind("<KeyRelease>", self._update_cursor_status)
        self._editor.bind("<ButtonRelease-1>", self._update_cursor_status)
        self._editor.bind("<Control-s>", self._save_shortcut)
        self._editor.bind("<Control-S>", self._save_shortcut)
        self._editor.bind("<Control-f>", self._open_find)
        self._editor.bind("<Control-F>", self._open_find)
        self._editor.bind("<Tab>", self._insert_tab)

        # 底部按钮
        btns = ttk.Frame(self)
        btns.pack(fill=tk.X, padx=8, pady=(4, 8))
        self._save_btn = ttk.Button(
            btns, text="💾 保存到板子",
            command=self._save, state="disabled")
        self._save_btn.pack(side=tk.LEFT, padx=(0, 6))
        self._dl_btn = ttk.Button(
            btns, text="⬇ 下载到本地",
            command=self._download, state="disabled")
        self._dl_btn.pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(
            btns, text="📄 新建文件",
            command=self._new_file).pack(side=tk.LEFT, padx=(0, 6))
        self._st = ttk.Label(btns, text="", foreground="gray", font=FONT_UI)
        self._st.pack(side=tk.LEFT, padx=8)
        self._cursor_st = ttk.Label(btns, text="Ln 1, Col 1", foreground="gray", font=FONT_UI)
        self._cursor_st.pack(side=tk.RIGHT, padx=8)

    # ── 目录导航 ──────────────────────────────────────────────────────────────

    def _navigate(self, path):
        self._cwd = path.rstrip("/") or "/"
        self._path_var.set(self._cwd)
        self._refresh()

    def _up(self):
        parts = self._cwd.rstrip("/").rsplit("/", 1)
        parent = parts[0] if (len(parts) > 1 and parts[0]) else "/"
        self._navigate(parent)

    def _refresh(self):
        self._lb.delete(0, tk.END)
        self._entries.clear()
        try:
            raw_entries = self._sftp.listdir_attr(self._cwd)
        except Exception as e:
            self._msg(f"列目录失败：{e}", "red")
            return
        dirs, files = [], []
        for e in raw_entries:
            (dirs if _stat.S_ISDIR(e.st_mode) else files).append(e)
        dirs.sort(key=lambda x: x.filename.lower())
        files.sort(key=lambda x: x.filename.lower())
        for d in dirs:
            self._lb.insert(tk.END, _remote_list_label("📁", d.filename, d))
            self._entries.append(("dir", d.filename))
        for f in files:
            self._lb.insert(tk.END, _remote_list_label("📄", f.filename, f))
            self._entries.append(("file", f.filename))
        self._path_var.set(self._cwd)
        self._msg(f"{len(dirs)} 个目录，{len(files)} 个文件")

    def _on_dclick(self, _=None):
        sel = self._lb.curselection()
        if not sel:
            return
        kind, name = self._entries[sel[0]]
        if kind == "dir":
            if not self._confirm_discard():
                return
            self._navigate(f"{self._cwd}/{name}")
        else:
            if not self._confirm_discard():
                return
            self._open_file(f"{self._cwd}/{name}")

    # ── 文件读写 ──────────────────────────────────────────────────────────────

    def _open_file(self, path):
        try:
            with self._sftp.open(path) as fh:
                raw = fh.read()
        except Exception as e:
            self._msg(f"读取失败：{e}", "red")
            return
        content = None
        for enc in ("utf-8", "gbk", "latin-1"):
            try:
                content = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if content is None:
            self._msg("二进制文件，无法在编辑器中显示", "orange")
            return
        self._editor.delete("1.0", tk.END)
        self._editor.insert("1.0", content)
        self._editor.edit_reset()
        self._editor.edit_modified(False)
        self._open_path = path
        self._loaded_content = content   # 记录打开时内容，保存前比对板端是否被改
        self._dirty = False
        self._file_label.config(text=path, foreground="#569cd6")
        self._save_btn.config(state="normal")
        self._dl_btn.config(state="normal")
        self._update_line_numbers()
        self._highlight_syntax()
        self._update_cursor_status()
        self._msg(f"已打开  {path.split('/')[-1]}", "green")

    def _save(self):
        if not self._open_path:
            return
        content = self._editor.get("1.0", "end-1c")
        # 覆盖检测：打开后板端文件若被别处改动，先提醒再决定是否覆盖
        try:
            with self._sftp.open(self._open_path) as fh:
                disk_raw = fh.read()
            disk_text = None
            for enc in ("utf-8", "gbk", "latin-1"):
                try:
                    disk_text = disk_raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            if disk_text is not None and disk_text != self._loaded_content:
                if not messagebox.askyesno(
                        "板端文件已变化",
                        "打开之后，板端这个文件已被其他程序改动。\n"
                        "继续保存会覆盖那些改动，确定吗？",
                        parent=self):
                    self._msg("已取消保存", "orange")
                    return
        except IOError:
            pass  # 文件可能是新建的，读不到就直接写

        try:
            with self._sftp.open(self._open_path, "w") as fh:
                fh.write(content.encode("utf-8"))
            self._loaded_content = content   # 保存成功，更新快照
            self._dirty = False
            self._editor.edit_modified(False)
            self._update_title_dirty()
            self._msg("✓ 已保存", "green")
        except Exception as e:
            self._msg(f"保存失败：{e}", "red")

    def _download(self):
        if not self._open_path:
            return
        local = filedialog.asksaveasfilename(
            initialfile=self._open_path.split("/")[-1])
        if not local:
            return
        try:
            self._sftp.get(self._open_path, local)
            self._msg(f"✓ 已下载到  {local}", "green")
        except Exception as e:
            self._msg(f"下载失败：{e}", "red")

    def _new_file(self):
        dlg = tk.Toplevel(self)
        dlg.title("新建文件")
        dlg.geometry("380x130")
        dlg.resizable(False, False)
        dlg.grab_set()
        ttk.Label(dlg, text="文件名：", font=FONT_UI).pack(padx=10, pady=(10, 2), anchor="w")
        var = tk.StringVar()
        ent = ttk.Entry(dlg, textvariable=var, width=32)
        ent.pack(padx=10)
        ent.focus_set()
        def _ok():
            name = var.get().strip()
            if not name:
                return
            path = f"{self._cwd}/{name}"
            try:
                with self._sftp.open(path, "w") as fh:
                    fh.write(b"")
                dlg.destroy()
                self._refresh()
                self._open_file(path)
            except Exception as e:
                self._msg(f"创建失败：{e}", "red")
                dlg.destroy()
        ent.bind("<Return>", lambda _: _ok())
        ttk.Button(dlg, text="创建", command=_ok).pack(pady=6)

    # ── 编辑器体验增强 ──────────────────────────────────────────────────────

    def _editor_yview(self, *args):
        self._editor.yview(*args)
        self._line_numbers.yview(*args)

    def _on_editor_scroll(self, first, last, scrollbar):
        scrollbar.set(first, last)
        self._line_numbers.yview_moveto(first)

    def _on_modified(self, _=None):
        if not self._editor.edit_modified():
            return
        self._dirty = True
        self._update_title_dirty()
        self._update_line_numbers()
        self._highlight_current_line()
        self._update_cursor_status()
        self._schedule_highlight()
        self._editor.edit_modified(False)

    def _update_title_dirty(self):
        if not self._open_path:
            self._file_label.config(text="（未打开文件）", foreground="gray")
            return
        mark = "* " if self._dirty else ""
        self._file_label.config(text=f"{mark}{self._open_path}", foreground="#569cd6")

    def _update_line_numbers(self):
        end_line = int(self._editor.index("end-1c").split(".")[0])
        numbers = "\n".join(str(i) for i in range(1, end_line + 1))
        self._line_numbers.config(state="normal")
        self._line_numbers.delete("1.0", tk.END)
        self._line_numbers.insert("1.0", numbers)
        self._line_numbers.config(state="disabled")

    def _highlight_current_line(self, _=None):
        self._editor.tag_remove("current_line", "1.0", tk.END)
        line = self._editor.index(tk.INSERT).split(".")[0]
        self._editor.tag_add("current_line", f"{line}.0", f"{line}.0 lineend+1c")

    def _update_cursor_status(self, _=None):
        self._highlight_current_line()
        line, col = self._editor.index(tk.INSERT).split(".")
        self._cursor_st.config(text=f"Ln {line}, Col {int(col) + 1}")

    def _save_shortcut(self, _=None):
        self._save()
        return "break"

    def _insert_tab(self, _=None):
        self._editor.insert(tk.INSERT, "    ")
        return "break"

    def _open_find(self, _=None):
        if self._find_dlg and self._find_dlg.winfo_exists():
            self._find_dlg.lift()
            self._find_var_entry.focus_set()
            return "break"
        dlg = tk.Toplevel(self)
        dlg.title("查找")
        dlg.geometry("420x96")
        dlg.resizable(False, False)
        self._find_dlg = dlg
        frame = ttk.Frame(dlg)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        ttk.Label(frame, text="查找：", font=FONT_UI).grid(row=0, column=0, sticky="e")
        self._find_var = tk.StringVar()
        self._find_var_entry = ttk.Entry(frame, textvariable=self._find_var, width=28)
        self._find_var_entry.grid(row=0, column=1, columnspan=3, sticky="ew", padx=(4, 0))
        ttk.Button(frame, text="上一个", command=lambda: self._find_next(backward=True)).grid(row=1, column=1, pady=8)
        ttk.Button(frame, text="下一个", command=self._find_next).grid(row=1, column=2, pady=8, padx=4)
        ttk.Button(frame, text="关闭", command=dlg.destroy).grid(row=1, column=3, pady=8)
        frame.columnconfigure(1, weight=1)
        self._find_var_entry.bind("<Return>", lambda _: self._find_next())
        self._find_var_entry.focus_set()
        return "break"

    def _find_next(self, backward=False):
        pattern = self._find_var.get()
        if not pattern:
            return
        self._editor.tag_remove("find_match", "1.0", tk.END)
        start = self._editor.index(tk.INSERT)
        if backward:
            idx = self._editor.search(pattern, start, backwards=True, stopindex="1.0", nocase=True)
        else:
            idx = self._editor.search(pattern, start + "+1c", stopindex=tk.END, nocase=True)
            if not idx:
                idx = self._editor.search(pattern, "1.0", stopindex=tk.END, nocase=True)
        if not idx:
            self._msg("未找到匹配内容", "orange")
            return
        end = f"{idx}+{len(pattern)}c"
        self._editor.tag_add("find_match", idx, end)
        self._editor.mark_set(tk.INSERT, end)
        self._editor.see(idx)
        self._update_cursor_status()

    def _schedule_highlight(self):
        if self._highlight_job:
            self.after_cancel(self._highlight_job)
        self._highlight_job = self.after(350, self._highlight_syntax)

    def _highlight_syntax(self):
        self._highlight_job = None
        text = self._editor.get("1.0", "end-1c")
        if len(text) > 200000:
            self._msg("文件较大，已关闭语法高亮（不影响编辑/保存）", "#888888")
            return
        self._editor.tag_remove("kw", "1.0", tk.END)
        self._editor.tag_remove("comment", "1.0", tk.END)
        suffix = (self._open_path or "").rsplit(".", 1)[-1].lower()
        keywords = {
            "py": ["def", "class", "import", "from", "return", "if", "elif", "else", "for", "while", "try", "except", "with"],
            "cpp": ["class", "template", "typename", "return", "if", "else", "for", "while", "auto", "const", "void", "int", "__global__"],
            "h": ["class", "template", "typename", "return", "if", "else", "for", "while", "auto", "const", "void", "int"],
            "hpp": ["class", "template", "typename", "return", "if", "else", "for", "while", "auto", "const", "void", "int"],
            "sh": ["if", "then", "else", "fi", "for", "do", "done", "case", "esac", "function", "export"],
        }.get(suffix, [])
        for word in keywords:
            self._tag_word(word)
        if suffix == "py":
            self._tag_python_triple_comments(text)
        if suffix in ("cpp", "h", "hpp"):
            self._tag_block_comments(text, "/*", "*/")
        line_mark = "#" if suffix in ("py", "sh", "md") else "//"
        for line_no, line in enumerate(text.splitlines(), 1):
            pos = self._line_comment_pos(line, line_mark)
            if pos >= 0:
                self._editor.tag_add("comment", f"{line_no}.{pos}", f"{line_no}.0 lineend")

    @staticmethod
    def _line_comment_pos(line, mark):
        """返回行内注释标记的位置；忽略引号字符串内的标记。找不到返回 -1。"""
        in_str = None
        i, n, mlen = 0, len(line), len(mark)
        while i < n:
            ch = line[i]
            if in_str:
                if ch == "\\":
                    i += 2
                    continue
                if ch == in_str:
                    in_str = None
            elif ch in ("'", '"'):
                in_str = ch
            elif line[i:i + mlen] == mark:
                return i
            i += 1
        return -1

    def _tag_block_comments(self, text, open_mark, close_mark):
        """标记 /* ... */ 块注释（可跨行）。"""
        start = 0
        while True:
            begin = text.find(open_mark, start)
            if begin < 0:
                break
            close = text.find(close_mark, begin + len(open_mark))
            end = len(text) if close < 0 else close + len(close_mark)
            self._editor.tag_add("comment",
                                 self._offset_to_index(text, begin),
                                 self._offset_to_index(text, end))
            start = end

    def _tag_python_triple_comments(self, text):
        for marker in ('"""', "'''"):
            start = 0
            while True:
                begin = text.find(marker, start)
                if begin < 0:
                    break
                close = text.find(marker, begin + len(marker))
                end = len(text) if close < 0 else close + len(marker)
                self._editor.tag_add("comment", self._offset_to_index(text, begin), self._offset_to_index(text, end))
                start = end

    def _offset_to_index(self, text, offset):
        line = text.count("\n", 0, offset) + 1
        last_break = text.rfind("\n", 0, offset)
        column = offset if last_break < 0 else offset - last_break - 1
        return f"{line}.{column}"

    def _tag_word(self, word):
        start = "1.0"
        while True:
            idx = self._editor.search(word, start, stopindex=tk.END)
            if not idx:
                break
            end = f"{idx}+{len(word)}c"
            before = self._editor.get(f"{idx}-1c", idx)
            after = self._editor.get(end, f"{end}+1c")
            if not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_"):
                self._editor.tag_add("kw", idx, end)
            start = end

    def _msg(self, text, color="gray"):
        self._st.config(text=text, foreground=color)


class RemotePathPicker(tk.Toplevel):
    """轻量板端路径选择器，用 SFTP 把选中的目录/文件回填到命令表单。"""

    def __init__(self, parent, ssh_client, start_path, mode="dir", on_select=None):
        super().__init__(parent)
        self.title("选择板端路径")
        self.geometry("860x560")
        self.minsize(680, 420)
        self._sftp = ssh_client.open_sftp()
        self._mode = mode
        self._on_select_cb = on_select
        self._entries = []
        self._cwd = self._starting_dir(start_path)
        self._build()
        self._refresh()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        try:
            self._sftp.close()
        except Exception:
            pass
        self.destroy()

    def _starting_dir(self, path):
        raw = (path or "").strip()
        if not raw.startswith("/"):
            return "/home/HwHiAiUser/work"
        try:
            st = self._sftp.stat(raw)
            if _stat.S_ISDIR(st.st_mode):
                return raw.rstrip("/") or "/"
        except Exception:
            pass
        parent = raw.rsplit("/", 1)[0]
        return parent if parent else "/"

    def _build(self):
        nav = ttk.Frame(self)
        nav.pack(fill=tk.X, padx=10, pady=(10, 6))
        ttk.Label(nav, text="板端路径：", font=FONT_UI).pack(side=tk.LEFT)
        self._path_var = tk.StringVar(value=self._cwd)
        entry = ttk.Entry(nav, textvariable=self._path_var)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 6))
        entry.bind("<Return>", lambda _: self._navigate(self._path_var.get().strip()))
        ttk.Button(nav, text="上级", width=6, command=self._up).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(nav, text="刷新", width=6, command=self._refresh).pack(side=tk.LEFT)

        body = ttk.Frame(self)
        body.pack(fill=tk.BOTH, expand=True, padx=10)
        self._lb = tk.Listbox(
            body, selectmode="single", font=FONT_MONO,
            activestyle="none", bg="#252526", fg="#cccccc",
            selectbackground="#094771", selectforeground="white",
            relief="flat",
        )
        vsb = ttk.Scrollbar(body, orient="vertical", command=self._lb.yview)
        self._lb.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._lb.pack(fill=tk.BOTH, expand=True)
        self._lb.bind("<Double-Button-1>", self._on_dclick)
        self._lb.bind("<Return>", self._on_dclick)

        btns = ttk.Frame(self)
        btns.pack(fill=tk.X, padx=10, pady=10)
        if self._mode == "dir":
            ttk.Button(btns, text="选择当前目录", command=self._choose_current).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btns, text="选择选中项", command=self._choose_selected).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btns, text="取消", command=self._on_close).pack(side=tk.RIGHT)
        self._st = ttk.Label(btns, text="", foreground="gray", font=FONT_UI)
        self._st.pack(side=tk.LEFT, padx=8)

    def _navigate(self, path):
        if not path:
            return
        self._cwd = path.rstrip("/") or "/"
        self._path_var.set(self._cwd)
        self._refresh()

    def _up(self):
        parent = self._cwd.rstrip("/").rsplit("/", 1)[0]
        self._navigate(parent if parent else "/")

    def _refresh(self):
        self._lb.delete(0, tk.END)
        self._entries.clear()
        try:
            raw_entries = self._sftp.listdir_attr(self._cwd)
        except Exception as e:
            self._msg(f"列目录失败：{e}", "red")
            return
        dirs, files = [], []
        for e in raw_entries:
            (dirs if _stat.S_ISDIR(e.st_mode) else files).append(e)
        dirs.sort(key=lambda x: x.filename.lower())
        files.sort(key=lambda x: x.filename.lower())
        for d in dirs:
            self._lb.insert(tk.END, _remote_list_label("📁", d.filename, d))
            self._entries.append(("dir", d.filename))
        for f in files:
            self._lb.insert(tk.END, _remote_list_label("📄", f.filename, f))
            self._entries.append(("file", f.filename))
        self._path_var.set(self._cwd)
        self._msg(f"{len(dirs)} 个目录，{len(files)} 个文件")

    def _on_dclick(self, _=None):
        sel = self._lb.curselection()
        if not sel:
            return
        kind, name = self._entries[sel[0]]
        path = self._join_remote(self._cwd, name)
        if kind == "dir":
            if self._mode == "dir":
                self._navigate(path)
            else:
                self._navigate(path)
            return
        if self._mode == "file":
            self._select(path)
        else:
            self._msg("这是文件；当前字段需要选择目录", "orange")

    def _choose_current(self):
        self._select(self._cwd)

    def _choose_selected(self):
        sel = self._lb.curselection()
        if not sel:
            self._msg("请先点选一个目录或文件", "orange")
            return
        kind, name = self._entries[sel[0]]
        if self._mode == "file" and kind != "file":
            self._msg("当前字段需要选择文件", "orange")
            return
        self._select(self._join_remote(self._cwd, name))

    def _select(self, path):
        if self._on_select_cb:
            self._on_select_cb(path)
        self._on_close()

    def _join_remote(self, base, name):
        return f"/{name}" if base == "/" else f"{base.rstrip('/')}/{name}"

    def _msg(self, text, color="gray"):
        self._st.config(text=text, foreground=color)


# ── 主界面 ────────────────────────────────────────────────────────────────────

class CANNToolbox:
    def __init__(self, root):
        self.root = root
        self.root.title("CANN 工具箱")
        self.root.geometry("1180x760")
        self.root.minsize(980, 620)
        self._config = load_toolbox_config()
        self._configure_fonts()
        self._item_map   = {}
        self._field_vars = {}
        self._field_defs = []
        self._current    = None
        self._ssh        = None
        self._connecting = False
        self._connect_seq = 0
        self._connect_lock = threading.Lock()
        self._pending_connect_ssh = None
        self._active_channel = None
        self._running_board_command = False
        self._run_output_chunks = []
        self._build()

    def _configure_fonts(self):
        style = ttk.Style(self.root)
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont",
                     "TkHeadingFont", "TkCaptionFont", "TkSmallCaptionFont",
                     "TkIconFont", "TkTooltipFont"):
            try:
                font = tkfont.nametofont(name)
                font.configure(family="Microsoft YaHei UI", size=11)
            except Exception:
                pass
        try:
            tkfont.nametofont("TkFixedFont").configure(family="Consolas", size=12)
        except Exception:
            pass
        style.configure("Treeview", font=FONT_UI, rowheight=30)
        style.configure("Treeview.Heading", font=FONT_UI_BOLD)
        style.configure("TLabel", font=FONT_UI)
        style.configure("TButton", font=FONT_UI)
        style.configure("TCheckbutton", font=FONT_UI)
        style.configure("TCombobox", font=FONT_UI)
        style.configure("TLabelframe.Label", font=FONT_UI_BOLD)

    # ── 界面构建 ──────────────────────────────────────────────────────────────

    def _build(self):
        # 顶部：标题 + SSH 连接栏
        top = ttk.Frame(self.root)
        top.pack(fill=tk.X, padx=10, pady=(8, 0))
        ttk.Label(top, text="CANN 工具箱",
                  font=FONT_TITLE).pack(side=tk.LEFT)

        # SSH 状态区（右对齐）
        ssh_bar = ttk.Frame(top)
        ssh_bar.pack(side=tk.RIGHT)
        board = self._config.get("board", {})
        ttk.Label(ssh_bar, text="IP").pack(side=tk.LEFT, padx=(0, 2))
        self._host_var = tk.StringVar(value=board.get("host", "192.168.0.2"))
        ttk.Entry(ssh_bar, textvariable=self._host_var, width=13).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Label(ssh_bar, text="端口").pack(side=tk.LEFT, padx=(0, 2))
        self._port_var = tk.StringVar(value=str(board.get("port", 22)))
        ttk.Entry(ssh_bar, textvariable=self._port_var, width=5).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Label(ssh_bar, text="用户").pack(side=tk.LEFT, padx=(0, 2))
        self._user_var = tk.StringVar(value=board.get("user", "HwHiAiUser"))
        ttk.Entry(ssh_bar, textvariable=self._user_var, width=11).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Label(ssh_bar, text="密码").pack(side=tk.LEFT, padx=(0, 2))
        remember_password = bool(board.get("remember_password", True))
        self._pass_var = tk.StringVar(value=board.get("password", "") if remember_password else "")
        ttk.Entry(ssh_bar, textvariable=self._pass_var, show="*", width=10).pack(side=tk.LEFT, padx=(0, 4))
        self._remember_pass_var = tk.BooleanVar(value=remember_password)
        ttk.Checkbutton(
            ssh_bar, text="记住密码",
            variable=self._remember_pass_var,
        ).pack(side=tk.LEFT, padx=(0, 4))
        for var in (self._host_var, self._port_var, self._user_var):
            var.trace_add("write", lambda *_: self._refresh_cmd())
        ttk.Button(
            ssh_bar, text="保存配置",
            command=self._save_connection_config, width=9,
        ).pack(side=tk.LEFT, padx=(0, 8))
        self._conn_label = ttk.Label(
            ssh_bar, text="● 未连接",
            foreground="gray", font=FONT_UI_BOLD)
        self._conn_label.pack(side=tk.LEFT, padx=(0, 8))
        self._conn_btn = ttk.Button(
            ssh_bar, text="连接板子",
            command=self._toggle_ssh, width=9)
        self._conn_btn.pack(side=tk.LEFT, padx=(0, 4))
        # 文件管理器按钮（连接后才可用）
        self._filemgr_btn = ttk.Button(
            ssh_bar, text="📁 文件管理器",
            command=self._open_file_browser, width=12,
            state="disabled")
        self._filemgr_btn.pack(side=tk.LEFT)
        if not HAS_PARAMIKO:
            ttk.Label(ssh_bar, text="（需 pip install paramiko）",
                      foreground="red", font=FONT_UI).pack(side=tk.LEFT, padx=4)

        ttk.Separator(self.root).pack(fill=tk.X, padx=10, pady=5)

        # 底部按钮栏：先于主区域打包并钉在底部，窗口不够高时被压缩的是主区域而不是按钮
        btns = ttk.Frame(self.root)
        btns.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(0, 8))
        ttk.Button(btns, text="📋 复制命令",
                   command=self._copy).pack(side=tk.LEFT, padx=(0, 6))
        self._local_btn = ttk.Button(btns, text="▶ 本地执行",
                                     command=self._run_local)
        self._local_btn.pack(side=tk.LEFT, padx=(0, 6))
        self._board_btn = ttk.Button(btns, text="🔌 发送到板子",
                                     command=self._run_board, state="disabled")
        self._board_btn.pack(side=tk.LEFT, padx=(0, 6))
        self._stop_btn = ttk.Button(btns, text="■ 停止板端命令",
                                    command=self._stop_board_command, state="disabled")
        self._stop_btn.pack(side=tk.LEFT)
        self._status = ttk.Label(btns, text="", foreground="gray")
        self._status.pack(side=tk.LEFT, padx=12)

        # 主体分栏
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 4))

        # 左栏：工具树
        left = ttk.Frame(paned, width=205)
        paned.add(left, weight=1)
        ttk.Label(left, text="工具 / 功能", font=FONT_UI_BOLD).pack(anchor="w")
        self.tree = ttk.Treeview(left, show="tree", selectmode="browse")
        vsb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        for group in TOOLS:
            gid = self.tree.insert("", "end", text=group["group"], open=True)
            for item in group["items"]:
                iid = self.tree.insert(gid, "end", text="   " + item["name"])
                self._item_map[iid] = item

        # 右栏
        right = ttk.Frame(paned)
        paned.add(right, weight=3)

        desc_row = ttk.Frame(right)
        desc_row.pack(fill=tk.X, pady=(0, 4))
        self._badge = ttk.Label(desc_row, text="", font=FONT_UI_BOLD, width=12)
        self._badge.pack(side=tk.LEFT)
        self._desc = ttk.Label(
            desc_row, text="← 从左侧选择一个功能",
            foreground="gray", wraplength=760, justify="left")
        self._desc.pack(side=tk.LEFT, fill=tk.X, expand=True)
        desc_row.bind("<Configure>", self._on_desc_row_configure)

        self._fields_outer = ttk.LabelFrame(right, text="参数")
        self._fields_outer.pack(fill=tk.BOTH, expand=True, pady=(0, 4))
        self._fields_canvas = tk.Canvas(
            self._fields_outer, height=200, highlightthickness=0)
        fields_vsb = ttk.Scrollbar(
            self._fields_outer, orient="vertical",
            command=self._fields_canvas.yview)
        self._fields_frame = ttk.Frame(self._fields_canvas)
        self._fields_window = self._fields_canvas.create_window(
            (0, 0), window=self._fields_frame, anchor="nw")
        self._fields_canvas.configure(yscrollcommand=fields_vsb.set)
        self._fields_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        fields_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._fields_frame.bind("<Configure>", self._on_fields_configure)
        self._fields_canvas.bind("<Configure>", self._on_fields_canvas_configure)
        self._fields_canvas.bind("<Enter>", self._bind_fields_mousewheel)
        self._fields_canvas.bind("<Leave>", self._unbind_fields_mousewheel)

        cmd_bar = ttk.Frame(right)
        cmd_bar.pack(fill=tk.X, pady=(0, 2))
        ttk.Label(cmd_bar, text="生成的命令（可手动修改）",
                  font=FONT_UI_BOLD).pack(side=tk.LEFT)
        self._cmd_toggle_btn = ttk.Button(
            cmd_bar, text="隐藏命令",
            command=self._toggle_command, width=9)
        self._cmd_toggle_btn.pack(side=tk.RIGHT)
        self._cmd_visible = True

        self._cmd_lf = ttk.LabelFrame(right, text="")
        self._cmd_lf.pack(fill=tk.X, pady=(0, 4))
        self._cmd = tk.Text(
            self._cmd_lf, height=4, wrap=tk.WORD,
            font=FONT_MONO_SMALL, relief="flat", bg="#f5f5f5",
            padx=8, pady=6)
        self._cmd.pack(fill=tk.X, padx=4, pady=4)

        out_bar = ttk.Frame(right)
        out_bar.pack(fill=tk.X, pady=(0, 2))
        ttk.Label(out_bar, text="执行输出", font=FONT_UI_BOLD).pack(side=tk.LEFT)
        ttk.Button(
            out_bar, text="清空输出",
            command=self._clear_output, width=9).pack(side=tk.RIGHT, padx=(4, 0))
        self._output_toggle_btn = ttk.Button(
            out_bar, text="折叠输出",
            command=self._toggle_output, width=9)
        self._output_toggle_btn.pack(side=tk.RIGHT)
        self._output_visible = True

        self._output_lf = ttk.LabelFrame(right, text="")
        self._output_lf.pack(fill=tk.BOTH, expand=True, pady=(0, 4))
        self._output = scrolledtext.ScrolledText(
            self._output_lf, height=5, wrap=tk.WORD,
            font=FONT_MONO_SMALL, relief="flat",
            bg="#1e1e1e", fg="#d4d4d4", insertbackground="white",
            padx=8, pady=6)
        self._output.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self._output.insert(tk.END, "输出将显示在这里...\n")
        self._output.config(state="disabled")

        self._summary_lf = ttk.LabelFrame(right, text="问题摘要")
        self._summary_lf.pack(fill=tk.X, pady=(0, 4))
        self._summary = scrolledtext.ScrolledText(
            self._summary_lf, height=3, wrap=tk.WORD,
            font=FONT_UI, relief="flat",
            bg="#fff8e1", fg="#333333",
            padx=8, pady=6)
        self._summary.pack(fill=tk.X, padx=4, pady=4)
        self._summary.insert(tk.END, "命令结束后会在这里提取关键报错和可能原因。\n")
        self._summary.config(state="disabled")

    # ── SSH 连接管理 ──────────────────────────────────────────────────────────

    def _current_board_config(self):
        host = self._host_var.get().strip()
        user = self._user_var.get().strip()
        try:
            port = int(self._port_var.get().strip() or "22")
        except ValueError:
            port = 22
        default_remote_dir = self._config.get("board", {}).get(
            "default_remote_dir", f"/home/{user}/work")
        return {
            "host": host,
            "port": port,
            "user": user,
            "password": self._pass_var.get(),
            "remember_password": bool(self._remember_pass_var.get()),
            "default_remote_dir": default_remote_dir,
        }

    def _template_values(self):
        values = {
            "board_host": self._host_var.get().strip() if hasattr(self, "_host_var") else "",
            "board_user": self._user_var.get().strip() if hasattr(self, "_user_var") else "",
            "board_port": self._port_var.get().strip() if hasattr(self, "_port_var") else "22",
            "cann_path": config_cann_path(self._config),
            "cann_env": config_cann_env(self._config),
            "workspace": LOCAL_ROOT,
            "toolbox": str(APP_DIR).replace("\\", "/"),
            "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
        }
        values.update(self._config.get("paths", {}))
        return values

    def _expand_field_values(self, values):
        expanded = dict(values)
        raw_input = str(expanded.get("input", "")).strip()
        if raw_input:
            input_path = Path(raw_input)
            input_dir = input_path if input_path.suffix == "" else input_path.parent
            expanded["input_dir"] = str(input_dir).replace("\\", "/")
            expanded["input_name"] = input_path.name
            expanded["input_stem"] = input_path.stem or input_path.name
        else:
            expanded.setdefault("input_dir", "")
            expanded.setdefault("input_name", "")
            expanded.setdefault("input_stem", "")
        for _ in range(3):
            changed = False
            for key, value in list(expanded.items()):
                if not isinstance(value, str) or "{" not in value:
                    continue
                try:
                    new_value = value.format(**expanded)
                except KeyError:
                    continue
                if new_value != value:
                    expanded[key] = new_value
                    changed = True
            if not changed:
                break
        return expanded

    def _save_connection_config(self):
        board = self._current_board_config()
        if not board["host"] or not board["user"]:
            self._flash("IP 和用户名不能为空", "red")
            return
        self._config = _deep_merge(self._config, {
            "board": {
                "host": board["host"],
                "port": board["port"],
                "user": board["user"],
                "password": board["password"] if board["remember_password"] else "",
                "remember_password": board["remember_password"],
                "default_remote_dir": board["default_remote_dir"],
            }
        })
        try:
            save_toolbox_config(self._config)
            self._flash("✓ 已保存连接配置（不保存密码）", "green")
            self._refresh_cmd()
        except Exception as e:
            self._flash(f"保存失败：{e}", "red")

    def _toggle_ssh(self):
        if self._connecting:
            self._cancel_connect()
        elif self._ssh:
            self._disconnect()
        else:
            self._connect()

    def _connect(self):
        if not HAS_PARAMIKO:
            self._flash("请先运行：pip install paramiko", "red")
            return
        board = self._current_board_config()
        if not board["host"] or not board["user"]:
            self._flash("IP 和用户名不能为空", "red")
            return
        if not board["password"]:
            self._flash("请输入板端密码（不会保存）", "red")
            return
        with self._connect_lock:
            self._connect_seq += 1
            seq = self._connect_seq
            self._connecting = True
            self._pending_connect_ssh = None
        self._conn_label.config(text="● 连接中...", foreground="orange")
        self._conn_btn.config(text="取消连接", state="normal")
        self._filemgr_btn.config(state="disabled")
        self._append_output(f"[SSH] 正在连接 {board['user']}@{board['host']}:{board['port']}...\n")
        threading.Thread(target=self._do_connect, args=(board, seq), daemon=True).start()

    def _is_current_connect(self, seq):
        with self._connect_lock:
            return self._connecting and seq == self._connect_seq

    def _do_connect(self, board, seq):
        ssh = None
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            with self._connect_lock:
                if seq != self._connect_seq or not self._connecting:
                    return
                self._pending_connect_ssh = ssh
            ssh.connect(
                board["host"],
                port=board["port"],
                username=board["user"],
                password=board["password"],
                timeout=10,
                auth_timeout=10,
                banner_timeout=10,
            )
            if not self._is_current_connect(seq):
                try:
                    ssh.close()
                except Exception:
                    pass
                return
            with self._connect_lock:
                if seq == self._connect_seq:
                    self._pending_connect_ssh = None
            self.root.after(0, lambda s=ssh: self._on_connected(board, s, seq))
        except Exception as e:
            if self._is_current_connect(seq):
                self.root.after(0, lambda: self._on_connect_fail(str(e), seq))
            else:
                try:
                    if ssh:
                        ssh.close()
                except Exception:
                    pass

    def _on_connected(self, board, ssh, seq):
        if not self._is_current_connect(seq):
            try:
                ssh.close()
            except Exception:
                pass
            return
        with self._connect_lock:
            self._connecting = False
            self._pending_connect_ssh = None
        self._ssh = ssh
        self._conn_label.config(text=f"● 已连接 {board['host']}", foreground="green")
        self._conn_btn.config(text="断开", state="normal")
        self._filemgr_btn.config(state="normal")
        self._update_buttons()
        self._append_output(f"[SSH] 已连接到 {board['user']}@{board['host']}:{board['port']}\n")

    def _on_connect_fail(self, err, seq=None):
        if seq is not None and not self._is_current_connect(seq):
            return
        with self._connect_lock:
            self._connecting = False
            self._pending_connect_ssh = None
        self._conn_label.config(text="● 连接失败", foreground="red")
        self._conn_btn.config(text="连接板子", state="normal")
        self._append_output(f"[SSH] 连接失败：{err}\n")

    def _cancel_connect(self):
        with self._connect_lock:
            if not self._connecting:
                return
            self._connect_seq += 1
            self._connecting = False
            pending = self._pending_connect_ssh
            self._pending_connect_ssh = None
        if pending:
            try:
                pending.close()
            except Exception:
                pass
        self._conn_label.config(text="● 已取消连接", foreground="gray")
        self._conn_btn.config(text="连接板子", state="normal")
        self._filemgr_btn.config(state="disabled")
        self._update_buttons()
        self._append_output("[SSH] 已取消本次连接请求\n")

    def _disconnect(self):
        if self._connecting:
            self._cancel_connect()
            return
        if self._ssh:
            try:
                self._ssh.close()
            except Exception:
                pass
            self._ssh = None
        self._conn_label.config(text="● 未连接", foreground="gray")
        self._conn_btn.config(text="连接板子")
        self._filemgr_btn.config(state="disabled")
        self._update_buttons()
        self._append_output("[SSH] 已断开连接\n")

    # ── 文件管理器入口 ────────────────────────────────────────────────────────

    def _open_file_browser(self):
        if not self._ssh:
            self._flash("请先连接板子", "red")
            return
        board = self._current_board_config()
        FileBrowser(
            self.root, self._ssh,
            board["host"], board["user"], board["default_remote_dir"])

    # ── 工具选择 ──────────────────────────────────────────────────────────────

    def _on_select(self, _event):
        sel = self.tree.selection()
        if not sel:
            return
        item = self._item_map.get(sel[0])
        if not item:
            return
        self._current = item
        self._desc.config(text=item.get("desc", ""), foreground="black")
        if item.get("builder"):
            self._badge.config(text="🧩 生成文件", foreground="#6a1b9a")
            self._build_builder_form(item)
        elif item.get("target") == "board":
            self._badge.config(text="🔌 板端执行", foreground="#cc6600")
            self._build_fields(item)
        else:
            self._badge.config(text="🖥 本机执行", foreground="#007700")
            self._build_fields(item)
        self._update_buttons()

    def _update_buttons(self):
        if not self._current:
            return
        if self._running_board_command:
            self._local_btn.config(state="disabled")
            self._board_btn.config(state="disabled")
            self._stop_btn.config(state="normal")
            return
        self._stop_btn.config(state="disabled")
        if self._current.get("builder"):
            # 生成器不执行命令，复制/保存在表单内完成
            self._local_btn.config(state="disabled")
            self._board_btn.config(state="disabled")
            return
        is_board  = self._current.get("target") == "board"
        connected = self._ssh is not None
        self._local_btn.config(state="disabled" if is_board else "normal")
        self._board_btn.config(
            state="normal" if (is_board and connected) else "disabled")

    def _on_desc_row_configure(self, event):
        try:
            badge_width = self._badge.winfo_width()
            wrap = max(520, event.width - badge_width - 24)
            self._desc.configure(wraplength=wrap)
        except Exception:
            pass

    # ── 参数表单 ──────────────────────────────────────────────────────────────

    def _on_fields_configure(self, _event=None):
        self._fields_canvas.configure(
            scrollregion=self._fields_canvas.bbox("all"))

    def _on_fields_canvas_configure(self, event):
        self._fields_canvas.itemconfigure(self._fields_window, width=event.width)

    def _bind_fields_mousewheel(self, _event=None):
        self._fields_canvas.bind_all("<MouseWheel>", self._on_fields_mousewheel)

    def _unbind_fields_mousewheel(self, _event=None):
        self._fields_canvas.unbind_all("<MouseWheel>")

    def _on_fields_mousewheel(self, event):
        self._fields_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _toggle_output(self):
        if self._output_visible:
            self._output_lf.pack_forget()
            self._output_toggle_btn.config(text="展开输出")
            self._output_visible = False
        else:
            self._output_lf.pack(fill=tk.BOTH, expand=True, pady=(0, 4), after=self._output_toggle_btn.master)
            self._output_toggle_btn.config(text="折叠输出")
            self._output_visible = True

    def _toggle_command(self):
        if self._cmd_visible:
            self._cmd_lf.pack_forget()
            self._cmd_toggle_btn.config(text="显示命令")
            self._cmd_visible = False
        else:
            self._cmd_lf.pack(fill=tk.X, pady=(0, 4), after=self._cmd_toggle_btn.master)
            self._cmd_toggle_btn.config(text="隐藏命令")
            self._cmd_visible = True

    def _is_remote_path_field(self, item, field):
        if field.get("remote"):
            return True
        if field.get("type") != "text":
            return False
        key = field.get("key", "")
        if key == "remote":
            return True
        if item.get("target") != "board":
            return False
        remote_keys = {
            "path", "workdir", "json", "output", "project", "build_out", "run_pkg",
            "install_dir", "op_host_cpp", "output_dir", "model_path", "opp_dir",
            "case_json", "dump_dir", "app", "script", "op_type_file", "profile_dir",
            "report_dir", "kpp_dir", "src_dir", "dst_dir", "config_file",
            "relocatable_file",
        }
        return key in remote_keys

    def _remote_path_mode(self, field):
        file_keys = {
            "json", "run_pkg", "op_host_cpp", "model_path", "case_json", "app",
            "script", "op_type_file", "config_file", "relocatable_file",
        }
        return "file" if field.get("key") in file_keys else "dir"

    def _build_fields(self, item):
        for w in self._fields_frame.winfo_children():
            w.destroy()
        self._field_vars = {}
        self._field_defs = item.get("fields", [])
        self._case_list_rows   = {}   # key → list of {dir/elements/blockdim/label: StringVar}
        self._case_list_frames = {}   # key → container Frame
        fields = item.get("fields", [])
        if not fields:
            ttk.Label(self._fields_frame, text="此功能无需额外参数",
                      foreground="gray").grid(row=0, column=0, padx=10, pady=6)
            self._fields_canvas.yview_moveto(0)
            self._refresh_cmd()
            return
        for i, f in enumerate(fields):
            if f["type"] == "note":
                ttk.Label(
                    self._fields_frame,
                    text=f["text"],
                    foreground=f.get("foreground", "#666666"),
                    wraplength=760,
                    justify="left",
                ).grid(row=i, column=0, columnspan=3,
                       padx=10, pady=(4, 6), sticky="w")
                continue
            if f["type"] == "check":
                var = tk.BooleanVar(value=bool(f.get("default", False)))
            else:
                default = f.get("default", "")
                if isinstance(default, str):
                    try:
                        default = default.format(**self._template_values())
                    except KeyError:
                        pass
                default = _combo_display_value(f, default)
                var = tk.StringVar(value=default)
            var.trace_add("write", lambda *_: self._refresh_cmd())
            self._field_vars[f["key"]] = var
            if f["type"] == "check":
                ttk.Checkbutton(
                    self._fields_frame, text=f["label"],
                    variable=var,
                ).grid(row=i, column=0, columnspan=3,
                       padx=10, pady=3, sticky="w")
                continue

            label = ("必填｜" if f.get("required") else "") + f["label"] + " :"
            _form_label(
                self._fields_frame,
                label,
                required=f.get("required"),
            ).grid(row=i, column=0, padx=(10, 4),
                   pady=3, sticky="ne")
            if f["type"] == "combo":
                ttk.Combobox(
                    self._fields_frame, textvariable=var,
                    values=_combo_display_options(f), width=50,
                ).grid(row=i, column=1, columnspan=2,
                       padx=4, pady=3, sticky="ew")
            elif f["type"] in ("file", "dir"):
                ttk.Entry(
                    self._fields_frame, textvariable=var, width=44,
                ).grid(row=i, column=1, padx=4, pady=3, sticky="ew")
                ft = f["type"]
                ttk.Button(
                    self._fields_frame, text="浏览", width=5,
                    command=lambda v=var, t=ft: self._browse(v, t),
                ).grid(row=i, column=2, padx=(0, 8), pady=3)
            elif self._is_remote_path_field(item, f):
                ttk.Entry(
                    self._fields_frame, textvariable=var, width=44,
                ).grid(row=i, column=1, padx=4, pady=3, sticky="ew")
                mode = self._remote_path_mode(f)
                ttk.Button(
                    self._fields_frame, text="板端", width=5,
                    command=lambda v=var, m=mode: self._browse_remote(v, m),
                ).grid(row=i, column=2, padx=(0, 8), pady=3)
            elif f["type"] == "case_list":
                key = f["key"]
                outer = ttk.LabelFrame(self._fields_frame, text=f.get("label", "规格列表"))
                outer.grid(row=i, column=1, columnspan=2, padx=4, pady=6, sticky="ew")
                self._case_list_frames[key] = outer
                rows_data = self._case_list_rows.setdefault(key, [])
                for rd in f.get("default_rows", [{}]):
                    try:
                        rd_resolved = {k: (v.format(**self._template_values())
                                          if isinstance(v, str) else v)
                                       for k, v in rd.items()}
                    except KeyError:
                        rd_resolved = rd
                    row_vars = {
                        "dir":      tk.StringVar(value=rd_resolved.get("dir", "")),
                        "elements": tk.StringVar(value=rd_resolved.get("elements", "")),
                        "blockdim": tk.StringVar(value=rd_resolved.get("blockdim", "1")),
                        "label":    tk.StringVar(value=rd_resolved.get("label", "")),
                    }
                    for v in row_vars.values():
                        v.trace_add("write", lambda *_: self._refresh_cmd())
                    rows_data.append(row_vars)
                self._case_list_rebuild(key)
                continue
            else:
                ttk.Entry(
                    self._fields_frame, textvariable=var, width=50,
                ).grid(row=i, column=1, columnspan=2,
                       padx=4, pady=3, sticky="ew")
        self._fields_frame.columnconfigure(1, weight=1)
        self._fields_canvas.yview_moveto(0)
        self.root.after_idle(self._on_fields_configure)
        self._refresh_cmd()

    # ── case_list 动态行 ──────────────────────────────────────────────────────

    def _case_list_rebuild(self, key):
        outer = self._case_list_frames[key]
        for w in outer.winfo_children():
            w.destroy()
        # 表头
        hdr = ttk.Frame(outer)
        hdr.pack(fill=tk.X, padx=4, pady=(2, 0))
        ttk.Label(hdr, text="目录", width=42, anchor="w",
                  foreground="#555555").pack(side=tk.LEFT, padx=(2, 4), fill=tk.X, expand=True)
        for text, width in [("总像素数", 8), ("blockdim", 8), ("标签", 14)]:
            ttk.Label(hdr, text=text, width=width, anchor="w",
                      foreground="#555555").pack(side=tk.LEFT, padx=2)
        # 数据行
        rows = self._case_list_rows[key]
        for idx, row_vars in enumerate(rows):
            rf = ttk.Frame(outer)
            rf.pack(fill=tk.X, padx=4, pady=1)
            e_dir = ttk.Entry(rf, textvariable=row_vars["dir"], width=42)
            e_dir.pack(side=tk.LEFT, padx=(0, 1), fill=tk.X, expand=True)
            ttk.Button(rf, text="📁", width=3,
                       command=lambda v=row_vars["dir"]: self._browse(v, "dir")
                       ).pack(side=tk.LEFT, padx=(0, 4))
            ttk.Entry(rf, textvariable=row_vars["elements"], width=8).pack(side=tk.LEFT, padx=2)
            ttk.Entry(rf, textvariable=row_vars["blockdim"], width=6).pack(side=tk.LEFT, padx=2)
            ttk.Entry(rf, textvariable=row_vars["label"],    width=14).pack(side=tk.LEFT, padx=2)
            if len(rows) > 1:
                ttk.Button(rf, text="×", width=2,
                           command=lambda k=key, i=idx: self._case_list_del(k, i)
                           ).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(outer, text="＋ 添加规格",
                   command=lambda k=key: self._case_list_add(k)
                   ).pack(anchor="w", padx=4, pady=(4, 4))
        self.root.after_idle(self._on_fields_configure)

    def _case_list_add(self, key):
        rows = self._case_list_rows[key]
        row_vars = {
            "dir":      tk.StringVar(value=""),
            "elements": tk.StringVar(value=""),
            "blockdim": tk.StringVar(value="1"),
            "label":    tk.StringVar(value=""),
        }
        for v in row_vars.values():
            v.trace_add("write", lambda *_: self._refresh_cmd())
        rows.append(row_vars)
        self._case_list_rebuild(key)
        self._refresh_cmd()

    def _case_list_del(self, key, idx):
        rows = self._case_list_rows[key]
        if len(rows) > 1:
            rows.pop(idx)
        self._case_list_rebuild(key)
        self._refresh_cmd()

    # ── builder（文件生成器）─────────────────────────────────────────────────

    def _build_builder_form(self, item):
        # 不走命令行那套，初始化一次数据模型，再绘制
        self._field_vars = {}
        self._field_defs = []
        self._builder_spec = item.get("builder", {})
        self._builder_basic_vars = {}
        for bf in self._builder_spec.get("basic_fields", []):
            var = tk.StringVar(value=bf.get("default", ""))
            self._builder_basic_vars[bf["key"]] = var
            if bf.get("rerender_on_change"):
                var.trace_add("write", lambda *_: self._render_builder())
            else:
                var.trace_add("write", lambda *_: self._refresh_builder_json())
        # 每个可重复组先放一行默认
        self._builder_rows = {}
        for sec in self._builder_spec.get("repeat_sections", []):
            default_rows = sec.get("default_rows") or [{}]
            self._builder_rows[sec["key"]] = [
                self._new_builder_row(sec, defaults) for defaults in default_rows
            ]
        self._render_builder()

    def _new_builder_row(self, sec, defaults=None):
        defaults = defaults or {}
        row = {}
        for f in sec.get("fields", []):
            var = tk.StringVar(value=defaults.get(f["key"], f.get("default", "")))
            var.trace_add("write", lambda *_: self._refresh_builder_json())
            row[f["key"]] = var
        return row

    def _builder_field_omitted(self, f):
        cond = f.get("omit_when")
        if not cond:
            return False
        bv = self._builder_basic_vars.get(cond.get("basic"))
        return bv is not None and bv.get() == cond.get("equals")

    def _builder_field_options(self, f):
        ob = f.get("options_by")
        if ob:
            bv = self._builder_basic_vars.get(ob.get("basic"))
            key = bv.get() if bv is not None else None
            return ob.get("map", {}).get(key, f.get("options", []))
        return f.get("options", [])

    def _builder_emit_value(self, raw, f):
        emit = f.get("emit", "str")
        if emit in ("list", "list_int", "list_float"):
            parts = [x.strip() for x in raw.replace("，", ",").split(",") if x.strip()]
            if emit == "list_int":
                values = []
                for part in parts:
                    try:
                        values.append(int(part))
                    except ValueError:
                        values.append(part)
                return values
            if emit == "list_float":
                values = []
                for part in parts:
                    try:
                        values.append(float(part))
                    except ValueError:
                        values.append(part)
                return values
            return parts
        if emit == "int":
            try:
                return int(raw)
            except ValueError:
                return raw
        if emit == "float":
            try:
                return float(raw)
            except ValueError:
                return raw
        if emit == "bool":
            return raw.lower() in ("1", "true", "yes", "y", "on", "是", "需要")
        return raw

    def _render_builder(self):
        for w in self._fields_frame.winfo_children():
            w.destroy()
        self._builder_hint_labels = []  # [(var, label, hints_dict)]，每次重绘重置，避免 trace 泄漏
        spec = self._builder_spec
        r = 0
        # 顶层基本字段
        for bf in spec.get("basic_fields", []):
            var = self._builder_basic_vars[bf["key"]]
            _form_label(self._fields_frame, bf.get("label", bf["key"]) + " :").grid(
                row=r, column=0, padx=(10, 4), pady=3, sticky="e")
            if bf.get("type") == "choice":
                ttk.Combobox(self._fields_frame, textvariable=var,
                             values=self._builder_field_options(bf), state="readonly",
                             width=48).grid(row=r, column=1, columnspan=2,
                                            padx=4, pady=3, sticky="ew")
            else:
                ttk.Entry(self._fields_frame, textvariable=var, width=50).grid(
                    row=r, column=1, columnspan=2, padx=4, pady=3, sticky="ew")
            r += 1
            # 选项注释：选中后在下方显示灰字说明
            hints = bf.get("option_hints")
            if hints:
                hl = ttk.Label(self._fields_frame, text="", foreground="#6a1b9a",
                               wraplength=720, justify="left", font=FONT_UI)
                hl.grid(row=r, column=1, columnspan=2, padx=4, pady=(0, 4), sticky="w")
                self._builder_hint_labels.append((var, hl, hints))
                r += 1
        # 可重复组
        for sec in spec.get("repeat_sections", []):
            key = sec["key"]
            lf = ttk.LabelFrame(self._fields_frame, text=sec.get("label", key))
            _form_label(self._fields_frame, "", empty=True).grid(
                row=r, column=0, padx=(10, 4), pady=(8, 2), sticky="e")
            lf.grid(row=r, column=1, columnspan=2, padx=4, pady=(8, 2), sticky="ew")
            r += 1
            visible = [f for f in sec.get("fields", [])
                       if not self._builder_field_omitted(f)]
            row0 = 0
            legend = sec.get("legend")
            if legend:
                ttk.Label(lf, text=legend, foreground="#888888",
                          wraplength=700, justify="left", font=FONT_UI).grid(
                    row=0, column=0, columnspan=len(visible) + 1,
                    padx=6, pady=(2, 4), sticky="w")
                row0 = 1
            for ci, f in enumerate(visible):
                ttk.Label(lf, text=f.get("label", f["key"]),
                          font=FONT_UI).grid(row=row0, column=ci, padx=4, pady=(2, 0))
            for ri, row in enumerate(self._builder_rows.get(key, [])):
                for ci, f in enumerate(visible):
                    var = row[f["key"]]
                    if f.get("type") == "choice":
                        opts = self._builder_field_options(f)
                        if opts and var.get() not in opts:
                            var.set(opts[0])  # 模式切换后旧值非法，回退到第一个
                        ttk.Combobox(lf, textvariable=var, values=opts,
                                     state="readonly", width=12).grid(
                            row=row0 + 1 + ri, column=ci, padx=4, pady=2)
                    else:
                        ttk.Entry(lf, textvariable=var, width=14).grid(
                            row=row0 + 1 + ri, column=ci, padx=4, pady=2)
                ttk.Button(lf, text="✕", width=3,
                           command=lambda s=sec, i=ri: self._builder_del_row(s, i)
                           ).grid(row=row0 + 1 + ri, column=len(visible),
                                  padx=(2, 6), pady=2)
            ttk.Button(lf, text="➕ 加一行",
                       command=lambda s=sec: self._builder_add_row(s)).grid(
                row=row0 + 1 + len(self._builder_rows.get(key, [])), column=0,
                columnspan=2, padx=4, pady=(2, 6), sticky="w")
        # 保存/复制
        bar = ttk.Frame(self._fields_frame)
        bar.grid(row=r, column=0, columnspan=3, padx=10, pady=(8, 4), sticky="w")
        ttk.Button(bar, text="💾 保存到本地…",
                   command=self._save_builder).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(bar, text="📋 复制",
                   command=self._copy_builder).pack(side=tk.LEFT)
        self._fields_frame.columnconfigure(1, weight=1)
        self._fields_canvas.yview_moveto(0)
        self.root.after_idle(self._on_fields_configure)
        self._refresh_builder_json()

    def _builder_add_row(self, sec):
        self._builder_rows[sec["key"]].append(self._new_builder_row(sec))
        self._render_builder()

    def _builder_del_row(self, sec, index):
        rows = self._builder_rows[sec["key"]]
        if 0 <= index < len(rows):
            rows.pop(index)
        self._render_builder()

    def _refresh_builder_json(self):
        spec = getattr(self, "_builder_spec", None)
        if not spec:
            return
        # 更新选项注释
        for var, label, hints in getattr(self, "_builder_hint_labels", []):
            try:
                label.config(text=hints.get(var.get(), ""))
            except tk.TclError:
                pass
        obj = {}
        for bf in spec.get("basic_fields", []):
            if bf.get("control_only"):
                continue
            val = self._builder_basic_vars[bf["key"]].get().strip()
            if val:
                obj[bf["key"]] = self._builder_emit_value(val, bf)
        for sec in spec.get("repeat_sections", []):
            items = []
            for row in self._builder_rows.get(sec["key"], []):
                # 有 name 字段但为空的行整行跳过（避免生成无名条目）
                if "name" in row and not row["name"].get().strip():
                    continue
                d = {}
                for f in sec.get("fields", []):
                    if self._builder_field_omitted(f):
                        continue
                    raw = row[f["key"]].get().strip()
                    if not raw:
                        continue
                    d[f["key"]] = self._builder_emit_value(raw, f)
                if d:
                    items.append(d)
            if items:
                obj[sec["key"]] = items
        text = json.dumps([obj], ensure_ascii=False, indent=2)
        self._cmd.delete("1.0", tk.END)
        self._cmd.insert("1.0", text)

    def _save_builder(self):
        text = self._cmd.get("1.0", tk.END).strip()
        if not text:
            self._flash("没有可保存的内容", "red")
            return
        path = filedialog.asksaveasfilename(
            initialdir=LOCAL_ROOT, defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text + "\n")
            self._flash(f"✓ 已保存：{path}", "green")
            self._set_summary(
                f"已生成：{path}\n用上方“文件管理器 / 发送到板子”传到板端即可。\n")
        except Exception as e:
            self._flash(f"保存失败：{e}", "red")

    def _copy_builder(self):
        text = self._cmd.get("1.0", tk.END).strip()
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._flash("✓ 已复制", "green")

    def _browse(self, var, kind):
        path = (filedialog.askopenfilename() if kind == "file"
                else filedialog.askdirectory())
        if path:
            var.set(path)

    def _browse_remote(self, var, mode):
        if not self._ssh:
            self._flash("请先连接板子", "red")
            return
        board = self._current_board_config()
        start = var.get().strip() or board["default_remote_dir"]
        if not start.startswith("/"):
            start = board["default_remote_dir"]
        RemotePathPicker(
            self.root, self._ssh, start, mode=mode,
            on_select=lambda path: var.set(path),
        )

    def _refresh_cmd(self):
        if not self._current or self._current.get("builder"):
            return
        tmpl = self._current.get("template", "")
        values = {k: v.get() for k, v in self._field_vars.items()}
        for f in self._field_defs:
            key = f.get("key")
            if key in values:
                values[key] = _combo_emit_value(f, values[key])
        values.update(self._template_values())
        values = self._expand_field_values(values)
        metrics = []
        for f in self._field_defs:
            enabled_by = f.get("enabled_by")
            if enabled_by and not bool(self._field_vars.get(enabled_by, tk.BooleanVar(value=False)).get()):
                continue
            if f.get("metric") and bool(values.get(f["key"])):
                metrics.append(f["metric"])
            if f.get("metric_from_value"):
                raw = str(values.get(f["key"], "")).strip()
                if raw:
                    metrics.extend([x.strip() for x in raw.split(",") if x.strip()])
        values["metrics"] = ",".join(metrics)
        options = []
        for f in self._field_defs:
            option = f.get("option")
            if not option:
                continue
            enabled_by = f.get("enabled_by")
            if enabled_by and not bool(self._field_vars.get(enabled_by, tk.BooleanVar(value=False)).get()):
                continue
            if f.get("type") == "check" and not bool(self._field_vars[f["key"]].get()):
                continue
            if f.get("type") != "check" and not str(values.get(f["key"], "")).strip():
                continue
            try:
                options.append(option.format(**values))
            except KeyError:
                options.append(option)
        values["options"] = (" " + " ".join(options)) if options else ""
        # 前缀：拼在命令主体之前（如 create 前的 source 环境），位置由模板里的 {pre} 决定
        prefixes = []
        for f in self._field_defs:
            prefix = f.get("prefix_option")
            if not prefix:
                continue
            enabled_by = f.get("enabled_by")
            if enabled_by and not bool(self._field_vars.get(enabled_by, tk.BooleanVar(value=False)).get()):
                continue
            if f.get("type") == "check" and not bool(self._field_vars[f["key"]].get()):
                continue
            if f.get("type") != "check" and not str(values.get(f["key"], "")).strip():
                continue
            try:
                prefixes.append(prefix.format(**values))
            except KeyError:
                prefixes.append(prefix)
        values["pre"] = "".join(prefixes)
        # case_list 字段：生成 --case "dir" elements blockdim "label" 片段
        for cl_key, cl_rows in getattr(self, "_case_list_rows", {}).items():
            frags = []
            for rv in cl_rows:
                d = rv["dir"].get().strip()
                e = rv["elements"].get().strip()
                b = rv["blockdim"].get().strip() or "1"
                l = rv["label"].get().strip()
                if d:
                    frags.append(f'--case "{d}" {e} {b} "{l}"')
            values[cl_key] = " ".join(frags)
        try:
            cmd = tmpl.format(**values)
        except KeyError:
            cmd = tmpl
        except (IndexError, ValueError) as e:
            cmd = f"[命令模板格式错误] {e}\n请检查该工具的命令模板是否有未转义的大括号。"
        self._cmd.delete("1.0", tk.END)
        self._cmd.insert("1.0", cmd)

    def _missing_required(self):
        missing = []
        for f in self._field_defs:
            if not f.get("required"):
                continue
            enabled_by = f.get("enabled_by")
            if enabled_by and not bool(self._field_vars.get(enabled_by, tk.BooleanVar(value=False)).get()):
                continue
            key = f.get("key")
            if key not in self._field_vars:
                continue
            if not str(self._field_vars[key].get()).strip():
                missing.append(f.get("label", key))
        return missing

    # ── 执行 ──────────────────────────────────────────────────────────────────

    def _copy(self):
        missing = self._missing_required()
        if missing:
            self._flash("请先填写必填项：" + "、".join(missing), "red")
            return
        cmd = self._cmd.get("1.0", tk.END).strip()
        # 本机命令贴进 PowerShell 时，引号开头的可执行路径同样需要 & 调用运算符
        if (self._current and self._current.get("target") == "local"
                and cmd.startswith('"')):
            cmd = "& " + cmd
        self.root.clipboard_clear()
        self.root.clipboard_append(cmd)
        self._flash("✓ 已复制", "green")

    def _run_local(self):
        missing = self._missing_required()
        if missing:
            self._flash("请先填写必填项：" + "、".join(missing), "red")
            return
        cmd = self._cmd.get("1.0", tk.END).strip()
        if not cmd:
            return
        # PowerShell 里以引号包裹的可执行路径开头会被当成字符串，需用调用运算符 & 才会执行
        run_cmd = ("& " + cmd) if cmd.startswith('"') else cmd
        try:
            subprocess.Popen(["powershell", "-NoExit", "-Command", run_cmd])
            self._flash("▶ 已在 PowerShell 中启动", "#0066cc")
        except Exception as e:
            self._flash(f"错误：{e}", "red")

    def _run_board(self):
        if not self._ssh:
            self._flash("请先连接板子", "red")
            return
        missing = self._missing_required()
        if missing:
            self._flash("请先填写必填项：" + "、".join(missing), "red")
            return
        cmd = self._cmd.get("1.0", tk.END).strip()
        if not cmd:
            return
        self._running_board_command = True
        self._active_channel = None
        self._board_btn.config(state="disabled")
        self._local_btn.config(state="disabled")
        self._stop_btn.config(state="normal")
        self._run_output_chunks = []
        self._set_summary("正在等待命令输出，结束后会自动分析问题摘要...\n")
        self._append_output(f"\n$ {cmd}\n")
        threading.Thread(target=self._exec_ssh, args=(cmd,), daemon=True).start()

    def _exec_ssh(self, cmd):
        try:
            stdin, stdout, stderr = self._ssh.exec_command(
                cmd, timeout=300, get_pty=True)
            channel = stdout.channel
            self._active_channel = channel
            while True:
                emitted = False
                while channel.recv_ready():
                    data = channel.recv(4096).decode(errors="replace")
                    emitted = True
                    self.root.after(0, lambda d=data: self._append_output(d))
                while channel.recv_stderr_ready():
                    data = channel.recv_stderr(4096).decode(errors="replace")
                    emitted = True
                    self.root.after(0, lambda d=data: self._append_output(d))
                if channel.exit_status_ready():
                    while channel.recv_ready():
                        data = channel.recv(4096).decode(errors="replace")
                        self.root.after(0, lambda d=data: self._append_output(d))
                    while channel.recv_stderr_ready():
                        data = channel.recv_stderr(4096).decode(errors="replace")
                        self.root.after(0, lambda d=data: self._append_output(d))
                    exit_status = channel.recv_exit_status()
                    self.root.after(0, lambda s=exit_status: self._on_exec_done(s))
                    return
                if not emitted:
                    time.sleep(0.08)
        except Exception as e:
            self.root.after(0, lambda: self._append_output(f"\n[错误] {e}\n"))
            self.root.after(0, lambda: self._on_exec_done(None))

    def _on_exec_done(self, exit_status=0):
        self._running_board_command = False
        self._active_channel = None
        self._stop_btn.config(state="disabled")
        if exit_status in (None, 0):
            self._append_output("\n[完成]\n")
        else:
            self._append_output(f"\n[完成，退出码 {exit_status}]\n")
        self._analyze_latest_output(exit_status)
        self._update_buttons()

    def _stop_board_command(self):
        channel = self._active_channel
        if not channel:
            self._flash("当前没有可停止的板端命令", "gray")
            return
        try:
            if not channel.closed:
                channel.send("\x03")
                self._append_output("\n[已发送 Ctrl+C，正在等待板端命令退出...]\n")
                self._set_summary("已请求停止当前板端命令；如果官方工具残留子进程，请用“查看 CANN/仿真进程”确认。\n")
                self._stop_btn.config(state="disabled")
        except Exception as e:
            self._append_output(f"\n[停止失败] {e}\n")
            try:
                channel.close()
            except Exception:
                pass

    def _append_output(self, text):
        self._run_output_chunks.append(text)
        self._output.config(state="normal")
        self._output.insert(tk.END, text)
        self._output.see(tk.END)
        self._output.config(state="disabled")

    def _clear_output(self):
        self._output.config(state="normal")
        self._output.delete("1.0", tk.END)
        self._output.config(state="disabled")
        self._run_output_chunks = []
        self._set_summary("输出已清空。下一次命令结束后会重新生成问题摘要。\n")

    def _set_summary(self, text):
        self._summary.config(state="normal")
        self._summary.delete("1.0", tk.END)
        self._summary.insert("1.0", text)
        self._summary.config(state="disabled")

    def _analyze_latest_output(self, exit_status=None):
        text = "".join(self._run_output_chunks)
        success_pattern = (
            r"\b(success|succeeded|passed|100%)\b|"
            r"已保存|通过|SUCCESS|"
            r"successfully created|"
            r"CPack: - package: .* generated|"
            r"Self-extractable archive .* successfully created|"
            r"Generation completed|"
            r"Operator kernel .* execute info|"
            r"dump2trace_core\d+\.json"
        )
        if exit_status == 0 and re.search(success_pattern, text, re.IGNORECASE):
            if re.search(r"Operator kernel .* execute info|Generation completed", text, re.IGNORECASE):
                self._set_summary(
                    "命令已正常结束，msOpGen sim 已生成时间线；并且识别到源码/指令映射统计（line / call count / cycles）。\n"
                    "下一步可以下载 trace_out 目录里的 JSON/CSV，再用本地分析插件转 Excel 或画图。\n"
                )
            else:
                self._set_summary("命令已正常结束，并识别到成功产物。没有需要处理的报错。\n")
            return
        findings = self._extract_findings(text)
        if not findings:
            if re.search(success_pattern, text, re.IGNORECASE):
                self._set_summary("没有识别到明显报错。看起来这次命令大概率跑通了。\n")
            else:
                self._set_summary("没有抓到典型报错。如果结果仍不对，可以把输出里的关键几行贴出来，我再补规则。\n")
            return
        lines = ["我帮你从输出里摘到这些关键问题：\n"]
        for idx, item in enumerate(findings[:8], 1):
            lines.append(f"{idx}. {item['title']}\n")
            if item.get("where"):
                lines.append(f"   位置：{item['where']}\n")
            lines.append(f"   人话解释：{item['explain']}\n")
            lines.append(f"   建议：{item['suggest']}\n")
            if item.get("raw"):
                lines.append(f"   原始行：{item['raw'][:220]}\n")
        self._set_summary("".join(lines))

    def _extract_findings(self, text):
        findings = []
        seen = set()
        lines = text.splitlines()
        for line in lines:
            raw = line.strip()
            if not raw:
                continue
            item = self._classify_error_line(raw)
            if not item:
                continue
            key = (item["title"], item.get("where", ""), item.get("raw", ""))
            if key in seen:
                continue
            seen.add(key)
            findings.append(item)
        if not findings:
            failed = re.search(
                r"(?im)^\s*(?:\[[^\]]*\]\s*)?(?:error|fatal|traceback|exception|failed|失败)\b|"
                r"\b(?:error:|fatal:|traceback \(most recent call last\))",
                text,
            )
            if failed:
                findings.append({
                    "title": "命令失败，但暂时没匹配到具体错误类型",
                    "where": "",
                    "explain": "输出里出现了失败关键词，但不像常见编译/CMake/链接/权限格式。",
                    "suggest": "先看失败关键词前后 20 行；如果经常出现这种格式，可以把样例加入工具箱规则。",
                    "raw": failed.group(0),
                })
        return findings

    def _classify_error_line(self, raw):
        location = ""
        m = re.search(r"([^:\s][^:]*\.(?:cpp|cc|cxx|c|h|hpp|py|sh|json)):(\d+)(?::(\d+))?", raw)
        if m:
            location = f"{m.group(1)}:{m.group(2)}" + (f":{m.group(3)}" if m.group(3) else "")
        low = raw.lower()
        rules = [
            (r"relocatable file is compiled without debug info|compiled without debug info",
             "Debug 信息缺失",
             "你选的 kernel .o 是 Release 或没有带调试信息的产物，msOpGen sim 不能用它做源码/指令位置关联。",
             "先用“构建 OPP 工程 — Debug（仿真/源码映射）”重新编译，再选择 build_out/op_kernel/binary/... 下新生成的 kernel .o。"),
            (r"parsing instr pop dump error: empty parsing output|empty parsing output",
             "dump 里没有可解析的指令输出",
             "msOpGen sim 找到了 dump 目录，但当前 core/subcore 组合里没有有效指令，常见于选错 core、选错 veccore/cubecore，或 dump 文件本身是空的。",
             "310B 矢量算子优先试 core0 + veccore0；确认 dump 目录里有非 0 字节的 core0.veccore0.instr_popped_log.dump。"),
            (r"thread pool thread number should greater than 0",
             "官方 simulator 后处理线程数异常",
             "msprof op simulator 的后处理阶段拿到的线程数变成了 0；我们实测这更像当前板端工具链/模拟器收尾兼容性问题，不是算子计算结果错误。",
             "先看 output/OPPROF.../device0/tmp_dump 是否已经生成；如果有，直接用“msOpGen sim 转时间线”从 tmp_dump 救 trace。"),
            (r"child process exited with status 139|running task failed",
             "simulator 子进程异常退出",
             "软件仿真子进程崩溃或后处理失败；如果普通 ./main 已经 PASS，这通常不是功能正确性错误。",
             "保留这次 OPPROF 目录，检查 device0/tmp_dump；能解析就继续转 trace，不能解析再回头查 simulator 和 SOC/编译模式。"),
            (r"failed to generate .*_aicore_bin|failed to generate .*/_aicore_bin",
             "无法从 reloc 文件生成指令二进制",
             "msOpGen sim 想从 -reloc 文件提取指令信息，但当前文件不合适；最常见是误选了 run/out/main，或者 kernel .o 没有 Debug 信息。",
             "不要选 ./main 或 run/out/main；Debug 编译后选择 build_out/op_kernel/binary/ascend310b/<op_name>/*.o。"),
            (r"/home/[^ ]*/main doesn't exist|main doesn't exist",
             "reloc 路径里的 main 不存在或不该用",
             "`./main` 会按当前目录解析成错误路径；而且我们这条源码映射路线本来就应该选 kernel 侧 .o，不是 host 侧 main。",
             "取消 -reloc 先生成普通 trace，或 Debug 编译后选择 build_out/op_kernel/binary/... 下的 kernel .o。"),
            (r"fatal error: .*no such file or directory|cannot open source file|No such file or directory",
             "文件或头文件找不到",
             "编译器/工具想读某个文件，但路径下没有它，或者 include 路径没有配进去。",
             "检查文件名大小写、当前工作目录、CMake include 路径，以及命令里传的板端路径是否选对。"),
            (r"undefined reference|cannot find -l|ld: cannot find",
             "链接阶段找不到函数或库",
             "代码已经编译到链接阶段，但某个函数实现或动态/静态库没有被链接进来。",
             "检查 CMakeLists.txt 的 target_link_libraries、库路径、函数实现文件是否加入编译。"),
            (r"permission denied|operation not permitted",
             "权限不够",
             "当前用户没有读取、写入或执行这个文件/目录的权限。",
             "给脚本加执行权限 `chmod +x`，或检查输出目录权限；必要时换到 `/home/HwHiAiUser/work` 下操作。"),
            (r"cmake error|cmake.*error",
             "CMake 配置失败",
             "工程生成 Makefile/Ninja 文件时失败，还没真正开始编译 C++。",
             "优先看这行后面的变量名、路径或 package 名；常见是 CANN 路径、编译器路径、源码路径不对。"),
            (r"error:|fatal:",
             "编译器报错",
             "源码语法、类型、模板、宏或接口调用不符合编译器要求。",
             "从第一个 error 开始修，后面的 error 很多可能是连锁反应。优先打开摘要里的文件行号。"),
            (r"msopgen.*(invalid|unsupported|error)|unsupported framework|invalid compute unit",
             "msOpGen 参数不合法",
             "msOpGen 不接受当前参数组合，常见是框架类型、计算单元、JSON 路径或算子名格式不对。",
             "对 310B 生成 Ascend C 工程优先用 `-f tf -c ai_core-ascend310b -lan cpp`，并确认 JSON 可读。"),
            (r"msopst.*(invalid|error)|error_threshold|soc version|case name",
             "msOpST 测试参数不合法",
             "测试用例、SOC 名称、case 名或误差阈值格式不符合 msOpST 要求。",
             "310B 板端默认试 `-soc Ascend310B1`；误差阈值用类似 `[0.001, 0.001]` 的数组格式。"),
            (r"traceback|exception",
             "Python 脚本异常",
             "Python 程序运行时抛异常了，真正原因通常在 Traceback 最后一两行。",
             "看最后一个 `File ... line ...` 和最后一行异常类型；如果是路径/导入错误，先检查运行目录和 PYTHONPATH。"),
            (r"segmentation fault|core dumped",
             "程序崩溃",
             "程序访问了非法内存或底层库崩了，常见于指针、shape、输入输出内存或 ABI 不匹配。",
             "先用 msOpST/mssanitizer 缩小 case；确认输入 shape、dtype、OPP 安装目录和 runner 调用一致。"),
        ]
        for pattern, title, explain, suggest in rules:
            if re.search(pattern, raw, re.IGNORECASE):
                return {
                    "title": title,
                    "where": location,
                    "explain": explain,
                    "suggest": suggest,
                    "raw": raw,
                }
        if "warning:" in low:
            return None
        return None

    def _flash(self, msg, color):
        self._status.config(text=msg, foreground=color)
        self.root.after(3000, lambda: self._status.config(text=""))


if __name__ == "__main__":
    root = tk.Tk()
    try:
        root.tk.call("tk", "scaling", 1.25)
    except Exception:
        pass
    CANNToolbox(root)
    root.mainloop()
