#!/usr/bin/env python3
"""
agentry-run-report CLI.

Builds a unified report from a run directory produced by
`agentry-run-recorder` and emits it as Markdown, JSON, or both.

Usage:
    python3 agentry-run-report.py --run-dir runs/run-001 --format markdown
    python3 agentry-run-report.py --run-dir runs/run-001 --format json
    python3 agentry-run-report.py --run-dir runs/run-001 --format both \
            --md-out report.md --json-out report.json

Exit codes:
    0  - report built successfully
    2  - report built but the events.jsonl chain is broken (still emits output)
    3  - report built but the run did not complete (status != success/complete)
    1  - bad arguments / unreadable run dir
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from agentry_run_report import (  # noqa: E402
    ReportError,
    load_run,
    render_markdown,
    to_json,
)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="agentry-run-report",
        description=(
            "Unified Agentry run report. Composes the recorder's events, "
            "trajectories, handoff ledger, and fiscal log into one Markdown "
            "+ JSON deliverable."
        ),
    )
    p.add_argument(
        "--run-dir",
        required=True,
        help="Path to a directory written by agentry-run-recorder",
    )
    p.add_argument(
        "--format",
        choices=("markdown", "json", "both"),
        default="markdown",
        help="Output format (default: markdown)",
    )
    p.add_argument(
        "--md-out",
        help="Write markdown to this file (default: stdout)",
    )
    p.add_argument(
        "--json-out",
        help="Write JSON to this file (default: stdout if --format json/both)",
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help="Exit 2 on chain break and 3 on incomplete runs (non-strict only warns).",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])

    try:
        report = load_run(args.run_dir)
    except ReportError as e:
        print(f"agentry-run-report: {e}", file=sys.stderr)
        return 1

    md = render_markdown(report)
    js = to_json(report)

    if args.format in ("markdown", "both"):
        if args.md_out:
            Path(args.md_out).write_text(md, encoding="utf-8")
            print(f"wrote {args.md_out}", file=sys.stderr)
        else:
            sys.stdout.write(md)
    if args.format in ("json", "both"):
        if args.json_out:
            Path(args.json_out).write_text(js, encoding="utf-8")
            print(f"wrote {args.json_out}", file=sys.stderr)
        elif args.format == "json":
            sys.stdout.write(js)

    # exit code logic
    if not report.chain.ok:
        if args.strict:
            return 2
        print(
            f"warning: events.jsonl chain broken at seq {report.chain.broken_at_seq}",
            file=sys.stderr,
        )
    if report.status.lower() not in ("success", "complete", "completed", "ok", "succeeded"):
        if args.strict:
            return 3
        print(
            f"warning: run did not complete (status={report.status})",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
