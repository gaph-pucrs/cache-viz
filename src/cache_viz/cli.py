"""Command-line interface: ``cache-viz LOG.csv...`` opens the viewer, ``-o report.html`` writes the HTML report."""
from __future__ import annotations

import argparse
from pathlib import Path

from .analysis import CacheAnalysis
from .report import HtmlReport, ReportParams

MAX_MESSAGES = 20


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="cache-viz",
        description="Show the timeline and performance of one or more caches (or write an HTML report with -o).",
    )
    ap.add_argument("logs", nargs="+", type=Path, help="DMDebug CSV logs (e.g. debug/testbench.pe.dcache_ctrl.u_debug.csv)")
    ap.add_argument("-o", "--out", type=Path, help="write an HTML report to this file instead of opening the viewer")
    ap.add_argument("--lines", type=int, help="number of cache lines (default: next power of two above the highest line seen)")
    ap.add_argument("--period", type=float, default=0, help="clock period in TIME units (shows cycles)")
    ap.add_argument("--block-bytes", type=int, default=0, help="block size in bytes (memory traffic)")
    ap.add_argument("--miss-penalty", type=float, default=0, help="FILL penalty in cycles (stall estimate)")
    ap.add_argument("--wb-penalty", type=float, default=0, help="write-back penalty in cycles")
    return ap


def print_status(analysis: CacheAnalysis) -> None:
    log, anomalies = analysis.log, analysis.replay.anomalies
    inferred = " (inferred)" if log.nlines_inferred else ""
    print(f"{log.path.name}: {log.nlines} lines{inferred}, {len(log.events)} events, {len(anomalies)} anomalies")
    for msg in anomalies[:MAX_MESSAGES]:
        print("   -", msg)


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.lines is not None and args.lines < 1:
        ap.error("--lines must be at least 1")

    caches = []
    for path in args.logs:
        try:
            analysis = CacheAnalysis.from_file(path, args.lines)
        except (OSError, ValueError) as e:
            ap.error(str(e))
        print_status(analysis)
        caches.append(analysis)

    params = ReportParams(args.period, args.block_bytes, args.miss_penalty, args.wb_penalty)
    if args.out:
        HtmlReport(caches, params).write(args.out)
        print(f"-> {args.out}")
        return 0
    try:
        from .gui import show
    except ImportError as e:
        ap.error(f"the viewer needs tkinter ({e}); use -o FILE.html for the HTML report")
    show(caches, params)
    return 0
