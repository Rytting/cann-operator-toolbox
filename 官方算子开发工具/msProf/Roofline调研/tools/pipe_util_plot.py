#!/usr/bin/env python3
"""
PIPE 利用率分析工具 - 适用于 Ascend 310B4 msprof 输出

模式一：热力图（01_计算内存热力图）
  python pipe_util_plot.py --mode heatmap \\
      --case path/64x64  "RGB 64×64" \\
      --case path/128x128 "RGB 128×128" \\
      --case path/256x256 "RGB 256×256" \\
      --output pipe_heatmap.png

模式二：堆叠柱状图（04_通算流水图）
  python pipe_util_plot.py --mode stacked \\
      --case path/64x64  "RGB 64×64" \\
      --case path/128x128 "RGB 128×128" \\
      --case path/256x256 "RGB 256×256" \\
      --output pipe_stacked.png
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

PIPES = ['Scalar', 'MTE1', 'MTE2', 'MTE3']

RATIO_COLS = {
    'Scalar': 'aic_scalar_ratio',
    'MTE1':   'aic_mte1_ratio',
    'MTE2':   'aic_mte2_ratio',
    'MTE3':   'aic_mte3_ratio',
}

TIME_COLS = {
    'Scalar': 'aic_scalar_time(us)',
    'MTE1':   'aic_mte1_time(us)',
    'MTE2':   'aic_mte2_time(us)',
    'MTE3':   'aic_mte3_time(us)',
}

PIPE_COLORS = {
    'Scalar': '#9E9E9E',
    'MTE1':   '#03A9F4',
    'MTE2':   '#4CAF50',
    'MTE3':   '#FF9800',
}


def to_float(val, default=0.0):
    try:
        v = float(str(val).strip())
        return default if (v != v) else v
    except (TypeError, ValueError):
        return default


def load_pipe(data_dir):
    path = os.path.join(data_dir, 'PipeUtilization.csv')
    if not os.path.exists(path):
        raise FileNotFoundError(f"找不到 PipeUtilization.csv：{data_dir}")
    with open(path, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    # 取 AIC 行（sub_block_id = cube0 或空）
    for row in rows:
        sub = row.get('sub_block_id', '').strip()
        if sub in ('', 'cube0'):
            ratios = {p: to_float(row.get(RATIO_COLS[p], 0)) for p in PIPES}
            times  = {p: to_float(row.get(TIME_COLS[p],  0)) for p in PIPES}
            total  = to_float(row.get('aic_time(us)', 0))
            return ratios, times, total
    raise ValueError(f"PipeUtilization.csv 中未找到有效 AIC 行：{data_dir}")


def plot_heatmap(case_dirs, labels, op_name, output):
    n = len(case_dirs)
    # matrix: rows=PIPES, cols=cases
    data = np.zeros((len(PIPES), n))
    totals = []
    for j, d in enumerate(case_dirs):
        ratios, _, total = load_pipe(d)
        for i, p in enumerate(PIPES):
            data[i, j] = ratios[p] * 100   # 转成百分比
        totals.append(total)

    fig, ax = plt.subplots(figsize=(max(5, n * 1.8 + 1.5), 4))
    im = ax.imshow(data, aspect='auto', cmap='YlOrRd', vmin=0, vmax=100)

    ax.set_xticks(range(n))
    ax.set_xticklabels([f"{l}\n({t:.1f} μs)" for l, t in zip(labels, totals)], fontsize=9)
    ax.set_yticks(range(len(PIPES)))
    ax.set_yticklabels(PIPES, fontsize=9)

    for i in range(len(PIPES)):
        for j in range(n):
            v = data[i, j]
            color = 'white' if v > 55 else 'black'
            ax.text(j, i, f'{v:.1f}%', ha='center', va='center', fontsize=8, color=color)

    plt.colorbar(im, ax=ax, label='利用率 (%)', shrink=0.8)
    ax.set_title(f'PIPE 利用率热力图 — {op_name}', fontsize=11)
    ax.set_xlabel('算子规格（总耗时）', fontsize=9)
    ax.set_ylabel('PIPE 类型', fontsize=9)
    plt.tight_layout()
    plt.savefig(output, dpi=150, bbox_inches='tight')
    print(f"图片已保存：{output}")
    print(f"OUTPUT={output}")


def plot_stacked(case_dirs, labels, op_name, output):
    n = len(case_dirs)
    times_per_case = []
    totals = []
    for d in case_dirs:
        _, times, total = load_pipe(d)
        times_per_case.append(times)
        totals.append(total)

    x = np.arange(n)
    width = 0.5

    fig, ax = plt.subplots(figsize=(max(5, n * 1.8 + 1.5), 5))

    bottoms = np.zeros(n)
    for p in PIPES:
        vals = np.array([t[p] for t in times_per_case])
        bars = ax.bar(x, vals, width, bottom=bottoms,
                      color=PIPE_COLORS[p], label=p, alpha=0.88)
        for j, (v, b) in enumerate(zip(vals, bottoms)):
            if v > 0.05:
                ax.text(j, b + v / 2, f'{v:.2f}', ha='center', va='center',
                        fontsize=7.5, color='white' if p in ('MTE2', 'MTE3') else 'black')
        bottoms += vals

    # 总时间标注在顶部
    for j, t in enumerate(totals):
        ax.text(j, t + 0.05, f'总 {t:.2f} μs', ha='center', va='bottom', fontsize=8)

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylabel('时间 (μs)', fontsize=10)
    ax.set_title(f'通算流水时间分解 — {op_name}', fontsize=11)
    ax.legend(fontsize=8, loc='upper left')
    ax.grid(axis='y', alpha=0.25)
    plt.tight_layout()
    plt.savefig(output, dpi=150, bbox_inches='tight')
    print(f"图片已保存：{output}")
    print(f"OUTPUT={output}")


def main():
    ap = argparse.ArgumentParser(
        description='PIPE 利用率分析工具（Ascend 310B4）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    ap.add_argument('--mode', choices=['heatmap', 'stacked'], required=True,
                    help='heatmap=热力图(01)  stacked=堆叠柱状图(04)')
    ap.add_argument('--case', nargs=4, action='append',
                    metavar=('DIR', 'ELEMENTS', 'BLOCKDIM', 'LABEL'),
                    help='案例（可重复）：目录 [占位] [占位] 标签')
    ap.add_argument('--op-name',  default='Operator',     help='算子名称（图标题）')
    ap.add_argument('--output',   default='pipe_plot.png', help='输出图片路径')
    args = ap.parse_args()

    if not args.case:
        ap.error("请至少提供一个 --case DIR LABEL")

    case_dirs, labels = [], []
    for d, _e, _b, l in args.case:
        case_dirs.append(d)
        labels.append(l or os.path.basename(d.rstrip('/\\')))

    print(f"\n{'='*50}")
    print(f"算子：{args.op_name}  模式：{args.mode}")
    for d, l in zip(case_dirs, labels):
        try:
            ratios, times, total = load_pipe(d)
            print(f"  [{l}]  总耗时={total:.3f}μs  "
                  f"Scalar={ratios['Scalar']*100:.1f}%  "
                  f"MTE2={ratios['MTE2']*100:.1f}%  "
                  f"MTE3={ratios['MTE3']*100:.1f}%")
        except (FileNotFoundError, ValueError) as e:
            print(f"  [{l}] 警告：{e}")
    print(f"{'='*50}\n")

    if args.mode == 'heatmap':
        plot_heatmap(case_dirs, labels, args.op_name, args.output)
    else:
        plot_stacked(case_dirs, labels, args.op_name, args.output)


if __name__ == '__main__':
    main()
