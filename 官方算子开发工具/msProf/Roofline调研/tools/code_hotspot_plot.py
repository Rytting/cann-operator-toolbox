#!/usr/bin/env python3
"""
算子代码热点图 - 来自 msprof op simulator 的 code_exe_prof.csv（06_算子代码热点图）

注意：数据来源是软件仿真（msprof op simulator），不是真实上板采集。
      cycles 是仿真周期数，不等于实际硬件耗时，但可以相对比较各行代码的开销。

用法：
  python code_hotspot_plot.py \\
      --csv path/to/core0_veccore0_code_exe_prof.csv \\
      --op-name "RgbToGrayCustom 128×128" \\
      --output code_hotspot.png
"""

import argparse
import csv
import os
import sys

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
except ImportError:
    print("请先安装依赖：pip install matplotlib numpy")
    sys.exit(1)

plt.rcParams['font.family'] = ['Microsoft YaHei', 'SimHei', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False


def shorten_path(full_path):
    """把完整路径缩短成可读的短标签，区分用户代码和框架代码。"""
    if not full_path:
        return '(unknown)'
    # 提取文件名和行号
    base = full_path.replace('\\', '/')
    # 判断是否是用户 kernel 代码
    user_markers = ['rgb_to_gray', 'RgbToGrayCustom', 'rgb_to_gray_custom']
    is_user = any(m.lower() in base.lower() for m in user_markers)
    # 取最后的 file.cpp:line 部分
    parts = base.split('/')
    short = parts[-1] if parts else base
    prefix = '[用户]' if is_user else '[框架]'
    return f"{prefix} {short}"


def load_code_prof(csv_path):
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"找不到文件：{csv_path}")
    rows = []
    with open(csv_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            line_path = row.get('line', '').strip()
            try:
                cycles = int(str(row.get('cycles', 0)).strip())
                calls  = int(str(row.get('call count', 0)).strip())
            except (TypeError, ValueError):
                cycles, calls = 0, 0
            if cycles > 0:
                rows.append({
                    'path':   line_path,
                    'short':  shorten_path(line_path),
                    'cycles': cycles,
                    'calls':  calls,
                })
    rows.sort(key=lambda r: r['cycles'], reverse=True)
    return rows


def main():
    ap = argparse.ArgumentParser(
        description='算子代码热点图（Ascend msprof op simulator）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    ap.add_argument('--csv',      required=True,               help='code_exe_prof.csv 路径')
    ap.add_argument('--top',      default=15,    type=int,     help='显示前 N 行（默认 15）')
    ap.add_argument('--op-name',  default='Operator',           help='算子名称（图标题）')
    ap.add_argument('--output',   default='code_hotspot.png',  help='输出图片路径')
    args = ap.parse_args()

    rows = load_code_prof(args.csv)
    if not rows:
        print("错误：CSV 中没有有效数据"); sys.exit(1)

    top_rows = rows[:args.top]
    total_cycles = sum(r['cycles'] for r in rows)

    print(f"\n{'='*60}")
    print(f"算子：{args.op_name}  来源：{os.path.basename(args.csv)}")
    print(f"总 cycles：{total_cycles:,}  数据来自软件仿真")
    for r in top_rows:
        pct = r['cycles'] / total_cycles * 100
        print(f"  {r['cycles']:>6,} cycles ({pct:4.1f}%)  x{r['calls']}  {r['short']}")
    print(f"{'='*60}\n")

    labels  = [r['short'] for r in top_rows]
    cycles  = [r['cycles'] for r in top_rows]
    calls   = [r['calls']  for r in top_rows]
    pcts    = [c / total_cycles * 100 for c in cycles]

    # 颜色：用户代码深色，框架代码浅色
    colors = ['#E53935' if '[用户]' in l else '#90A4AE' for l in labels]

    fig, ax = plt.subplots(figsize=(10, max(4, len(top_rows) * 0.42 + 1.5)))
    y_pos = np.arange(len(top_rows))[::-1]   # 最大值在顶部

    bars = ax.barh(y_pos, cycles, color=colors, alpha=0.85)

    for bar, c, p, n in zip(bars, cycles, pcts, calls):
        w = bar.get_width()
        ax.text(w + total_cycles * 0.005, bar.get_y() + bar.get_height() / 2,
                f'{c:,}  ({p:.1f}%)  ×{n}',
                va='center', ha='left', fontsize=7.5)

    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel('仿真 Cycles（相对比较，不等于实际硬件耗时）', fontsize=9)
    ax.set_title(f'代码热点（Top {len(top_rows)}）— {args.op_name}\n'
                 f'数据来源：msprof op simulator（软件仿真）',
                 fontsize=10)
    ax.grid(axis='x', alpha=0.25)

    # 图例
    from matplotlib.patches import Patch
    legend_elems = [Patch(facecolor='#E53935', alpha=0.85, label='用户 kernel 代码'),
                    Patch(facecolor='#90A4AE', alpha=0.85, label='CANN 框架代码')]
    ax.legend(handles=legend_elems, fontsize=8, loc='lower right')

    plt.tight_layout()
    plt.savefig(args.output, dpi=150, bbox_inches='tight')
    print(f"图片已保存：{args.output}")
    print(f"OUTPUT={args.output}")


if __name__ == '__main__':
    main()
