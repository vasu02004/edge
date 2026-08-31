"""Summarize a stats.csv produced by main.py's periodic STATS logging: avg/peak/min
for CPU%, RAM (RSS), temp, fps, and latency over the full run, plus hourly RSS,
CPU%, and temp trends to catch slow growth or drift a single avg/peak/min summary
would hide, and a check for any Pi thermal-throttle events during the run.

Run with: python tools/analyze_stats.py [path/to/stats.csv]
"""
import csv
import sys
from collections import defaultdict
from datetime import datetime


def to_float(s):
    return float(s) if s else None


def hourly_trend(label, rows, start, field, unit):
    print(f"\nHourly {label} trend (catches slow growth an overall avg/peak/min would hide):")
    hourly = defaultdict(list)
    for r in rows:
        ts = datetime.strptime(r["timestamp"], "%Y-%m-%d %H:%M:%S")
        hour_bucket = int((ts - start).total_seconds() // 3600)
        val = to_float(r[field])
        if val is not None:
            hourly[hour_bucket].append(val)
    if not hourly:
        print("  no data")
        return
    for h in sorted(hourly):
        vals = hourly[h]
        print(
            f"  hour {h:3d}: avg={sum(vals) / len(vals):7.1f}{unit}  "
            f"peak={max(vals):7.1f}{unit}  best={min(vals):7.1f}{unit}"
        )


def summarize(label, values):
    values = [v for v in values if v is not None]
    if not values:
        print(f"  {label:20s} no data")
        return
    print(
        f"  {label:20s} avg={sum(values) / len(values):8.1f}  "
        f"peak={max(values):8.1f}  best={min(values):8.1f}"
    )


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "stats.csv"
    rows = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            rows.append(row)

    if not rows:
        print(f"{path}: no rows")
        return

    start = datetime.strptime(rows[0]["timestamp"], "%Y-%m-%d %H:%M:%S")
    end = datetime.strptime(rows[-1]["timestamp"], "%Y-%m-%d %H:%M:%S")
    duration_h = (end - start).total_seconds() / 3600

    print(f"{path}: {len(rows)} samples, {start} -> {end} ({duration_h:.1f}h)\n")

    print("Overall:")
    summarize("cpu_pct (process)", [to_float(r["cpu_pct"]) for r in rows])
    summarize("system_cpu_pct", [to_float(r["system_cpu_pct"]) for r in rows])
    summarize("rss_mb (process)", [to_float(r["rss_mb"]) for r in rows])
    summarize("mem_available_mb", [to_float(r["mem_available_mb"]) for r in rows])
    summarize("mem_used_pct", [to_float(r["mem_used_pct"]) for r in rows])
    summarize("cpu_temp_c", [to_float(r["cpu_temp_c"]) for r in rows])
    summarize("fps", [to_float(r["fps"]) for r in rows])
    summarize("aruco_avg_ms", [to_float(r["aruco_avg_ms"]) for r in rows])
    summarize("yolo_avg_ms", [to_float(r["yolo_avg_ms"]) for r in rows])
    print(f"  {'grab_fails (total)':20s} {sum(int(r['grab_fails']) for r in rows)}")

    proc_cpu = [to_float(r["cpu_pct"]) for r in rows]
    sys_cpu = [to_float(r["system_cpu_pct"]) for r in rows]
    gaps = [s - p for p, s in zip(proc_cpu, sys_cpu) if p is not None and s is not None]
    if gaps:
        avg_gap = sum(gaps) / len(gaps)
        if avg_gap > 15:
            print(
                f"\n  NOTE: system_cpu_pct averages {avg_gap:.1f} points higher than this "
                "process's cpu_pct — something else on the Pi is consuming meaningful CPU."
            )

    throttle_events = {r["throttled_hex"] for r in rows if r["throttled_hex"] and r["throttled_hex"] != "0x0"}
    if throttle_events:
        print(f"\n  WARNING: throttled_hex was non-zero at some point: {throttle_events}")
        print("  (Pi under-voltage or thermal throttling occurred — CPU/latency numbers may be understated.)")
    else:
        print("\n  No throttling detected (throttled_hex was 0x0 or n/a throughout).")

    hourly_trend("RSS", rows, start, "rss_mb", "MB")
    hourly_trend("CPU% (process)", rows, start, "cpu_pct", "%")
    hourly_trend("Temp", rows, start, "cpu_temp_c", "C")


if __name__ == "__main__":
    main()
