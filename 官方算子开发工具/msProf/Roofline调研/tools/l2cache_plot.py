#!/usr/bin/env python3
"""
L2 Cache 命中率分析工具 - 适用于 Ascend 310B4 msprof 输出（03_Cache热力图）

用法：
  python l2cache_plot.py \\
      --case path/64x64   "RGB 64×64" \\
      --case path/128x128 "RGB 128×128" \\
      --case path/256x256 "RGB 256×256" \\
      --op-name "RgbToGrayCustom" \\
      --output l2cache.png
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


def load_cache(data_dir):
    path = os.path.join(data_dir, 'L2Cache.csv')
    if not os.path.exists(path):
        raise FileNotFoundError(f"找不到 L2Cache.csv：{data_dir}")
    with open(path, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        sub = row.get('sub_block_id', '').strip()
        if sub in ('', 'cube0'):
            return {
                'write_hit':  to_float(row.get('aic_write_hit_rate(%)',  0)),
                'read_hit':   to_float(row.get('aic_read_hit_rate(%)',   0)),
                'total_hit':  to_float(row.get('aic_total_hit_rate(%)',  0)),
                'write_hit_n':  to_float(row.get('aic_write_cache_hit',  0)),
                'write_miss_n': to_float(row.get('aic_write_cache_miss_allocate', 0)),
                'r0_hit_n':     to_float(row.get('aic_r0_read_cache_hit', 0)),
                'r0_miss_n':    to_float(row.get('aic_r0_read_cache_miss_allocate', 0)),
            }
    raise ValueError(f"L2Cache.csv 中未找到有效 AIC 行：{data_dir}")


def main():
    ap = argparse.ArgumentParser(
        description='L2 Cache 命中率分析工具（Ascend 310B4）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    ap.add_argument('--case', nargs=4, action='append',
                    metavar=('DIR', 'ELEMENTS', 'BLOCKDIM', 'LABEL'),
                    help='案例（可重复）：目录 [占位] [占位] 标签')
    ap.add_argument('--op-name',  default='Operator',       help='算子名称（图标题）')
    ap.add_argument('--output',   default='l2cache.png',    help='输出图片路径')
    args = ap.parse_args()

    if not args.case:
        ap.error("请至少提供一个 --case DIR LABEL")

    case_dirs, labels, cache_data = [], [], []
    for d, _e, _b, l in args.case:
        case_dirs.append(d)
        labels.append(l or os.path.basename(d.rstrip('/\\')))
        try:
            cache_data.append(load_cache(d))
        except (FileNotFoundError, ValueError) as e:
            print(f"警告：{e}")
            cache_data.append({'write_hit': 0, 'read_hit': 0, 'total_hit': 0})

    print(f"\n{'='*55}")
    print(f"算子：{args.op_name}  L2 Cache 命中率")
    for l, c in zip(labels, cache_data):
        print(f"  [{l}]  写命中={c['write_hit']:.1f}%  "
              f"读命中={c['read_hit']:.1f}%  "
              f"总命中={c['total_hit']:.1f}%")
    print(f"{'='*55}\n")

    n = len(labels)
    x = np.arange(n)
    width = 0.22

    write_rates = [c['write_hit']  for c in cache_data]
    read_rates  = [c['read_hit']   for c in cache_data]
    total_rates = [c['total_hit']  for c in cache_data]

    fig, ax = plt.subplots(figsize=(max(5, n * 2 + 2), 5))

    b1 = ax.bar(x - width, write_rates, width, label='写命中率', color='#2196F3', alpha=0.85)
    b2 = ax.bar(x,          read_rates,  width, label='读命中率', color='#4CAF50', alpha=0.85)
    b3 = ax.bar(x + width,  total_rates, width, label='总命中率', color='#FF9800', alpha=0.85)

    def label_bars(bars):
        for bar in bars:
            h = bar.get_height()
            if h > 0.5:
                ax.text(bar.get_x() + bar.get_width() / 2, h + 0.8,
                        f'{h:.1f}%', ha='center', va='bottom', fontsize=7.5)

    label_bars(b1)
    label_bars(b2)
    label_bars(b3)

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylabel('命中率 (%)', fontsize=10)
    ax.set_ylim(0, 115)
    ax.set_title(f'L2 Cache 命中率 — {args.op_name}', fontsize=11)
    ax.legend(fontsize=9)
    ax.grid(axis='y', alpha=0.25)

    subtitle = 'L2 命中率低说明数据量超出缓存容量，每次需从 DRAM 读取（memory-bound 算子的正常表现）'
    ax.text(0.5, -0.14, subtitle, transform=ax.transAxes,
            ha='center', fontsize=7.5, color='#555555', style='italic')

    plt.tight_layout()
    plt.savefig(args.output, dpi=150, bbox_inches='tight')
    print(f"图片已保存：{args.output}")
    print(f"OUTPUT={args.output}")


if __name__ == '__main__':
    main()
