#!/usr/bin/env python3
"""Check whether an msOpGen OPP project still looks like a skeleton."""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


@dataclass
class CheckResult:
    title: str
    path: Path | None
    passed: list[str]
    missing: list[str]
    warnings: list[str]

    @property
    def ok(self) -> bool:
        return not self.missing and not self.warnings


PROFILE_ALIASES = {
    "add": "elementwise_binary",
    "generic": "generic",
}

PROFILE_LABELS = {
    "generic": "通用基础检查",
    "elementwise_binary": "Vector 二元逐元素（Add/Sub/Mul 类）",
    "elementwise_vector": "Vector 单输入/多输入逐元素（激活/图像类）",
    "reduce": "Reduce 聚合类",
    "gather_scatter": "Gather/Scatter 索引寻址类",
    "scan": "Scan 前缀计算类",
    "copy_cast_layout": "Copy/Cast/Layout 转换类",
    "matmul_cube_basic": "MatMul/Cube 基础检查",
}

PROFILE_CHOICES = list(PROFILE_LABELS)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def find_first(root: Path, patterns: list[str], include_dirs: list[str] | None = None) -> Path | None:
    include_dirs = include_dirs or []
    candidates: list[Path] = []
    for pattern in patterns:
        candidates.extend(root.rglob(pattern))
    filtered: list[Path] = []
    for path in candidates:
        if not path.is_file():
            continue
        posix = path.as_posix().lower()
        if include_dirs and not any(part.lower() in posix for part in include_dirs):
            continue
        filtered.append(path)
    if not filtered:
        return None
    filtered.sort(key=lambda p: (len(p.parts), str(p).lower()))
    return filtered[0]


def tiling_include_names(host_path: Path | None) -> list[str]:
    if not host_path:
        return []
    text = read_text(host_path)
    names: list[str] = []
    for match in re.finditer(r"#\s*include\s*[<\"]([^>\"]*tiling[^>\"]*\.h(?:pp)?)[>\"]", text, re.IGNORECASE):
        names.append(Path(match.group(1)).name)
    return names


def find_tiling_header(root: Path, host_path: Path | None) -> tuple[Path | None, list[str]]:
    tiling = find_first(root, ["*tiling*.h", "*tiling*.hpp"])
    if tiling:
        return tiling, []

    warnings: list[str] = []
    include_names = tiling_include_names(host_path)
    if not include_names:
        return None, warnings

    # 用户经常只选择手写代码 src/ 目录；msopgen 原始 tiling 头文件可能还在相邻 gen/ 里。
    search_roots = [root.parent] if root.name.lower() == "src" else []
    for include_name in include_names:
        for search_root in search_roots:
            matches = [p for p in search_root.rglob(include_name) if p.is_file()]
            matches.sort(key=lambda p: (len(p.parts), str(p).lower()))
            if matches:
                warnings.append(
                    f"tiling 头文件不在当前选择目录内；已按 host include 在相邻目录找到：{matches[0]}"
                )
                return matches[0], warnings
        warnings.append(f"host 引用了 {include_name}，但当前选择目录里没有这个头文件。")
    return None, warnings


def check_patterns(text: str, specs: list[tuple[str, str]]) -> tuple[list[str], list[str]]:
    passed: list[str] = []
    missing: list[str] = []
    for label, pattern in specs:
        if re.search(pattern, text, re.MULTILINE):
            passed.append(label)
        else:
            missing.append(label)
    return passed, missing


def normalize_profile(profile: str) -> str:
    return PROFILE_ALIASES.get(profile, profile)


def add_profile_kernel_specs(profile: str, specs: list[tuple[str, str]], warnings: list[str], text: str) -> None:
    vector_api = r"\b(Add|Sub|Mul|Div|Muls|Adds|Max|Min|Exp|Ln|Abs|Relu|Duplicate)\s*\("
    if profile == "elementwise_binary":
        specs.extend([
            ("二元矢量计算 API", r"\b(Add|Sub|Mul|Div|Max|Min)\s*\("),
        ])
        if not re.search(r"\b(x|input0|src0)\w*\b", text, re.IGNORECASE) or not re.search(r"\b(y|input1|src1)\w*\b", text, re.IGNORECASE):
            warnings.append("二元逐元素算子通常应能看出两个输入；请确认 x/y 或 input0/input1 都已接入。")
    elif profile == "elementwise_vector":
        specs.extend([
            ("矢量计算 API", vector_api),
            ("LocalTensor 中间数据", r"\bLocalTensor\s*<"),
        ])
    elif profile == "reduce":
        specs.extend([
            ("聚合/规约线索", r"\b(Reduce|ReduceSum|ReduceMax|ReduceMin|WholeReduce|sum|acc|accum|for\s*\().*"),
            ("循环或分段处理", r"\bfor\s*\(|\bwhile\s*\("),
        ])
        warnings.append("Reduce 需要重点确认输出 shape、reduce 轴、跨 tile/block 聚合是否正确；关键词检查只能发现明显空壳。")
    elif profile == "gather_scatter":
        specs.extend([
            ("索引输入/变量", r"\b(indices|index|idx|indice)\b"),
            ("地址偏移/步长计算", r"\b(offset|stride|slice|axis)\b|[\+\-]\s*\w+\s*\*"),
            ("边界判断", r"\bif\s*\(.*(<|<=|>|>=).*"),
        ])
        warnings.append("Gather/Scatter 的核心风险是不规则访存、索引越界和 Scatter 写冲突；需要结合数据范围单独验证。")
    elif profile == "scan":
        specs.extend([
            ("前缀/累计状态线索", r"\b(prefix|scan|cum|cumsum|running|acc|accum)\b"),
            ("顺序依赖循环", r"\bfor\s*\(|\bwhile\s*\("),
        ])
        warnings.append("Scan 有前缀依赖，跨 block/segment 的边界状态需要特别设计；不能按普通 elementwise 独立切分。")
    elif profile == "copy_cast_layout":
        specs.extend([
            ("数据搬运", r"\bDataCopy\s*\("),
            ("地址偏移或布局处理", r"\b(offset|stride|format|layout|shape|axis)\b|[\+\-]\s*\w+\s*\*"),
        ])
        if not re.search(r"\b(Cast|Round|half|float|int8|uint8|int32)\b", text):
            warnings.append("如果这是 Cast 算子，请确认 dtype 转换逻辑；如果只是 Copy/Layout，可忽略 dtype 提示。")
    elif profile == "matmul_cube_basic":
        specs.extend([
            ("Matmul/Cube 头文件或接口", r"matmul|Matmul|Cube|matmul_intf"),
            ("矩阵 A/B/C 设置", r"\b(SetTensorA|SetTensorB|GetTensorC|Iterate)\b"),
        ])
        warnings.append("MatMul/Cube 只做基础识别；深度检查还需要 M/N/K、L0/L1/UB、AIC/AIV 协作等专门规则。")


def add_profile_host_specs(profile: str, specs: list[tuple[str, str]], warnings: list[str], text: str) -> None:
    if profile in ("reduce", "gather_scatter", "scan"):
        specs.append(("shape/axis 参数线索", r"\b(axis|axes|shape|dim|outer|inner)\b"))
    if profile == "gather_scatter":
        warnings.append("host 侧需确认 indices dtype、axis/slice 语义和越界策略是否与 JSON/case 对齐。")
    elif profile == "scan":
        warnings.append("host 侧需确认 scan 方向、axis、inclusive/exclusive 语义，以及输出 shape 是否与输入一致。")
    elif profile == "matmul_cube_basic":
        specs.append(("M/N/K 或矩阵维度线索", r"\b(M|N|K|mSize|nSize|kSize|baseM|baseN|baseK)\b"))


def add_profile_tiling_specs(profile: str, specs: list[tuple[str, str]], warnings: list[str], text: str) -> None:
    if profile == "elementwise_binary":
        warnings.append("二元逐元素通常要确认 total/block/tile/loop 或等价常量，确保两个输入和输出切分一致。")
    elif profile == "reduce":
        specs.append(("Reduce tiling 线索", r"\b(axis|outer|inner|reduce|reduceLen|segment)\b"))
    elif profile == "gather_scatter":
        specs.append(("Gather/Scatter tiling 线索", r"\b(indices|index|slice|axis|stride|offset)\b"))
    elif profile == "scan":
        specs.append(("Scan tiling 线索", r"\b(axis|segment|prefix|offset|blockOffset|inner|outer)\b"))
    elif profile == "matmul_cube_basic":
        specs.append(("MatMul tiling 线索", r"\b(baseM|baseN|baseK|mSize|nSize|kSize|singleM|singleN|singleK)\b"))


def check_kernel(path: Path | None, profile: str) -> CheckResult:
    if not path:
        return CheckResult("kernel 侧实现", None, [], ["未找到 op_kernel 下的 .cpp 文件"], [])

    text = read_text(path)
    warnings: list[str] = []
    specs = [
        ("AI Core kernel 入口", r"extern\s+\"C\".*__global__.*__aicore__"),
        ("kernel 类或结构", r"\b(class|struct)\s+Kernel\w*"),
        ("Init 初始化阶段", r"\bInit\s*\("),
        ("Process 主流程", r"\bProcess\s*\("),
        ("CopyIn 搬入阶段", r"\bCopyIn\s*\("),
        ("Compute 计算阶段", r"\bCompute\s*\("),
        ("CopyOut 搬出阶段", r"\bCopyOut\s*\("),
        ("GlobalTensor", r"\bGlobalTensor\s*<"),
        ("LocalTensor", r"\bLocalTensor\s*<"),
        ("TPipe", r"\bTPipe\b"),
        ("TQue/TBuf 队列或临时缓冲", r"\b(TQue|TBuf)\s*<"),
        ("DataCopy 数据搬运", r"\bDataCopy\s*\("),
    ]
    add_profile_kernel_specs(profile, specs, warnings, text)

    passed, missing = check_patterns(text, specs)
    if profile == "elementwise_binary":
        global_tensor_count = len(re.findall(r"\bGlobalTensor\s*<", text))
        if global_tensor_count >= 3:
            passed.append("至少三个 GlobalTensor（通常对应两个输入和一个输出）")
        else:
            missing.append("至少三个 GlobalTensor（通常对应两个输入和一个输出）")
    if "TODO: user kernel impl" in text or "TODO" in text:
        warnings.append("kernel 文件仍包含 TODO，可能还是 msopgen 生成的空壳或半成品")
    if len(text.strip()) < 800:
        warnings.append("kernel 文件很短，通常不像完整 Ascend C kernel 实现")
    if "GET_TILING_DATA" not in text:
        warnings.append("kernel 未显式读取 GET_TILING_DATA；若使用运行时 tiling，请确认这里不是遗漏。若使用编译期常量切分，则可忽略。")
    return CheckResult("kernel 侧实现", path, passed, missing, warnings)


def check_host(path: Path | None, profile: str) -> CheckResult:
    if not path:
        return CheckResult("host/注册侧实现", None, [], ["未找到 op_host 下的 .cpp 文件"], [])

    text = read_text(path)
    warnings: list[str] = []
    specs = [
        ("TilingFunc", r"\bTilingFunc\s*\("),
        ("InferShape", r"\bInferShape\s*\("),
        ("InferDataType", r"\bInferDataType\s*\("),
        ("SetTiling", r"\bSetTiling\s*\("),
        ("SetBlockDim", r"\bSetBlockDim\s*\("),
        ("SaveToBuffer", r"\bSaveToBuffer\s*\("),
        ("OP_ADD 注册", r"\bOP_ADD\s*\("),
        ("AICore 配置", r"\bAICore\s*\("),
        ("ascend310b 配置", r"ascend310b"),
    ]
    add_profile_host_specs(profile, specs, warnings, text)
    passed, missing = check_patterns(text, specs)
    if "TODO" in text:
        warnings.append("host 文件仍包含 TODO")
    if re.search(r"SetBlockDim\s*\(\s*1\s*\)", text):
        warnings.append("SetBlockDim 当前为 1；若想验证多 block 切分策略，需要确认这是否符合设计")
    return CheckResult("host/注册侧实现", path, passed, missing, warnings)


def check_tiling(path: Path | None, require_rich_tiling: bool, profile: str,
                 extra_warnings: list[str] | None = None) -> CheckResult:
    if not path:
        return CheckResult("tiling 数据定义", None, [], ["未找到 tiling 头文件"], extra_warnings or [])

    text = read_text(path)
    warnings: list[str] = list(extra_warnings or [])
    specs = [
        ("BEGIN_TILING_DATA_DEF", r"\bBEGIN_TILING_DATA_DEF\s*\("),
        ("TILING_DATA_FIELD_DEF", r"\bTILING_DATA_FIELD_DEF\s*\("),
        ("REGISTER_TILING_DATA_CLASS", r"\bREGISTER_TILING_DATA_CLASS\s*\("),
    ]
    add_profile_tiling_specs(profile, specs, warnings, text)
    passed, missing = check_patterns(text, specs)
    fields = re.findall(r"\bTILING_DATA_FIELD_DEF\s*\(", text)
    if require_rich_tiling and len(fields) < 3:
        warnings.append("tiling 字段较少；复杂切分通常还需要 total/block/tile/loop 等字段")
    if "TODO" in text:
        warnings.append("tiling 文件仍包含 TODO")
    return CheckResult("tiling 数据定义", path, passed, missing, warnings)


def print_result(result: CheckResult) -> None:
    print(f"\n[{result.title}]")
    if result.path:
        print(f"文件：{result.path}")
    for item in result.passed:
        print(f"  [OK] {item}")
    for item in result.missing:
        print(f"  [缺] {item}")
    for item in result.warnings:
        print(f"  [注意] {item}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check msOpGen OPP project completeness.")
    parser.add_argument("project", help="OPP project directory generated by msopgen gen")
    parser.add_argument("--op-profile", choices=PROFILE_CHOICES, default="elementwise_binary",
                        help="operator programming paradigm checklist")
    parser.add_argument("--op-kind", choices=["add", "generic"], default=None,
                        help="deprecated alias: add -> elementwise_binary, generic -> generic")
    parser.add_argument("--strict-tiling", action="store_true",
                        help="warn when tiling data has only a minimal field set")
    args = parser.parse_args()

    root = Path(args.project).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        print(f"[FAIL] 工程目录不存在：{root}")
        return 2
    profile = normalize_profile(args.op_kind or args.op_profile)

    kernel = find_first(root, ["*.cpp"], ["op_kernel", "kernel"])
    host = find_first(root, ["*.cpp"], ["op_host", "host"])
    tiling, tiling_warnings = find_tiling_header(root, host)

    print("OPP 工程完整性检查")
    print(f"工程目录：{root}")
    print(f"检查范式：{PROFILE_LABELS.get(profile, profile)}")
    print("说明：本工具只做关键词体检，不证明算子一定正确；它主要用于识别 msopgen gen 后仍像空壳的工程。")

    results = [
        check_kernel(kernel, profile),
        check_host(host, profile),
        check_tiling(tiling, args.strict_tiling or profile != "generic", profile, tiling_warnings),
    ]
    for result in results:
        print_result(result)

    missing_count = sum(len(r.missing) for r in results)
    warning_count = sum(len(r.warnings) for r in results)

    print("\n[结论]")
    if missing_count:
        print(f"[需要补代码] 发现 {missing_count} 个缺失项、{warning_count} 个注意项。建议先补齐缺失阶段，再运行 build/compile。")
        return 1
    if warning_count:
        print(f"[基本齐全但需复核] 必备结构都在，但有 {warning_count} 个注意项。可以先跑官方 compile 或 Release 构建做语法/工程校验。")
        return 0
    print("[看起来已补全] kernel、host、tiling 的关键结构都已出现。下一步可以跑官方 compile 或 Release 构建。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
