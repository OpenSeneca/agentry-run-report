"""
Core report-builder for an Agentry run directory.

A "run directory" is the directory written by `agentry-run-recorder`. The
shape we expect (only the files we touch):

    runs/<run_id>/
        events.jsonl        -- one JSON event per line, SHA-256 chained
        trajectories.jsonl  -- one trajectory record per line (graded by
                               agentry-trajectory-grader)
        meta.json           -- optional, written by some harnesses

This module reads those files and produces a `RunReport`. We deliberately
stay stdlib-only: the Agentry stack is a foundation layer and shouldn't
pull in requests / pydantic / yaml for a tool this small.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


# ---------- public errors ----------


class ReportError(ValueError):
    """Raised when a run directory is missing required files or is malformed."""


# ---------- data classes ----------


@dataclass
class StepAggregate:
    """How a single tool fared across the run."""

    tool: str
    calls: int
    successes: int
    failures: int
    success_rate: float


@dataclass
class CostSummary:
    """Token + cost rollup for the run, in USD."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    model_breakdown: dict[str, dict[str, float]] = field(default_factory=dict)


@dataclass
class DurationSummary:
    """Wall-clock timing for the run."""

    start: str | None = None
    end: str | None = None
    duration_seconds: float | None = None


@dataclass
class ChainStatus:
    """SHA-256 chain status of `events.jsonl`."""

    events: int
    ok: bool
    broken_at_seq: int | None = None
    expected_hash: str | None = None
    actual_hash: str | None = None


@dataclass
class RunReport:
    """The unified report we emit for a run."""

    run_id: str
    run_dir: str
    status: str
    chain: ChainStatus
    steps: list[StepAggregate]
    costs: CostSummary
    duration: DurationSummary
    trajectory_count: int
    handoffs_validated: int = 0
    handoffs_failed: int = 0
    fiscal_status: str = "unknown"
    notes: list[str] = field(default_factory=list)
    generated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "run_id": self.run_id,
            "run_dir": self.run_dir,
            "status": self.status,
            "chain": asdict(self.chain),
            "steps": [asdict(s) for s in self.steps],
            "costs": asdict(self.costs),
            "duration": asdict(self.duration),
            "trajectory_count": self.trajectory_count,
            "handoffs_validated": self.handoffs_validated,
            "handoffs_failed": self.handoffs_failed,
            "fiscal_status": self.fiscal_status,
            "notes": list(self.notes),
            "generated_at": self.generated_at,
        }
        return d


# ---------- file readers ----------


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ReportError(f"missing required file: {path}")
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for ln, raw in enumerate(fh, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError as e:
                raise ReportError(f"{path}:{ln}: invalid JSON: {e}") from e
            if not isinstance(row, dict):
                raise ReportError(f"{path}:{ln}: line is not a JSON object")
            out.append(row)
    return out


# ---------- chain verification ----------


def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def verify_chain(events: Sequence[Mapping[str, Any]]) -> ChainStatus:
    """Recompute the SHA-256 chain and return where (if anywhere) it breaks.

    Mirrors the chain rule used by `agentry-run-recorder`:
        chain_hash[n] = SHA256( prev_chain_hash[n-1] || canonical_json(envelope[n]) )
    where `envelope` is the event with `chain_hash` itself stripped.
    """
    prev = "0" * 64
    for ev in events:
        seq = ev.get("seq")
        if not isinstance(seq, int):
            return ChainStatus(
                events=len(events),
                ok=False,
                broken_at_seq=-1,
                expected_hash=prev,
                actual_hash=None,
            )
        envelope = {k: v for k, v in ev.items() if k != "chain_hash"}
        expected = hashlib.sha256(
            prev.encode("ascii") + _canonical(envelope)
        ).hexdigest()
        if ev.get("chain_hash") != expected:
            return ChainStatus(
                events=len(events),
                ok=False,
                broken_at_seq=seq,
                expected_hash=expected,
                actual_hash=ev.get("chain_hash"),
            )
        prev = expected
    return ChainStatus(events=len(events), ok=True)


# ---------- aggregations ----------


def aggregate_steps(events: Sequence[Mapping[str, Any]]) -> list[StepAggregate]:
    """Group step events by tool and compute success rate."""
    by_tool: dict[str, dict[str, int]] = {}
    for ev in events:
        if ev.get("event") != "step":
            continue
        tool = ev.get("tool")
        if not isinstance(tool, str) or not tool:
            continue
        slot = by_tool.setdefault(tool, {"calls": 0, "successes": 0, "failures": 0})
        slot["calls"] += 1
        # Heuristics for "success": step_status, status, ok, or fallback to "complete"
        status = ev.get("step_status") or ev.get("status") or ev.get("ok")
        if status is True or status == "ok" or status == "success" or status == "complete":
            slot["successes"] += 1
        elif status is False or status in ("error", "fail", "failed"):
            slot["failures"] += 1
        # if unknown, we leave it out of successes/failures but still count the call

    out: list[StepAggregate] = []
    for tool, s in sorted(by_tool.items()):
        decided = s["successes"] + s["failures"]
        rate = (s["successes"] / decided) if decided else 0.0
        out.append(
            StepAggregate(
                tool=tool,
                calls=s["calls"],
                successes=s["successes"],
                failures=s["failures"],
                success_rate=round(rate, 4),
            )
        )
    return out


def compute_costs(events: Sequence[Mapping[str, Any]]) -> CostSummary:
    """Sum tokens + USD cost. Model breakdown is best-effort (if events carry
    `model` and `cost_usd` / `usage`).
    """
    in_t = out_t = 0
    cost = 0.0
    by_model: dict[str, dict[str, float]] = {}
    for ev in events:
        usage = ev.get("usage") or {}
        if isinstance(usage, dict):
            in_t += int(usage.get("input_tokens", 0) or 0)
            out_t += int(usage.get("output_tokens", 0) or 0)
        c = ev.get("cost_usd")
        if isinstance(c, (int, float)):
            cost += float(c)
            model = str(ev.get("model") or "unknown")
            slot = by_model.setdefault(
                model, {"input_tokens": 0.0, "output_tokens": 0.0, "cost_usd": 0.0}
            )
            slot["input_tokens"] += float(usage.get("input_tokens", 0) or 0)
            slot["output_tokens"] += float(usage.get("output_tokens", 0) or 0)
            slot["cost_usd"] += float(c)
    return CostSummary(
        input_tokens=in_t,
        output_tokens=out_t,
        total_tokens=in_t + out_t,
        cost_usd=round(cost, 6),
        model_breakdown={
            m: {k: round(v, 6) for k, v in d.items()}
            for m, d in by_model.items()
        },
    )


def compute_durations(events: Sequence[Mapping[str, Any]]) -> DurationSummary:
    """First / last timestamp delta, when events carry `ts` (ISO 8601)."""
    starts: list[str] = []
    ends: list[str] = []
    for ev in events:
        ts = ev.get("ts") or ev.get("timestamp")
        if not isinstance(ts, str):
            continue
        if ev.get("event") == "start":
            starts.append(ts)
        if ev.get("event") == "complete":
            ends.append(ts)
    if not starts and not ends:
        # fall back to first / last event ts
        all_ts = [
            ev.get("ts") or ev.get("timestamp")
            for ev in events
            if isinstance(ev.get("ts") or ev.get("timestamp"), str)
        ]
        if all_ts:
            starts = [all_ts[0]]
            ends = [all_ts[-1]]
    if not starts or not ends:
        return DurationSummary()
    try:
        t0 = datetime.fromisoformat(starts[0].replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(ends[-1].replace("Z", "+00:00"))
    except ValueError:
        return DurationSummary(start=starts[0], end=ends[-1])
    if t0.tzinfo is None:
        t0 = t0.replace(tzinfo=timezone.utc)
    if t1.tzinfo is None:
        t1 = t1.replace(tzinfo=timezone.utc)
    return DurationSummary(
        start=starts[0],
        end=ends[-1],
        duration_seconds=round((t1 - t0).total_seconds(), 3),
    )


# ---------- top-level loader ----------


def load_run(run_dir: str | Path) -> RunReport:
    """Build a `RunReport` from a recorder run directory.

    Raises `ReportError` if the directory is missing the required files or
    contains malformed JSON. Other files (`meta.json`, handoff-contract
    ledger, etc.) are read opportunistically.
    """
    p = Path(run_dir)
    if not p.is_dir():
        raise ReportError(f"run dir is not a directory: {p}")

    events_path = p / "events.jsonl"
    traj_path = p / "trajectories.jsonl"
    meta_path = p / "meta.json"

    events = _read_jsonl(events_path)
    trajectories = _read_jsonl(traj_path) if traj_path.is_file() else []

    # status: prefer the recorder's "complete" event
    status = "unknown"
    for ev in events:
        if ev.get("event") == "complete":
            status = str(ev.get("status") or ev.get("result") or "complete")
            break

    chain = verify_chain(events)
    steps = aggregate_steps(events)
    costs = compute_costs(events)
    duration = compute_durations(events)

    # handoff ledger (optional)
    handoffs_validated = 0
    handoffs_failed = 0
    fiscal_status = "unknown"
    handoff_ledger = p / "handoff_ledger.jsonl"
    if handoff_ledger.is_file():
        for row in _read_jsonl(handoff_ledger):
            verdict = (row.get("verdict") or row.get("result") or "").lower()
            if verdict in ("accept", "accepted", "valid", "ok", "warn", "warning"):
                handoffs_validated += 1
            elif verdict in ("reject", "rejected", "fail", "failed", "invalid"):
                handoffs_failed += 1

    fiscal_log = p / "fiscal.jsonl"
    if fiscal_log.is_file():
        decisions = _read_jsonl(fiscal_log)
        if decisions:
            fiscal_status = str(
                decisions[-1].get("decision")
                or decisions[-1].get("verdict")
                or decisions[-1].get("status")
                or "unknown"
            )

    notes: list[str] = []
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(meta, dict) and meta.get("note"):
                notes.append(str(meta["note"]))
        except json.JSONDecodeError:
            notes.append("meta.json present but invalid JSON (ignored)")

    if not chain.ok:
        notes.append(
            f"events.jsonl chain broken at seq {chain.broken_at_seq} — "
            f"audit layer will flag this run"
        )

    return RunReport(
        run_id=p.name,
        run_dir=str(p.resolve()),
        status=status,
        chain=chain,
        steps=steps,
        costs=costs,
        duration=duration,
        trajectory_count=len(trajectories),
        handoffs_validated=handoffs_validated,
        handoffs_failed=handoffs_failed,
        fiscal_status=fiscal_status,
        notes=notes,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


# ---------- output ----------


def to_json(report: RunReport, indent: int | None = 2) -> str:
    return json.dumps(report.to_dict(), indent=indent, sort_keys=True)


def render_markdown(report: RunReport) -> str:
    """Render a human-readable Markdown report."""
    lines: list[str] = []
    lines.append(f"# Agentry run report — `{report.run_id}`")
    lines.append("")
    lines.append(f"- **Status:** `{report.status}`")
    lines.append(
        f"- **Chain:** {'✅ intact' if report.chain.ok else '❌ BROKEN at seq ' + str(report.chain.broken_at_seq)} "
        f"({report.chain.events} events)"
    )
    if report.duration.duration_seconds is not None:
        lines.append(
            f"- **Duration:** {report.duration.duration_seconds:g}s "
            f"({report.duration.start} → {report.duration.end})"
        )
    if report.costs.total_tokens or report.costs.cost_usd:
        lines.append(
            f"- **Tokens:** {report.costs.total_tokens:,}  "
            f"(in {report.costs.input_tokens:,} / out {report.costs.output_tokens:,})"
        )
    if report.costs.cost_usd:
        lines.append(f"- **Cost:** ${report.costs.cost_usd:,.4f}")
    if report.fiscal_status != "unknown":
        lines.append(f"- **Fiscal gate:** `{report.fiscal_status}`")
    lines.append(
        f"- **Handoffs:** {report.handoffs_validated} accepted, "
        f"{report.handoffs_failed} rejected"
    )
    lines.append(f"- **Trajectories:** {report.trajectory_count}")
    lines.append(f"- **Generated:** {report.generated_at}")
    lines.append("")

    if report.steps:
        lines.append("## Tool usage")
        lines.append("")
        lines.append("| Tool | Calls | ✅ | ❌ | Success rate |")
        lines.append("|------|------:|---:|---:|-------------:|")
        for s in sorted(report.steps, key=lambda x: (-x.calls, x.tool)):
            lines.append(
                f"| `{s.tool}` | {s.calls} | {s.successes} | {s.failures} | "
                f"{s.success_rate * 100:.1f}% |"
            )
        lines.append("")

    if report.costs.model_breakdown:
        lines.append("## Cost by model")
        lines.append("")
        lines.append("| Model | In tok | Out tok | Cost (USD) |")
        lines.append("|-------|-------:|--------:|-----------:|")
        for m, d in sorted(report.costs.model_breakdown.items()):
            lines.append(
                f"| `{m}` | {int(d['input_tokens']):,} | {int(d['output_tokens']):,} | "
                f"${d['cost_usd']:,.4f} |"
            )
        lines.append("")

    if report.notes:
        lines.append("## Notes")
        lines.append("")
        for n in report.notes:
            lines.append(f"- {n}")
        lines.append("")

    # mean step cost as a tiny CI-friendly hint
    if report.steps and report.costs.total_tokens:
        mean_tokens = report.costs.total_tokens / max(
            sum(s.calls for s in report.steps), 1
        )
        lines.append(
            f"_Avg tokens per tool call: {mean_tokens:,.1f}._"
        )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ---------- stat helpers exposed for tests ----------


def mean(xs: Iterable[float]) -> float:
    xs = list(xs)
    return statistics.fmean(xs) if xs else 0.0
