#!/usr/bin/env python3
"""
Roofline 分析工具 - 适用于 Ascend 310B4
结合 msprof 采集的矩阵 FLOP（aic_cube_fops）与手算的向量 FLOP，画 Roofline 图。

用法：
  python roofline_plot.py \\
      --data-dir path/to/dim8_v2 \\
      --total-elements 16384 \\
      --blockdim 8 \\
      --vec-flop-per-elem 1 \\
      --op-name "AddCustom fp16 (dim8)"

双数据集对比：
  python roofline_plot.py \\
      --data-dir path/to/dim8_v2 --label "dim8" \\
      --data-dir2 path/to/dim1_v2 --label2 "dim1" \\
      --total-elements 16384 --blockdim 8 \\
      --total-elements2 16384 --blockdim2 1 \\
      --vec-flop-per-elem 1 \\
      --op-name "AddCustom fp16"
"""

import argparse
import csv
import os
import sys

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

try:
    import matplotlib
    matplotlib.use('Agg')  # 无 GUI 环境也能保存图片
    import matplotlib.pyplot as plt
    import numpy as np
except ImportError:
    print("请先安装依赖：pip install matplotlib numpy")
    sys.exit(1)

plt.rcParams['font.family'] = ['Microsoft YaHei', 'SimHei', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False

# ── 310B4 默认硬件参数 ────────────────────────────────────────────────────────
HW_PEAK_FLOPS_FP16 = 4e12   # 4 TFLOPS fp16（官方规格）
HW_PEAK_BW         = 34e9   # ~34 GB/s LPDDR4x（实测偏低，理论值）


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        return [row for row in reader]


def to_float(val, default=0.0):
    try:
        v = float(str(val).strip())
        return default if (v != v) else v   # NaN → default
    except (TypeError, ValueError):
        return default


def load_blocks(data_dir, total_elements, blockdim, vec_flop_per_elem):
    """
    从 msprof 输出目录读取 Memory.csv 和 ArithmeticUtilization.csv，
    返回每个 block 的 (算术强度, 实际性能, block_id, 时间us) 列表。
    """
    mem_rows   = read_csv(os.path.join(data_dir, 'Memory.csv'))
    arith_rows = read_csv(os.path.join(data_dir, 'ArithmeticUtilization.csv'))

    if not mem_rows:
        raise FileNotFoundError(f"找不到 Memory.csv：{data_dir}")

    elems_per_block   = total_elements / blockdim
    vec_flop_per_block = vec_flop_per_elem * elems_per_block

    points = []
    arith_idx = 0
    for row in mem_rows:
        # 只取 AIC 行（sub_block_id = cube0 或空）
        sub = row.get('sub_block_id', '').strip()
        if sub not in ('', 'cube0'):
            continue

        time_us = to_float(row.get('aic_time(us)', 0))
        if time_us <= 0:
            continue

        read_kb  = to_float(row.get('read_main_memory_datas(KB)', 0))
        write_kb = to_float(row.get('write_main_memory_datas(KB)', 0))
        total_bytes = (read_kb + write_kb) * 1024
        if total_bytes <= 0:
            continue

        # 矩阵 FLOP（msprof 量的）
        cube_fops = 0.0
        if arith_idx < len(arith_rows):
            cube_fops = to_float(arith_rows[arith_idx].get('aic_cube_fops', 0))
            arith_idx += 1

        total_flop = cube_fops + vec_flop_per_block
        ai   = total_flop / total_bytes          # FLOP/Byte
        perf = total_flop / (time_us * 1e-6)     # FLOP/s

        block_id = row.get('block_id', str(len(points)))
        points.append({
            'ai':       ai,
            'perf':     perf,
            'block_id': block_id,
            'time_us':  time_us,
            'cube_fops': cube_fops,
            'vec_flop':  vec_flop_per_block,
            'bytes':     total_bytes,
            'gm_read_kb': read_kb,
            'gm_write_kb': write_kb,
            'cache_read_kb': (
                to_float(row.get('GM_to_L1_datas(KB)', 0)) +
                to_float(row.get('GM_to_UB_datas(KB)', 0))
            ),
            'cache_write_kb': (
                to_float(row.get('L1_to_GM_datas(KB)(estimate)', 0)) +
                to_float(row.get('UB_to_GM_datas(KB)', 0))
            ),
        })

    return points


def draw_roofline(ax, peak_flops, peak_bw, all_point_sets, colors, labels):
    """在 ax 上画屋顶线和数据点。"""
    ridge = peak_flops / peak_bw   # FLOP/Byte

    # 确定 x 轴范围
    all_ais = [p['ai'] for pts in all_point_sets for p in pts]
    min_ai = min(all_ais) if all_ais else 0.01
    x = np.logspace(np.log10(min_ai * 0.05), np.log10(ridge * 20), 400)

    # 屋顶线
    roof_mem     = peak_bw    * x
    roof_compute = np.full_like(x, peak_flops)
    roof         = np.minimum(roof_mem, roof_compute)

    ax.loglog(x, roof_mem,     'b--', lw=1.2, alpha=0.7,
              label=f'Memory BW  {peak_bw/1e9:.0f} GB/s')
    ax.loglog(x, roof_compute, 'r--', lw=1.2, alpha=0.7,
              label=f'Compute  {peak_flops/1e12:.0f} TFLOPS fp16')
    ax.loglog(x, roof,         'k-',  lw=2,
              label='Roofline (Ascend 310B4)')

    # 脊点标记
    ax.axvline(x=ridge, color='gray', ls=':', lw=1)
    ax.text(ridge * 1.08, peak_flops * 0.5,
            f'Ridge\n{ridge:.0f} FLOP/B',
            color='gray', fontsize=8, va='center')

    # 数据点
    for pts, color, label in zip(all_point_sets, colors, labels):
        xs = [p['ai']   for p in pts]
        ys = [p['perf'] for p in pts]
        ax.scatter(xs, ys, s=55, color=color, zorder=5, label=label)
        for p in pts:
            bid = p['block_id']
            # Block 6/7 常出现异常，用 * 标注
            marker = '*' if str(bid) in ('6', '7') else ''
            ax.annotate(
                f"B{bid}{marker}\n{p['time_us']:.1f}μs",
                (p['ai'], p['perf']),
                textcoords='offset points', xytext=(6, 3),
                fontsize=6.5, color=color
            )

    ax.set_xlabel('Arithmetic Intensity  (FLOP / Byte)', fontsize=11)
    ax.set_ylabel('Performance  (FLOP / s)',             fontsize=11)
    ax.grid(True, which='both', alpha=0.25)
    ax.legend(fontsize=8, loc='upper left')

    # Y 轴人类可读格式
    def fmt_y(v, _):
        if   v >= 1e12: return f'{v/1e12:.1f}T'
        elif v >= 1e9:  return f'{v/1e9:.0f}G'
        elif v >= 1e6:  return f'{v/1e6:.0f}M'
        else:           return f'{v:.0f}'
    ax.yaxis.set_major_formatter(plt.FuncFormatter(fmt_y))

    return ridge


def aggregate_points(points, label):
    """把一个 msprof 目录里的 block 行汇总成官方风格图上的一个算子点。"""
    total_flop = sum(p['cube_fops'] + p['vec_flop'] for p in points)
    total_bytes = sum(p['bytes'] for p in points)
    total_time_us = sum(p['time_us'] for p in points)
    if total_flop <= 0 or total_bytes <= 0 or total_time_us <= 0:
        raise ValueError("汇总点缺少有效 FLOP、访存字节数或耗时")
    return {
        'label': label,
        'ai': total_flop / total_bytes,
        'perf': total_flop / (total_time_us * 1e-6),
        'time_us': total_time_us,
        'flop': total_flop,
        'gm_bytes': total_bytes,
        'gm_read_kb': sum(p.get('gm_read_kb', 0.0) for p in points),
        'gm_write_kb': sum(p.get('gm_write_kb', 0.0) for p in points),
        'cache_read_kb': sum(p.get('cache_read_kb', 0.0) for p in points),
        'cache_write_kb': sum(p.get('cache_write_kb', 0.0) for p in points),
        'block_count': len(points),
    }


def _nice_log_bounds(value, low_factor, high_factor, floor=0.01):
    low = max(floor, value * low_factor)
    high = max(low * 10, value * high_factor)
    return low, high


def draw_official_single(ax, point, peak_flops, peak_bw, peak_l2_bw, op_name):
    """
    画接近官方文档 Roofline 截图的单次摘要图。
    这里的 L2 线用可配置片上缓存带宽近似；当前 CSV 主要提供 GM/UB/L1 侧数据。
    """
    x0 = max(point['ai'], 1e-6)
    y0_tops = max(point['perf'] / 1e12, 1e-6)
    peak_tops = peak_flops / 1e12
    x_min, x_max = _nice_log_bounds(x0, 0.02, 200, floor=0.01)
    gm_ridge = peak_flops / peak_bw
    l2_ridge = peak_flops / peak_l2_bw
    x_max = max(x_max, gm_ridge * 3, l2_ridge * 3, 10)
    y_min, y_max = _nice_log_bounds(y0_tops, 0.03, 500, floor=0.01)
    y_max = max(y_max, peak_tops * 1.6)

    x = np.logspace(np.log10(x_min), np.log10(x_max), 500)
    gm_roof = np.minimum(peak_flops, peak_bw * x) / 1e12
    l2_roof = np.minimum(peak_flops, peak_l2_bw * x) / 1e12

    ax.set_facecolor('#f8fafc')
    ax.loglog(x, gm_roof, color='#cfd3d8', lw=2.0, label='GM Read + Write')
    ax.loglog(x, l2_roof, color='#4db08b', lw=2.0, label='L2 Read + Write')
    ax.scatter([x0], [y0_tops], s=145, color='#4db08b', edgecolor='white',
               linewidth=1.2, zorder=5)

    # 官方图那种红色读数辅助线
    ax.vlines(x0, y_min, min(y0_tops, y_max), colors='red', lw=1.4)
    ax.hlines(y0_tops, x_min, min(x0, x_max), colors='red', lw=1.4)
    ax.text(x0 * 1.03, max(y_min * 1.2, y0_tops / 8), 'a',
            color='red', fontsize=9, va='bottom')
    ax.text(max(x_min * 1.15, x0 / 6), y0_tops * 1.08, 'b',
            color='#1976d2', fontsize=9, va='bottom')

    ax.axvline(gm_ridge, color='#9aa8b6', ls=':', lw=0.9)
    ax.text(gm_ridge * 1.05, peak_tops * 1.18,
            f'Cube_FP({100.0:.6f}%)',
            color='#667085', fontsize=9, weight='bold', ha='left', va='bottom')

    info = (
        f"{point['label']}\n"
        f"带宽：GM {peak_bw/1e9:.0f}GB/s，L2 {peak_l2_bw/1e12:.1f}TB/s\n"
        f"算术强度：{point['ai']:.4f} OPs/Byte\n"
        f"性能：{point['perf']/1e12:.6f} TOPs/s\n"
        f"块数：{point['block_count']}，耗时合计：{point['time_us']:.3f} μs"
    )
    ax.annotate(
        info, xy=(x0, y0_tops), xytext=(18, -16), textcoords='offset points',
        fontsize=8.5, color='#667085', ha='left', va='top',
        bbox=dict(boxstyle='round,pad=0.45', fc='white', ec='#e5e7eb', alpha=0.96),
    )

    ax.set_title('GM/L2', fontsize=13, color='#344054', weight='bold', pad=46)
    ax.set_xlabel('OPs/Byte', color='#7b8da3')
    ax.set_ylabel('TOPs/s', color='#7b8da3', rotation=0)
    ax.yaxis.set_label_coords(0.0, 1.04)
    ax.xaxis.set_label_coords(1.0, -0.02)
    ax.xaxis.label.set_horizontalalignment('right')
    ax.grid(True, which='both', color='#d7e0ea', lw=0.7)
    ax.legend(loc='upper center', bbox_to_anchor=(0.5, 1.12),
              ncol=2, frameon=False, fontsize=8)
    ax.set_xlim(x_min, x_max)
    ax.set_ylim(y_min, y_max)
    ax.tick_params(colors='#8a94a3', labelsize=8)
    for spine in ('top', 'right'):
        ax.spines[spine].set_visible(False)
    ax.spines['left'].set_color('#8a94a3')
    ax.spines['bottom'].set_color('#8a94a3')

    fig_note = (
        f"{op_name} | GM读写={point['gm_read_kb'] + point['gm_write_kb']:.1f}KB, "
        f"片上读写近似={point['cache_read_kb'] + point['cache_write_kb']:.1f}KB"
    )
    ax.text(0.0, -0.18, fig_note, transform=ax.transAxes,
            fontsize=8, color='#667085', ha='left', va='top')


# ── 主程序 ────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description='Roofline 分析工具（Ascend 310B4）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    # 第一个数据集（--data-dir 和 --case 二选一）
    ap.add_argument('--data-dir',         default=None,  help='msprof 输出目录（含 Memory.csv）')
    ap.add_argument('--total-elements',   default=None,  type=int,   help='算子总元素数')
    ap.add_argument('--blockdim',         default=1,     type=int,   help='blockdim（默认 1）')
    ap.add_argument('--vec-flop-per-elem',default=1.0,   type=float, help='每元素向量 FLOP（默认 1）')
    ap.add_argument('--label',            default='',                help='图例标签')
    # 第二个数据集（可选，用于对比）
    ap.add_argument('--data-dir2',        default=None,  help='第二个 msprof 目录（可选）')
    ap.add_argument('--total-elements2',  default=None,  type=int)
    ap.add_argument('--blockdim2',        default=1,     type=int)
    ap.add_argument('--label2',           default='',                help='第二数据集图例标签')
    # 第三个数据集（可选，用于三规格对比）
    ap.add_argument('--data-dir3',        default=None,  help='第三个 msprof 目录（可选）')
    ap.add_argument('--total-elements3',  default=None,  type=int)
    ap.add_argument('--blockdim3',        default=1,     type=int)
    ap.add_argument('--label3',           default='',                help='第三数据集图例标签')
    # 多案例模式：--case DIR ELEMENTS BLOCKDIM LABEL（可重复，与 --data-dir 二选一）
    ap.add_argument('--case', nargs=4, action='append',
                    metavar=('DIR', 'ELEMENTS', 'BLOCKDIM', 'LABEL'),
                    help='案例（可重复）：目录 总元素数 blockdim 标签')
    # 图表参数
    ap.add_argument('--op-name',          default='Operator',        help='算子名称（图标题）')
    ap.add_argument('--peak-flops',       default=HW_PEAK_FLOPS_FP16, type=float,
                    help=f'硬件峰值算力 FLOP/s（默认 {HW_PEAK_FLOPS_FP16:.0e}）')
    ap.add_argument('--peak-bw',          default=HW_PEAK_BW,         type=float,
                    help=f'硬件峰值带宽 B/s（默认 {HW_PEAK_BW:.0e}）')
    ap.add_argument('--peak-l2-bw',       default=4e12,               type=float,
                    help='片上缓存/L2 近似带宽 B/s（官方风格单次图使用，默认 4e12）')
    ap.add_argument('--style',            default='compare',
                    choices=['compare', 'official-single'],
                    help='compare=多点对比图；official-single=官方风格单次摘要图')
    ap.add_argument('--output',           default='roofline.png',    help='输出图片路径')
    args = ap.parse_args()

    if not args.case and not args.data_dir:
        ap.error("请提供 --data-dir（单/双/三数据集模式）或 --case（多案例模式）之一")
    if not args.case and args.total_elements is None:
        ap.error("使用 --data-dir 模式时必须同时提供 --total-elements")

    # 颜色池（最多支持 8 个案例）
    COLOR_POOL = ['#2196F3', '#FF5722', '#4CAF50', '#9C27B0',
                  '#FF9800', '#00BCD4', '#F44336', '#795548']

    # ── 多案例模式（--case 重复参数）────────────────────────────────────────────
    if args.case:
        point_sets, labels = [], []
        for dir_c, elem_c, bdim_c, lbl_c in args.case:
            try:
                pts = load_blocks(dir_c, int(elem_c), int(bdim_c), args.vec_flop_per_elem)
            except (FileNotFoundError, ValueError) as e:
                print(f"警告：案例 {dir_c} 加载失败：{e}")
                continue
            point_sets.append(pts)
            labels.append(lbl_c or os.path.basename(dir_c.rstrip('/\\')))
        if not point_sets:
            print("错误：没有成功加载任何案例"); sys.exit(1)
        colors = COLOR_POOL[:len(point_sets)]

    # ── 兼容旧式 --data-dir 参数 ────────────────────────────────────────────────
    else:
        try:
            pts1 = load_blocks(args.data_dir, args.total_elements,
                               args.blockdim, args.vec_flop_per_elem)
        except FileNotFoundError as e:
            print(f"错误：{e}"); sys.exit(1)

        label1 = args.label or os.path.basename(args.data_dir.rstrip('/\\'))
        point_sets = [pts1]
        labels     = [label1]

        for dir_arg, elems_arg, bdim_arg, lbl_arg in [
            (args.data_dir2, args.total_elements2, args.blockdim2, args.label2),
            (args.data_dir3, args.total_elements3, args.blockdim3, args.label3),
        ]:
            if not dir_arg:
                continue
            total_n = elems_arg or args.total_elements
            try:
                pts_n = load_blocks(dir_arg, total_n, bdim_arg, args.vec_flop_per_elem)
            except FileNotFoundError as e:
                print(f"警告：数据集加载失败：{e}")
                continue
            lbl_n = lbl_arg or os.path.basename(dir_arg.rstrip('/\\'))
            point_sets.append(pts_n)
            labels.append(lbl_n)

        colors = COLOR_POOL[:len(point_sets)]

    if args.style == 'official-single' and len(point_sets) != 1:
        print("错误：official-single 只适合一个 msprof 目录；多规格对比请使用默认 compare 风格")
        sys.exit(1)

    # 打印汇总
    print(f"\n{'='*55}")
    print(f"算子：{args.op_name}")
    print(f"硬件：Ascend 310B4  峰值算力={args.peak_flops/1e12:.0f}TFLOPS  "
          f"峰值带宽={args.peak_bw/1e9:.0f}GB/s")
    ridge = args.peak_flops / args.peak_bw
    print(f"脊点：{ridge:.1f} FLOP/Byte")
    for pts, label in zip(point_sets, labels):
        print(f"\n[{label}]")
        for p in pts:
            status = 'memory-bound' if p['ai'] < ridge else 'compute-bound'
            print(f"  Block {p['block_id']:>2}: AI={p['ai']:.4f} FLOP/B  "
                  f"Perf={p['perf']/1e9:.2f} GFLOP/s  "
                  f"t={p['time_us']:.1f}μs  ({status})")
    print(f"{'='*55}\n")

    # 画图
    if args.style == 'official-single':
        point = aggregate_points(point_sets[0], labels[0])
        fig, ax = plt.subplots(figsize=(12, 5.2))
        draw_official_single(
            ax, point, args.peak_flops, args.peak_bw, args.peak_l2_bw, args.op_name
        )
    else:
        fig, ax = plt.subplots(figsize=(9, 6))
        draw_roofline(ax, args.peak_flops, args.peak_bw, point_sets, colors, labels)
        subtitle = (f"vec_flop/elem={args.vec_flop_per_elem}  |  "
                    f"cube_fops from msprof  |  bytes from Memory.csv")
        ax.set_title(f'Roofline — {args.op_name}\n{subtitle}', fontsize=10)

    plt.tight_layout()
    plt.savefig(args.output, dpi=150, bbox_inches='tight')
    print(f"图片已保存：{args.output}")
    # 工具箱插件协议：成功时 stdout 最后一行输出生成物路径
    print(f"OUTPUT={args.output}")


if __name__ == '__main__':
    main()
