#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""KPP 输出解读：读 msKPP 跑出来的 Pipe_statistic.csv / Instruction_statistic.csv
（可选 trace.json），自动判出瓶颈在哪条 pipe、是搬运受限还是计算受限、读写带宽
是否对称、双缓冲理论收益上限——把原本要手动加 cycle/算带宽的活儿一键打出来。

用法：
    python kpp_report.py <KPP输出目录>
    python kpp_report.py <KPP输出目录> --md 理论建模_自动.md   # 同时写一份 markdown

注意：msKPP 用 910B1 硬件参数建模，310B4 不在支持列表内，绝对数字会偏乐观，
      只看"瓶颈在哪、搬运还是计算受限"这类相对趋势。实测请以 msProf 为准。
"""
import argparse
import csv
import json
import os
import sys

# pipe 归类：哪些算"数据搬运"，哪些算"计算"
MOVE_PIPES = {"PIPE-MTE1", "PIPE-MTE2", "PIPE-MTE3", "PIPE-FIX"}
CALC_PIPES = {"PIPE-V", "PIPE-M", "PIPE-S"}
PIPE_HUMAN = {
    "PIPE-MTE2": "GM→UB 读入",
    "PIPE-MTE3": "UB→GM 写出",
    "PIPE-MTE1": "L1→UB 搬运",
    "PIPE-V": "Vector 计算",
    "PIPE-M": "Cube 计算",
    "PIPE-S": "Scalar 标量",
    "PIPE-FIX": "FixPipe",
}


def _num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def read_pipe_csv(path):
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            rows.append({k.strip(): (v.strip() if isinstance(v, str) else v)
                         for k, v in r.items()})
    return rows


def load(out_dir):
    pipe_path = os.path.join(out_dir, "Pipe_statistic.csv")
    inst_path = os.path.join(out_dir, "Instruction_statistic.csv")
    trace_path = os.path.join(out_dir, "trace.json")
    if not os.path.isfile(pipe_path):
        sys.exit(f"[错误] 找不到 {pipe_path}\n该目录看起来不是 KPP 输出目录。")
    pipes = read_pipe_csv(pipe_path)
    insts = read_pipe_csv(inst_path) if os.path.isfile(inst_path) else []
    bw = {}  # pipe 名 -> 建模带宽(GB/s)，直接从 trace.json 取现成值
    if os.path.isfile(trace_path):
        try:
            with open(trace_path, encoding="utf-8") as f:
                tj = json.load(f)
            tid_name = {e["tid"]: e["args"]["name"]
                        for e in tj.get("traceEvents", [])
                        if e.get("ph") == "M" and e.get("name") == "thread_name"}
            for e in tj.get("traceEvents", []):
                if e.get("ph") == "X" and "Bandwidth(GB/s)" in e.get("args", {}):
                    pname = tid_name.get(e["tid"], "")
                    bw[pname] = e["args"]["Bandwidth(GB/s)"]
        except Exception:
            pass
    return pipes, insts, bw


def analyze(pipes, insts, bw):
    total = next((r for r in pipes if r.get("Pipe", "").lower() == "total"), None)
    items = [r for r in pipes if r.get("Pipe", "").lower() != "total"]
    total_cycle = _num(total["Cycle"]) if total else sum(_num(r["Cycle"]) for r in items)
    total_us = _num(total["Duration(us)"]) if total else 0.0

    for r in items:
        r["_cycle"] = _num(r["Cycle"])
        r["_us"] = _num(r["Duration(us)"])
        r["_pct"] = (r["_cycle"] / total_cycle * 100) if total_cycle else 0.0

    move_cycle = sum(r["_cycle"] for r in items if r["Pipe"] in MOVE_PIPES)
    calc_cycle = sum(r["_cycle"] for r in items if r["Pipe"] in CALC_PIPES)
    bottleneck = max(items, key=lambda r: r["_cycle"]) if items else None

    lines = []
    P = lines.append
    P("=" * 60)
    P("  KPP 输出解读（910B1 建模，310B4 仅看相对趋势）")
    P("=" * 60)
    P(f"  串行总 cycle：{total_cycle:.0f}" + (f"    并行后时长：{total_us:.4f} us" if total_us else ""))
    P("")
    P("  各 pipe 占比（按 cycle 排序）：")
    for r in sorted(items, key=lambda r: r["_cycle"], reverse=True):
        human = PIPE_HUMAN.get(r["Pipe"], r["Pipe"])
        bar = "█" * max(1, round(r["_pct"] / 4))
        bwtxt = f"  {bw[r['Pipe']]:.1f} GB/s" if r["Pipe"] in bw else ""
        P(f"    {r['Pipe']:<10} {human:<10} {r['_cycle']:>6.0f} cyc  {r['_pct']:5.1f}%  {bar}{bwtxt}")
    P("")

    # 瓶颈
    if bottleneck:
        P(f"  ▶ 瓶颈 pipe：{bottleneck['Pipe']}（{PIPE_HUMAN.get(bottleneck['Pipe'], '')}），"
          f"占 {bottleneck['_pct']:.1f}%")

    # 搬运 vs 计算
    move_pct = (move_cycle / total_cycle * 100) if total_cycle else 0
    calc_pct = (calc_cycle / total_cycle * 100) if total_cycle else 0
    P(f"  ▶ 搬运 {move_cycle:.0f} cyc（{move_pct:.1f}%） vs 计算 {calc_cycle:.0f} cyc（{calc_pct:.1f}%）")
    if move_cycle >= calc_cycle * 1.5:
        P(f"    → memory-bound（搬运受限）。优化重点放在切分 / buffer 复用 / 减少进出 GM，")
        P(f"      而不是改计算逻辑——算力再省也藏在搬运后面。")
    elif calc_cycle >= move_cycle * 1.5:
        P(f"    → compute-bound（计算受限）。值得想怎么减计算量 / 换更快的向量指令。")
    else:
        P(f"    → 搬运与计算大致均衡，两边都可能成为优化点。")

    # 读写带宽对称性
    rd, wr = bw.get("PIPE-MTE2"), bw.get("PIPE-MTE3")
    if rd and wr:
        ratio = wr / rd if rd else 0
        P(f"  ▶ 读带宽 {rd:.1f} GB/s，写带宽 {wr:.1f} GB/s（写≈读的 {ratio*100:.0f}%）")
        if ratio < 0.8:
            P(f"    → 写明显比读慢，写出多的算子会更吃亏；尽量减少 UB→GM 的回写次数。")

    # 双缓冲收益上限
    if total_cycle and calc_cycle:
        roi = min(calc_cycle, move_cycle) / total_cycle * 100
        P(f"  ▶ 双缓冲理论收益上限 ≈ {roi:.1f}%"
          f"（把较小的那条 pipe 完全藏进较大的之后最多省这么多；实际因流水建立更低）")

    # 指令级别
    if insts:
        P("")
        P("  指令明细：")
        for r in sorted(insts, key=lambda r: _num(r.get("Cycle", 0)), reverse=True):
            P(f"    {r.get('Instruction',''):<16} {_num(r.get('Cycle',0)):>6.0f} cyc")

    P("")
    P("  ⚠ 以上为 910B1（HBM）建模，310B4 用 LPDDR，绝对时间会偏乐观。")
    P("    请用 msProf 上板实测对账；趋势（谁是瓶颈、搬运还是计算受限）通常仍成立。")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="KPP 输出解读")
    ap.add_argument("out_dir", help="msKPP 输出目录（含 Pipe_statistic.csv）")
    ap.add_argument("--md", default="", help="可选：把解读同时写成 markdown 文件")
    args = ap.parse_args()
    pipes, insts, bw = load(args.out_dir)
    report = analyze(pipes, insts, bw)
    print(report)
    if args.md:
        with open(args.md, "w", encoding="utf-8") as f:
            f.write("# KPP 输出解读（自动生成）\n\n```\n" + report + "\n```\n")
        print(f"\n[已写出] {args.md}")


if __name__ == "__main__":
    main()
