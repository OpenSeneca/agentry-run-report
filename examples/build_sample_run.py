#!/usr/bin/env python3
"""
Build a sample run directory for `agentry-run-report` examples / manual testing.

Mimics the layout produced by `agentry-run-recorder` (we don't depend on that
package; this is a stdlib-only fixture so the example is reproducible).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

from agentry_run_report import load_run, render_markdown  # noqa: E402


def _canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def chain(events):
    prev = "0" * 64
    out = []
    for ev in events:
        envelope = {k: v for k, v in ev.items() if k != "chain_hash"}
        h = hashlib.sha256(prev.encode("ascii") + _canon(envelope)).hexdigest()
        ev2 = dict(ev)
        ev2["chain_hash"] = h
        out.append(ev2)
        prev = h
    return out


def main():
    out_dir = ROOT / "sample_run"
    out_dir.mkdir(parents=True, exist_ok=True)

    events = [
        {"seq": 1, "event": "start", "ts": "2026-06-23T10:00:00Z",
         "task": "Summarize today's three Agentry PRs"},
        {"seq": 2, "event": "step", "ts": "2026-06-23T10:00:01Z",
         "tool": "gh_list_prs", "args": "{\"repo\": \"OpenSeneca\"}",
         "output": "3 PRs", "step_status": "ok", "model": "gpt-4o-mini",
         "usage": {"input_tokens": 50, "output_tokens": 20},
         "cost_usd": 0.0001},
        {"seq": 3, "event": "step", "ts": "2026-06-23T10:00:02Z",
         "tool": "summarize", "args": "pr-1,pr-2,pr-3", "output": "summary…",
         "step_status": "ok", "model": "gpt-4o-mini",
         "usage": {"input_tokens": 600, "output_tokens": 200},
         "cost_usd": 0.0012},
        {"seq": 4, "event": "step", "ts": "2026-06-23T10:00:03Z",
         "tool": "post_to_digest", "args": "summary", "output": "ok",
         "step_status": "ok", "model": "gpt-4o-mini",
         "usage": {"input_tokens": 250, "output_tokens": 30},
         "cost_usd": 0.0004},
        {"seq": 5, "event": "complete", "ts": "2026-06-23T10:00:04Z",
         "status": "success", "result": "digest posted"},
    ]

    with (out_dir / "events.jsonl").open("w", encoding="utf-8") as fh:
        for ev in chain(events):
            fh.write(json.dumps(ev) + "\n")

    trajectories = [
        {
            "id": "t1",
            "task": "Summarize today's three Agentry PRs",
            "expected_tools": ["gh_list_prs", "summarize", "post_to_digest"],
            "forbidden_tools": ["web_browser"],
            "min_steps": 3,
            "max_steps": 5,
            "required_outputs": ["digest posted"],
            "trajectory": [
                {"step": 1, "tool": "gh_list_prs", "args": "...",
                 "output": "3 PRs"},
                {"step": 2, "tool": "summarize", "args": "...",
                 "output": "summary…"},
                {"step": 3, "tool": "post_to_digest", "args": "...",
                 "output": "ok"},
            ],
        }
    ]
    with (out_dir / "trajectories.jsonl").open("w", encoding="utf-8") as fh:
        for t in trajectories:
            fh.write(json.dumps(t) + "\n")

    handoff_ledger = [
        {"verdict": "accept", "from_worker": "planner",
         "to_worker": "executor", "contract_id": "planner_to_executor.v1"},
        {"verdict": "accept", "from_worker": "executor",
         "to_worker": "auditor", "contract_id": "executor_to_auditor.v1"},
    ]
    with (out_dir / "handoff_ledger.jsonl").open("w", encoding="utf-8") as fh:
        for row in handoff_ledger:
            fh.write(json.dumps(row) + "\n")

    fiscal = [{"decision": "allow", "ceiling_usd": 5.0, "spent_usd": 0.0017}]
    with (out_dir / "fiscal.jsonl").open("w", encoding="utf-8") as fh:
        for row in fiscal:
            fh.write(json.dumps(row) + "\n")

    (out_dir / "meta.json").write_text(
        json.dumps({"note": "sample run built by examples/build_sample_run.py"}),
        encoding="utf-8",
    )

    print(f"wrote {out_dir}/")
    print(f"  events.jsonl       ({len(events)} events)")
    print(f"  trajectories.jsonl ({len(trajectories)} records)")
    print(f"  handoff_ledger.jsonl ({len(handoff_ledger)} rows)")
    print(f"  fiscal.jsonl        ({len(fiscal)} rows)")


if __name__ == "__main__":
    main()
