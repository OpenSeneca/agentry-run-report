#!/usr/bin/env python3
"""
Tests for agentry-run-report. Stdlib only, runnable as a script.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from agentry_run_report import (  # noqa: E402
    ReportError,
    __version__,
    aggregate_steps,
    compute_costs,
    compute_durations,
    load_run,
    render_markdown,
    to_json,
    verify_chain,
)


def _canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _chain(events):
    """Mimic agentry-run-recorder's chain rule."""
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


def _write_run(dirpath: Path, events, trajectories=None, meta=None,
               handoff_ledger=None, fiscal_log=None) -> Path:
    dirpath.mkdir(parents=True, exist_ok=True)
    with (dirpath / "events.jsonl").open("w", encoding="utf-8") as fh:
        for ev in _chain(events):
            fh.write(json.dumps(ev) + "\n")
    if trajectories is not None:
        with (dirpath / "trajectories.jsonl").open("w", encoding="utf-8") as fh:
            for t in trajectories:
                fh.write(json.dumps(t) + "\n")
    if meta is not None:
        (dirpath / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    if handoff_ledger is not None:
        with (dirpath / "handoff_ledger.jsonl").open("w", encoding="utf-8") as fh:
            for row in handoff_ledger:
                fh.write(json.dumps(row) + "\n")
    if fiscal_log is not None:
        with (dirpath / "fiscal.jsonl").open("w", encoding="utf-8") as fh:
            for row in fiscal_log:
                fh.write(json.dumps(row) + "\n")
    return dirpath


GOOD_EVENTS = [
    {"seq": 1, "event": "start", "ts": "2026-06-23T10:00:00Z", "task": "Compute 17*23"},
    {"seq": 2, "event": "step", "ts": "2026-06-23T10:00:01Z", "tool": "calc",
     "args": "17*23", "output": "391", "step_status": "ok", "model": "gpt-4o-mini",
     "usage": {"input_tokens": 10, "output_tokens": 5}, "cost_usd": 0.00012},
    {"seq": 3, "event": "step", "ts": "2026-06-23T10:00:02Z", "tool": "calc",
     "args": "391+0", "output": "391", "step_status": "ok", "model": "gpt-4o-mini",
     "usage": {"input_tokens": 8, "output_tokens": 3}, "cost_usd": 0.00008},
    {"seq": 4, "event": "complete", "ts": "2026-06-23T10:00:03Z", "status": "success",
     "result": "391"},
]

GOOD_TRAJ = [
    {
        "id": "t1",
        "task": "Compute 17*23",
        "expected_tools": ["calc"],
        "forbidden_tools": [],
        "min_steps": 1,
        "max_steps": 3,
        "required_outputs": ["391"],
        "trajectory": [
            {"step": 1, "tool": "calc", "args": "17*23", "output": "391"},
        ],
    }
]


class ChainTests(unittest.TestCase):
    def test_intact_chain_passes(self):
        st = verify_chain(_chain(GOOD_EVENTS))
        self.assertTrue(st.ok)
        self.assertEqual(st.events, len(GOOD_EVENTS))

    def test_tamper_detected(self):
        chained = _chain(GOOD_EVENTS)
        chained[1]["output"] = "999"  # tamper
        st = verify_chain(chained)
        self.assertFalse(st.ok)
        self.assertEqual(st.broken_at_seq, 2)


class AggregationTests(unittest.TestCase):
    def test_aggregate_steps(self):
        agg = aggregate_steps(GOOD_EVENTS)
        self.assertEqual(len(agg), 1)
        self.assertEqual(agg[0].tool, "calc")
        self.assertEqual(agg[0].calls, 2)
        self.assertEqual(agg[0].successes, 2)
        self.assertEqual(agg[0].failures, 0)
        self.assertEqual(agg[0].success_rate, 1.0)

    def test_compute_costs(self):
        c = compute_costs(GOOD_EVENTS)
        self.assertEqual(c.input_tokens, 18)
        self.assertEqual(c.output_tokens, 8)
        self.assertEqual(c.total_tokens, 26)
        self.assertAlmostEqual(c.cost_usd, 0.0002, places=6)
        self.assertIn("gpt-4o-mini", c.model_breakdown)

    def test_compute_durations(self):
        d = compute_durations(GOOD_EVENTS)
        self.assertEqual(d.start, "2026-06-23T10:00:00Z")
        self.assertEqual(d.end, "2026-06-23T10:00:03Z")
        self.assertEqual(d.duration_seconds, 3.0)


class LoadRunTests(unittest.TestCase):
    def test_load_good_run(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "run-good"
            _write_run(
                d, GOOD_EVENTS, GOOD_TRAJ,
                meta={"note": "smoke run"},
                handoff_ledger=[
                    {"verdict": "accept"},
                    {"verdict": "accept"},
                    {"verdict": "reject"},
                ],
                fiscal_log=[{"decision": "allow"}],
            )
            r = load_run(d)
            self.assertEqual(r.run_id, "run-good")
            self.assertEqual(r.status, "success")
            self.assertTrue(r.chain.ok)
            self.assertEqual(r.trajectory_count, 1)
            self.assertEqual(r.handoffs_validated, 2)
            self.assertEqual(r.handoffs_failed, 1)
            self.assertEqual(r.fiscal_status, "allow")
            self.assertIn("smoke run", r.notes)
            self.assertEqual(len(r.steps), 1)
            self.assertEqual(r.steps[0].tool, "calc")

    def test_chain_break_creates_note(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "run-bad"
            d.mkdir(parents=True, exist_ok=True)
            chained = _chain(GOOD_EVENTS)
            chained[1]["output"] = "tampered"
            with (d / "events.jsonl").open("w", encoding="utf-8") as fh:
                for ev in chained:
                    fh.write(json.dumps(ev) + "\n")
            r = load_run(d)
            self.assertFalse(r.chain.ok)
            self.assertTrue(any("chain broken" in n for n in r.notes))

    def test_missing_dir_raises(self):
        with self.assertRaises(ReportError):
            load_run("/nonexistent/run-zzz")

    def test_missing_events_raises(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "run-empty"
            d.mkdir()
            with self.assertRaises(ReportError):
                load_run(d)

    def test_optional_files_optional(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "run-minimal"
            _write_run(d, GOOD_EVENTS, [])
            r = load_run(d)
            self.assertEqual(r.trajectory_count, 0)
            self.assertEqual(r.handoffs_validated, 0)
            self.assertEqual(r.fiscal_status, "unknown")


class OutputTests(unittest.TestCase):
    def test_to_json_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "run-rt"
            _write_run(d, GOOD_EVENTS, GOOD_TRAJ)
            r = load_run(d)
            js = to_json(r)
            d2 = json.loads(js)
            self.assertEqual(d2["run_id"], "run-rt")
            self.assertEqual(d2["status"], "success")
            self.assertTrue(d2["chain"]["ok"])
            self.assertEqual(d2["costs"]["total_tokens"], 26)

    def test_markdown_contains_key_sections(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "run-md"
            _write_run(d, GOOD_EVENTS, GOOD_TRAJ)
            r = load_run(d)
            md = render_markdown(r)
            self.assertIn("# Agentry run report", md)
            self.assertIn("`run-md`", md)
            self.assertIn("Tool usage", md)
            self.assertIn("calc", md)
            self.assertIn("Cost by model", md)
            self.assertIn("gpt-4o-mini", md)


class CLITests(unittest.TestCase):
    """Exercise the ``agentry-run-report.py`` CLI as a subprocess.

    These tests pin the ``--version`` flag (new in v0.1.1) against the
    pyproject.toml ``[project] version`` so a future bump cannot leave
    the two out of sync again (the v0.1.5 defect pattern from
    agentry-stack-smoke).
    """

    def _run_cli(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(ROOT / "agentry-run-report.py"), *args],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_version_flag_prints_version_and_exits_zero(self):
        """``--version`` exits 0 and prints the package semver from pyproject.toml."""
        import re
        toml = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        m = re.search(r'^version\s*=\s*"(\d+\.\d+\.\d+)"', toml, re.MULTILINE)
        self.assertTrue(m, "pyproject.toml is missing [project] version")
        pyproject_version = m.group(1)

        proc = self._run_cli("--version")
        self.assertEqual(
            proc.returncode, 0,
            f"--version should exit 0, got {proc.returncode}: {proc.stderr}",
        )
        out = proc.stdout
        self.assertIn("agentry-run-report", out)
        self.assertIn(pyproject_version, out)
        # Regression pin: the printed semver must match pyproject.toml.
        # v0.1.5 (agentry-stack-smoke) shipped the flag but the string
        # was stuck at the prior version.  Pin both so it can't drift.
        self.assertEqual(__version__, pyproject_version)

    def test_version_flag_via_module(self):
        """``python3 -m agentry_run_report --version`` also exits 0."""
        proc = subprocess.run(
            [sys.executable, "-m", "agentry_run_report", "--version"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(__version__, proc.stdout)

    def test_summary_flag_emits_machine_readable_json(self):
        """``--summary`` prints a single JSON object with the documented schema."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "run-summary"
            _write_run(d, GOOD_EVENTS, GOOD_TRAJ)
            proc = self._run_cli("--run-dir", str(d), "--summary")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            # Required schema fields (new in v0.1.1)
            for key in (
                "tool", "version", "run_id", "status", "chain_ok",
                "chain_events", "chain_broken_at_seq", "n_steps",
                "total_tokens", "cost_usd", "trajectory_count",
                "handoffs_validated", "handoffs_failed", "fiscal_status",
                "duration_seconds",
            ):
                self.assertIn(key, payload, f"missing key: {key}")
            self.assertEqual(payload["tool"], "agentry-run-report")
            self.assertEqual(payload["version"], __version__)
            self.assertEqual(payload["run_id"], "run-summary")
            self.assertTrue(payload["chain_ok"])
            self.assertEqual(payload["chain_events"], len(GOOD_EVENTS))
            self.assertEqual(payload["n_steps"], 2)
            self.assertEqual(payload["total_tokens"], 26)
            self.assertAlmostEqual(payload["cost_usd"], 0.0002, places=6)
            self.assertEqual(payload["trajectory_count"], 1)
            self.assertEqual(payload["duration_seconds"], 3.0)

    def test_summary_flag_short_circuits_report_body(self):
        """``--summary`` must NOT emit the markdown body to stdout."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "run-summary-no-body"
            _write_run(d, GOOD_EVENTS, GOOD_TRAJ)
            proc = self._run_cli("--run-dir", str(d), "--summary")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            # A single line of JSON, no markdown headers.
            self.assertNotIn("# Agentry run report", proc.stdout)
            self.assertNotIn("Tool usage", proc.stdout)
            self.assertEqual(proc.stdout.count("\n"), 1)

    def test_summary_flag_reports_chain_break(self):
        """``--summary`` surfaces chain_ok=False when events.jsonl is tampered."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "run-bad-chain"
            d.mkdir(parents=True, exist_ok=True)
            chained = _chain(GOOD_EVENTS)
            chained[1]["output"] = "tampered"
            with (d / "events.jsonl").open("w", encoding="utf-8") as fh:
                for ev in chained:
                    fh.write(json.dumps(ev) + "\n")
            proc = self._run_cli("--run-dir", str(d), "--summary")
            payload = json.loads(proc.stdout)
            self.assertFalse(payload["chain_ok"])
            self.assertEqual(payload["chain_broken_at_seq"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
