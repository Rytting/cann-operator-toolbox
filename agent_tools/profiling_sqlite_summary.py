#!/usr/bin/env python3
"""Summarize exported CANN msprof sqlite data.

Usage:
  python agent_tools/profiling_sqlite_summary.py <profile_extract_dir_or_archive>

The script accepts either an extracted profiling directory or a .tar.gz archive.
It prints the key tables that matter for the SetBlockDim experiments:
ge_summary.block_dim, AI_CORE task_time durations, op_counter op_report, and
long CANN_API calls when a host msprof database is present.
"""

from __future__ import annotations

import argparse
import sqlite3
import statistics
import tarfile
import tempfile
from pathlib import Path


def pct(values: list[float], percent: float) -> float | None:
    if not values:
        return None
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * percent / 100
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    if lo == hi:
        return xs[lo]
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def fmt_us(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f} us"


def extract_if_needed(path: Path) -> Path:
    if path.is_dir():
        return path
    if path.suffixes[-2:] == [".tar", ".gz"] or path.name.endswith(".tgz"):
        out = Path(tempfile.mkdtemp(prefix="profiling_sqlite_"))
        with tarfile.open(path, "r:gz") as tf:
            tf.extractall(out, filter="data")
        return out
    raise ValueError(f"Expected directory or .tar.gz archive: {path}")


def table_exists(con: sqlite3.Connection, table: str) -> bool:
    row = con.execute(
        "select 1 from sqlite_master where type='table' and name=?", (table,)
    ).fetchone()
    return row is not None


def summarize_ai_core_db(db: Path) -> None:
    print(f"\n## {db}")
    with sqlite3.connect(db) as con:
        if table_exists(con, "ge_summary"):
            cols = [r[1] for r in con.execute("pragma table_info(ge_summary)")]
            wanted = [c for c in ["op_name", "op_type", "block_dim", "task_type"] if c in cols]
            if wanted:
                query = "select distinct " + ", ".join(wanted) + " from ge_summary limit 10"
                print("ge_summary:")
                for row in con.execute(query):
                    print("  " + ", ".join(f"{k}={v}" for k, v in zip(wanted, row)))
        if table_exists(con, "task_time"):
            cols = [r[1] for r in con.execute("pragma table_info(task_time)")]
            if {"duration_time", "task_type"}.issubset(cols):
                rows = con.execute(
                    "select duration_time from task_time where task_type='AI_CORE' order by start_time"
                ).fetchall()
                durations = [r[0] / 1000.0 for r in rows]
                if durations:
                    stable = durations[1:] if len(durations) > 1 else durations
                    print(
                        "AI_CORE task_time:"
                        f" count={len(durations)} total={fmt_us(sum(durations))}"
                        f" avg={fmt_us(statistics.mean(durations))}"
                        f" min={fmt_us(min(durations))} max={fmt_us(max(durations))}"
                        f" p50={fmt_us(pct(durations, 50))}"
                    )
                    if stable is not durations:
                        print(
                            "AI_CORE stable excluding first:"
                            f" count={len(stable)} total={fmt_us(sum(stable))}"
                            f" avg={fmt_us(statistics.mean(stable))}"
                            f" min={fmt_us(min(stable))} max={fmt_us(max(stable))}"
                            f" p50={fmt_us(pct(stable, 50))}"
                        )


def summarize_op_counter(db: Path) -> None:
    print(f"\n## {db}")
    with sqlite3.connect(db) as con:
        if not table_exists(con, "op_report"):
            return
        cols = [r[1] for r in con.execute("pragma table_info(op_report)")]
        print("op_report:")
        for row in con.execute("select * from op_report"):
            d = dict(zip(cols, row))
            if "total_time" in d:
                d["total_time_us"] = d["total_time"] / 1000.0
            if "min" in d:
                d["min_us"] = d["min"] / 1000.0
            if "avg" in d:
                d["avg_us"] = d["avg"] / 1000.0
            if "max" in d:
                d["max_us"] = d["max"] / 1000.0
            keep = [
                "op_type",
                "core_type",
                "occurrences",
                "total_time_us",
                "avg_us",
                "min_us",
                "max_us",
            ]
            print("  " + ", ".join(f"{k}={d[k]}" for k in keep if k in d))


def summarize_host_msprof(db: Path) -> None:
    with sqlite3.connect(db) as con:
        if not table_exists(con, "CANN_API"):
            return
        print(f"\n## {db}")
        strings: dict[int, str] = {}
        if table_exists(con, "STRING_IDS"):
            cols = [r[1] for r in con.execute("pragma table_info(STRING_IDS)")]
            for row in con.execute("select * from STRING_IDS"):
                d = dict(zip(cols, row))
                sid = d.get("id")
                value = d.get("value", d.get("data", d.get("name")))
                if sid is not None and value is not None:
                    strings[int(sid)] = str(value)
        cols = [r[1] for r in con.execute("pragma table_info(CANN_API)")]
        rows = []
        for row in con.execute("select * from CANN_API"):
            d = dict(zip(cols, row))
            if "startNs" not in d or "endNs" not in d or "name" not in d:
                continue
            name = strings.get(d["name"], str(d["name"]))
            dur_ms = (d["endNs"] - d["startNs"]) / 1e6
            rows.append((dur_ms, name, d.get("connectionId", "")))
        print("CANN_API longest calls:")
        for dur_ms, name, conn in sorted(rows, reverse=True)[:12]:
            print(f"  {dur_ms:10.3f} ms  conn={conn}  {name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    if not args.path.exists():
        print(f"ERROR: 找不到输入路径: {args.path}")
        raise SystemExit(1)
    root = extract_if_needed(args.path)
    for db in sorted(root.rglob("ai_core_op_summary.db")):
        summarize_ai_core_db(db)
    for db in sorted(root.rglob("op_counter.db")):
        summarize_op_counter(db)
    for db in sorted(root.rglob("msprof_*.db")):
        summarize_host_msprof(db)


if __name__ == "__main__":
    main()
