# agentry-run-report

**Unified report generator for an Agentry run directory.** Reads the
`events.jsonl` + `trajectories.jsonl` (and optional `handoff_ledger.jsonl` /
`fiscal.jsonl`) emitted by
[`agentry-run-recorder`](https://github.com/OpenSeneca/agentry-run-recorder),
verifies the SHA-256 event chain, and emits one combined Markdown + JSON
report — suitable for posting to a PR, attaching to a digest, or feeding
the audit layer.

| Agentry layer | Status | Tests | License | Python | Deps |
|---|---|---|---|---|---|
| orchestration (unified report / run-summary) | v0.1.2 | 17/17 in <0.5s | MIT (OpenSeneca) | 3.8+ | **stdlib only** |

## What it composes into

Sits at the *end* of an Agentry run, after the recorder has flushed:

```
planner ─▶ executor ─▶ auditor
   │            │          │
   ▼            ▼          ▼
agentry-run-recorder   agentry-fiscal-gate
   │            │          │
   └──────┬─────┴──────────┘
          ▼
   agentry-run-report  ◀── you are here
          │
          ├──▶ report.md   (PR comment, digest attachment)
          └──▶ report.json (dashboard / audit ledger row)
```

This is a small *adapter*: it doesn't grade, score, or gate — it lifts
the signals the rest of the Agentry stack has already produced into one
shippable artifact.

## What it does

- Verifies the SHA-256 chain of `events.jsonl` (mirrors
  `agentry-run-recorder`'s rule: `chain_hash[n] = SHA256(prev || canonical(event))`).
  On tamper, the report still renders, but it gets a prominent warning.
- Aggregates tool usage: per-tool call counts, successes, failures,
  success rate.
- Sums token usage + cost, with a per-model breakdown.
- Computes wall-clock duration from the first `start` and last `complete`
  timestamps.
- Reads the optional handoff ledger and reports accepted/rejected counts.
- Reads the optional fiscal log and reports the final gate decision.
- Emits Markdown (human) and/or JSON (machine).

## Install

No dependencies. Just Python 3.8+.

```bash
git clone https://github.com/OpenSeneca/agentry-run-report.git
cd agentry-run-report
```

## CLI

```bash
# Markdown to stdout (default)
agentry-run-report runs/run-001

# JSON to stdout
agentry-run-report runs/run-001 --format json

# Both, to files
agentry-run-report runs/run-001 --format both \
        --md-out report.md --json-out report.json

# Strict CI mode: exit 2 on chain break, exit 3 on incomplete run
agentry-run-report runs/run-001 --format json --strict

# Machine-readable one-line summary (v0.1.1+)
agentry-run-report runs/run-001 --summary

# Version
agentry-run-report --version
```

Can also be invoked as `python3 -m agentry_run_report <run-dir>` or `python3 agentry-run-report.py <run-dir>`.

Exit codes:
- `0` — report built, run completed, chain intact
- `2` — (with `--strict`) chain broken
- `3` — (with `--strict`) run did not reach a `complete` / `success` status
- `1` — bad arguments / unreadable run dir

## Python API

```python
from agentry_run_report import load_run, render_markdown, to_json

report = load_run("runs/run-001")
print(render_markdown(report))
with open("report.json", "w") as f:
    f.write(to_json(report))
```

## Run directory layout (consumed)

```
runs/<run_id>/
    events.jsonl          # required, one event per line, SHA-256 chained
    trajectories.jsonl    # required (may be empty), one trajectory per line
    meta.json             # optional, {"note": "..."}
    handoff_ledger.jsonl  # optional, one row per handoff verdict
    fiscal.jsonl          # optional, one row per fiscal-gate decision
```

## What it deliberately does NOT do

- It does **not** grade trajectories — that is
  [`agentry-trajectory-grader`](https://github.com/OpenSeneca/agentry-trajectory-grader)'s job.
- It does **not** score outputs — that is
  [`agentry-eval-scorer`](https://github.com/OpenSeneca/agentry-eval-scorer)'s job.
- It does **not** enforce cost ceilings — that is
  [`agentry-fiscal-gate`](https://github.com/OpenSeneca/agentry-fiscal-gate)'s job.
- It does **not** validate handoff contracts — that is
  [`agentry-handoff-contract`](https://github.com/OpenSeneca/agentry-handoff-contract)'s job.

It composes their outputs. One job, well-bounded.

## Tests

```bash
cd agentry-run-report
python3 tests/test_report.py
```

17 tests, ~0.5s, stdlib only. 18/18 smoke checks via `bash examples/smoke.sh`.

## Example

```bash
python3 examples/build_sample_run.py          # writes examples/sample_run/
agentry-run-report examples/sample_run --format markdown
```

Sample output (excerpt):

```
# Agentry run report — `sample_run`

- **Status:** `success`
- **Chain:** ✅ intact (5 events)
- **Duration:** 4s (2026-06-23T10:00:00Z → 2026-06-23T10:00:04Z)
- **Tokens:** 1,150  (in 900 / out 250)
- **Cost:** $0.0017
- **Fiscal gate:** `allow`
- **Handoffs:** 2 accepted, 0 rejected
- **Trajectories:** 1

## Tool usage

| Tool           | Calls | ✅ | ❌ | Success rate |
|----------------|------:|---:|---:|-------------:|
| `gh_list_prs`  |     1 |  1 |  0 |       100.0% |
| `summarize`    |     1 |  1 |  0 |       100.0% |
| `post_to_digest` |   1 |  1 |  0 |       100.0% |

## Cost by model

| Model         | In tok | Out tok | Cost (USD) |
|---------------|-------:|--------:|-----------:|
| `gpt-4o-mini` |    900 |     250 |   $0.0017  |
```
