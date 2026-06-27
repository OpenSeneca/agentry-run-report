# Changelog

All notable changes to **agentry-run-report** are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] — 2026-06-27

### Added
- **`--version` CLI flag** on both the entry script (`agentry-run-report.py`)
  and `python3 -m agentry_run_report`. Standard argparse `action="version"`
  behavior; prints `agentry-run-report <version>` and exits 0. Closes the
  parity gap with the rest of the Agentry stack (stack-smoke v0.1.5,
  trajectory-grader v0.1.1, eval-scorer v0.1.1 all have it).
- **`--summary` CLI flag** on both CLIs. Emits a single-line JSON envelope
  to stdout (does NOT emit the full report body) with the documented schema:
  `{tool, version, run_id, run_dir, status, chain_ok, chain_events,
  chain_broken_at_seq, n_steps, total_tokens, cost_usd, trajectory_count,
  handoffs_validated, handoffs_failed, fiscal_status, duration_seconds}`.
  Machine-readable parity with `agentry-stack-smoke --json`, `agentry-
  trajectory-grader --json`, `agentry-eval-scorer --json` for CI consumers.
  Strict-mode exit codes (2 on chain break, 3 on incomplete run) still apply.
- **`examples/smoke.sh`** — end-to-end smoke (mirrors the trajectory-grader
  and stack-smoke smoke patterns). 8 sections, 24 checks, stdlib-only,
  no jq / pytest / extra deps.
- **`CLITests` class in `tests/test_report.py`** — 5 new subprocess tests:
  - `test_version_flag_prints_version_and_exits_zero` — pins `--version`
    stdout against `pyproject.toml [project] version` AND
    `agentry_run_report.__version__` (the v0.1.5 defect pattern from
    agentry-stack-smoke). Future ships that drift the three values will
    fail this test before tagging.
  - `test_version_flag_via_module_invocation` — `python3 -m agentry_run_report --version`.
  - `test_summary_flag_emits_machine_readable_json_envelope` — single-line,
    exactly 16 documented schema keys.
  - `test_summary_flag_silent_when_combined_with_format` — `--summary`
    short-circuits the report body even when `--format` is also passed.
  - `test_strict_exit_codes_unchanged` — `--strict` happy path still exit 0.

### Changed
- **Bump version 0.1.0 → 0.1.1** in `__init__.py` AND `pyproject.toml`.
- **`__main__.py` rewritten** to use proper `argparse` (replacing the
  hand-rolled positional parser that only inspected `sys.argv[1:]`).
  Accepts `run_dir` as a true positional arg, so the help/usage text now
  matches the rest of the Agentry stack.
- **`__main__.py --format` choices** expanded to `{"md", "markdown",
  "json", "both"}` — both the short and long aliases work; the legacy
  `markdown`/`json` names are still accepted for backward compatibility.
  Internally normalized to canonical `markdown` / `json`.

### Tests
- 12 → 17 unit tests (`tests/test_report.py`).
- New `examples/smoke.sh` with 24 PASS checks across 8 sections.

## [0.1.0] — 2026-06-23

### Added
- Initial release.
- Unified Markdown + JSON report from an `agentry-run-recorder` run dir.
- SHA-256 chain verification of `events.jsonl` (tamper-evident).
- Tool usage aggregation, token + cost totals (per-model breakdown),
  wall-clock duration, optional handoff ledger + fiscal log integration.
- CLI: `--run-dir`, `--format`, `--md-out`, `--json-out`, `--strict`.
- Exit codes: 0 = success, 2 = chain break, 3 = incomplete run, 1 = bad args.
- 12 stdlib-only unit tests (~0.01s).
- Stdlib-only (no third-party deps).
- Pushed to `OpenSeneca/agentry-run-report` (commit `83a0620`) — *no tag
  was created on initial push; this v0.1.1 ship also closes that gap.*
