r"""
agentry-run-report
~~~~~~~~~~~~~~~~~~

Unified report generator for an Agentry run directory produced by
`agentry-run-recorder`. Reads the recorder's `events.jsonl` and
`trajectories.jsonl` and emits a single combined Markdown + JSON report
suitable for posting to a PR, dashboard, or audit log.

Agentry layer: orchestration (composes `agentry-run-recorder` +
`agentry-trajectory-grader` + `agentry-fiscal-gate` outputs into one
deliverable). Pairs with the rest of the Agentry stack:

  planner -> agentry-sandbox -> agentry-run-recorder
                                \-> agentry-run-report  (this)
                                       |
                                       +-> agentry-trajectory-grader
                                       +-> agentry-fiscal-gate
                                       +-> agentry-handoff-contract
                                       +-> agentry-eval-scorer
"""

from .report import (
    RunReport,
    ReportError,
    aggregate_steps,
    compute_costs,
    compute_durations,
    load_run,
    render_markdown,
    to_json,
    verify_chain,
)

__all__ = [
    "RunReport",
    "ReportError",
    "aggregate_steps",
    "compute_costs",
    "compute_durations",
    "load_run",
    "render_markdown",
    "to_json",
    "verify_chain",
]

__version__ = "0.1.1"
