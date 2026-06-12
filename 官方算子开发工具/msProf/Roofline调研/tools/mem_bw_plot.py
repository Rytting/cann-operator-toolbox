#!/usr/bin/env python3
"""
内存通路带宽分析工具 - 适用于 Ascend 310B4 msprof 输出（07_内存通路吞吐率波形图）

用法：
  python mem_bw_plot.py \\
      --case path/64x64   "RGB 64×64" \\
      --case path/128x128 "RGB 128×128" \\
      --case path/256x256 "RGB 256×256" \\
      --peak-bw 34 \\
      --op-name "RgbToGrayCustom" \\
      --output mem_bw.png
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


def to_float(val, default=0.0):
    try:
        v = float(str(val).strip())
        return default if (v != v) else v
    except (TypeError, ValueError):
        return default


def load_mem(data_dir):
    path = os.path.join(data_dir, 'Memory.csv')
    if not os.path.exists(path):
        raise FileNotFoundError(f"找不到 Memory.csv：{data_dir}")
    with open(path, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        sub = row.get('sub_block_id', '').strip()
        if sub in ('', 'cube0'):
            time_us = to_float(row.get('aic_time(us)', 0))
            return {
                'read_bw':    to_float(row.get('aic_main_mem_read_bw(GB/s)',  0)),
                'write_bw':   to_float(row.get('aic_main_mem_write_bw(GB/s)', 0)),
                'read_kb':    to_float(row.get('read_main_memory_datas(KB)',   0)),
                'write_kb':   to_float(row.get('write_main_memory_datas(KB)',  0)),
                'gm_l1_kb':   to_float(row.get('GM_to_L1_datas(KB)',          0)),
                'l1_gm_kb':   to_float(row.get('L1_to_GM_datas(KB)(estimate)', 0)),
                'time_us':    time_us,
                'mte3_bw':    to_float(row.get('aic_mte3_active_bw(GB/s)', 0)
                                       if 'aic_mte3_active_bw(GB/s)' in row else 0),
            }
    raise ValueError(f"Memory.csv 中未找到有效 AIC 行：{data_dir}")


def main():
    ap = argparse.ArgumentParser(
        description='内存通路带宽分析工具（Ascend 310B4）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    ap.add_argument('--case', nargs=4, action='append',
                    metavar=('DIR', 'ELEMENTS', 'BLOCKDIM', 'LABEL'),
                    help='案例（可重复）：目录 [占位] [占位] 标签')
    ap.add_argument('--peak-bw',  default=34.0,  type=float,  help='硬件峰值带宽 GB/s（默认 34）')
    ap.add_argument('--op-name',  default='Operator',          help='算子名称（图标题）')
    ap.add_argument('--output',   default='mem_bw.png',        help='输出图片路径')
    args = ap.parse_args()

    if not args.case:
        ap.error("请至少提供一个 --case DIR LABEL")

    case_dirs, labels, mem_data = [], [], []
    for d, _e, _b, l in args.case:
        case_dirs.append(d)
        labels.append(l or os.path.basename(d.rstrip('/\\')))
        try:
            mem_data.append(load_mem(d))
        except (FileNotFoundError, ValueError) as e:
            print(f"警告：{e}")
            mem_data.append({'read_bw': 0, 'write_bw': 0, 'read_kb': 0,
                             'write_kb': 0, 'time_us': 0, 'mte3_bw': 0,
                             'gm_l1_kb': 0, 'l1_gm_kb': 0})

    print(f"\n{'='*60}")
    print(f"算子：{args.op_name}  峰值带宽={args.peak_bw:.0f} GB/s")
    for l, m in zip(labels, mem_data):
        total_bw = m['read_bw'] + m['write_bw']
        util = total_bw / args.peak_bw * 100
        print(f"  [{l}]  读={m['read_bw']:.2f} GB/s  写={m['write_bw']:.2f} GB/s  "
              f"总={total_bw:.2f} GB/s  利用率={util:.1f}%  "
              f"t={m['time_us']:.1f}μs")
    print(f"{'='*60}\n")

    n = len(labels)
    x = np.arange(n)
    width = 0.28

    read_bws  = [m['read_bw']  for m in mem_data]
    write_bws = [m['write_bw'] for m in mem_data]
    total_bws = [r + w for r, w in zip(read_bws, write_bws)]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(max(8, n * 2.5 + 3), 5))

    # 左图：读写带宽
    b_read  = ax1.bar(x - width / 2, read_bws,  width, label='GM 读带宽', color='#2196F3', alpha=0.85)
    b_write = ax1.bar(x + width / 2, write_bws, width, label='GM 写带宽', color='#FF9800', alpha=0.85)
    ax1.axhline(y=args.peak_bw, color='red', ls='--', lw=1.2, alpha=0.7,
                label=f'峰值 {args.peak_bw:.0f} GB/s')

    for bar in list(b_read) + list(b_write):
        h = bar.get_height()
        if h > 0.2:
            ax1.text(bar.get_x() + bar.get_width() / 2, h + 0.3,
                     f'{h:.1f}', ha='center', va='bottom', fontsize=7.5)

    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, fontsize=9)
    ax1.set_ylabel('带宽 (GB/s)', fontsize=10)
    ax1.set_title('GM 读写带宽对比', fontsize=10)
    ax1.legend(fontsize=8)
    ax1.grid(axis='y', alpha=0.25)
    ax1.set_ylim(0, args.peak_bw * 1.25)

    # 右图：总带宽利用率
    utils = [bw / args.peak_bw * 100 for bw in total_bws]
    bars = ax2.bar(x, utils, 0.45, color='#4CAF50', alpha=0.85)
    ax2.axhline(y=100, color='red', ls='--', lw=1.2, alpha=0.7, label='峰值 100%')

    for bar, bw, util in zip(bars, total_bws, utils):
        h = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width() / 2, h + 1,
                 f'{util:.1f}%\n({bw:.1f} GB/s)', ha='center', va='bottom', fontsize=8)

    ax2.set_xticks(x)
    ax2.set_xticklabels(labels, fontsize=9)
    ax2.set_ylabel('带宽利用率 (%)', fontsize=10)
    ax2.set_title('总带宽利用率（读+写）', fontsize=10)
    ax2.legend(fontsize=8)
    ax2.grid(axis='y', alpha=0.25)
    ax2.set_ylim(0, 120)

    fig.suptitle(f'内存通路吞吐率 — {args.op_name}', fontsize=12, y=1.01)
    plt.tight_layout()
    plt.savefig(args.output, dpi=150, bbox_inches='tight')
    print(f"图片已保存：{args.output}")
    print(f"OUTPUT={args.output}")


if __name__ == '__main__':
    main()
