"""
Module entry point so `python3 -m agentry_run_report` works.
"""

from __future__ import annotations

import sys

from . import __version__
from .report import (
    ReportError,
    load_run,
    render_markdown,
    to_json,
)


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(
            f"agentry-run-report {__version__}\n"
            "Usage: python3 -m agentry_run_report <run-dir> [--json] [--strict]\n"
            "       python3 -m agentry_run_report --version",
            file=sys.stderr,
        )
        return 1 if len(sys.argv) >= 2 and sys.argv[1] in ("-h", "--help") else 0

    if "--version" in sys.argv[1:]:
        print(f"agentry-run-report {__version__}")
        return 0

    args = sys.argv[1:]
    run_dir = args[0]
    as_json = "--json" in args
    strict = "--strict" in args

    try:
        report = load_run(run_dir)
    except ReportError as e:
        print(f"agentry-run-report: {e}", file=sys.stderr)
        return 1

    if as_json:
        sys.stdout.write(to_json(report))
    else:
        sys.stdout.write(render_markdown(report))

    if not report.chain.ok and strict:
        return 2
    if report.status.lower() not in ("success", "complete", "completed", "ok", "succeeded") and strict:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
