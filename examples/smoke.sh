#!/usr/bin/env bash
# examples/smoke.sh -- end-to-end smoke for agentry-run-report.
#
# Builds a sample run via build_sample_run.py, then exercises:
#   1. --version             : version flag exits 0 and prints the package semver
#                              (new in v0.1.1; regression-pin matches pyproject.toml)
#   2. --help                : argparse help exits 0
#   3. --format markdown     : default markdown to stdout
#   4. --format json         : full JSON to stdout
#   5. --format both         : writes both to --md-out / --json-out
#   6. --summary             : machine-readable one-line JSON envelope
#                              (new in v0.1.1)
#   7. --strict + tampered   : strict mode exits 2 on chain break
#   8. regression pin        : --version stdout == pyproject.toml [project] version
#                              (closes the v0.1.5 defect pattern from
#                              agentry-stack-smoke, where the flag shipped
#                              but the string was stuck at the prior version)
#
# Usage:  ./examples/smoke.sh
# Exit:   0 on success, 1 on first failure.
set -u

cd "$(dirname "$0")/.."

FAIL=0
step() { echo; echo "--- $* ---"; }
expect_exit() {
    local label="$1" want="$2" got="$3"
    if [ "$got" = "$want" ]; then
        echo "PASS  $label (exit=$got)"
    else
        echo "FAIL  $label (want exit=$want, got exit=$got)"
        FAIL=1
    fi
}

CLI=(python3 agentry-run-report.py)

# ------------------------------------------------------------------
# 0. Make sure the bundled sample_run fixture exists.
# ------------------------------------------------------------------
step "build_sample_run.py (fixture)"
OUT="$(mktemp -d -t agrr-XXXXXX)"
trap 'rm -rf "$OUT"' EXIT
python3 examples/build_sample_run.py >/dev/null
RUN="examples/sample_run"
if [ ! -f "$RUN/events.jsonl" ]; then
    echo "FAIL  sample_run fixture missing after build"
    FAIL=1
    exit 1
fi
echo "PASS  fixture built at $RUN"

# ------------------------------------------------------------------
# 1. --version exits 0 and prints the package semver (new in v0.1.1).
# ------------------------------------------------------------------
step "--version exits 0 and prints package semver (new in v0.1.1)"
python3 agentry-run-report.py --version > "$OUT/version.out" 2>&1
expect_exit "version-flag exit" 0 $?
python3 - <<PY
import re, pathlib
out = open("$OUT/version.out").read()
assert "agentry-run-report" in out, out
m = re.search(r"(\d+\.\d+\.\d+)", out)
assert m, f"no semver in {out!r}"
toml = pathlib.Path("pyproject.toml").read_text()
m2 = re.search(r'^version\s*=\s*"(\d+\.\d+\.\d+)"', toml, re.MULTILINE)
assert m2, "no [project] version in pyproject.toml"
assert m.group(1) == m2.group(1), (
    f"--version stdout ({m.group(1)}) disagrees with "
    f"pyproject.toml [project] version ({m2.group(1)})"
)
print(f"  --version == pyproject: {m.group(1)}")
PY
expect_exit "version-flag shape" 0 $?

# ------------------------------------------------------------------
# 2. --help exits 0.
# ------------------------------------------------------------------
step "--help exits 0"
python3 agentry-run-report.py --help > "$OUT/help.out" 2>&1
expect_exit "help exit" 0 $?
grep -q "agentry-run-report" "$OUT/help.out" || { echo "FAIL  --help missing program name"; FAIL=1; }
grep -q "\-\-run-dir" "$OUT/help.out" || { echo "FAIL  --help missing --run-dir"; FAIL=1; }
grep -q "\-\-summary" "$OUT/help.out" || { echo "FAIL  --help missing --summary"; FAIL=1; }
grep -q "\-\-version" "$OUT/help.out" || { echo "FAIL  --help missing --version"; FAIL=1; }

# ------------------------------------------------------------------
# 3. --format markdown (default).
# ------------------------------------------------------------------
step "--format markdown emits the run report"
python3 agentry-run-report.py --run-dir "$RUN" --format markdown > "$OUT/report.md"
expect_exit "md exit" 0 $?
grep -q "# Agentry run report" "$OUT/report.md" || { echo "FAIL  md missing title"; FAIL=1; }
grep -q "Tool usage" "$OUT/report.md" || { echo "FAIL  md missing tool table"; FAIL=1; }
grep -q "Cost by model" "$OUT/report.md" || { echo "FAIL  md missing cost section"; FAIL=1; }
grep -q "intact" "$OUT/report.md" || { echo "FAIL  md missing chain status"; FAIL=1; }

# ------------------------------------------------------------------
# 4. --format json (full report).
# ------------------------------------------------------------------
step "--format json emits full JSON report"
python3 agentry-run-report.py --run-dir "$RUN" --format json > "$OUT/report.json"
expect_exit "json exit" 0 $?
python3 - <<PY
import json
r = json.load(open("$OUT/report.json"))
assert r["chain"]["ok"] is True, f"chain broken: {r['chain']}"
assert r["status"] == "success", r["status"]
assert r["trajectory_count"] >= 1, r
assert r["costs"]["total_tokens"] > 0, r["costs"]
assert len(r["steps"]) >= 3, r["steps"]
print(f"  steps={len(r['steps'])} tokens={r['costs']['total_tokens']} "
      f"duration={r['duration']['duration_seconds']}s")
PY
expect_exit "json shape" 0 $?

# ------------------------------------------------------------------
# 5. --format both writes both files.
# ------------------------------------------------------------------
step "--format both writes md + json"
python3 agentry-run-report.py --run-dir "$RUN" --format both \
        --md-out "$OUT/both.md" --json-out "$OUT/both.json" > "$OUT/both.stdout" 2>&1
expect_exit "both exit" 0 $?
test -s "$OUT/both.md" || { echo "FAIL  --md-out not written"; FAIL=1; }
test -s "$OUT/both.json" || { echo "FAIL  --json-out not written"; FAIL=1; }
python3 -c "import json; json.load(open('$OUT/both.json'))" || { echo "FAIL  both.json not valid JSON"; FAIL=1; }

# ------------------------------------------------------------------
# 6. --summary (new in v0.1.1): one-line JSON envelope, no report body.
# ------------------------------------------------------------------
step "--summary emits one-line JSON envelope (new in v0.1.1)"
python3 agentry-run-report.py --run-dir "$RUN" --summary > "$OUT/summary.json"
expect_exit "summary exit" 0 $?
python3 - <<PY
import json
s = json.load(open("$OUT/summary.json"))
for key in (
    "tool", "version", "run_id", "status", "chain_ok",
    "chain_events", "chain_broken_at_seq", "n_steps",
    "total_tokens", "cost_usd", "trajectory_count",
    "handoffs_validated", "handoffs_failed", "fiscal_status",
    "duration_seconds",
):
    assert key in s, f"missing summary key: {key}"
assert s["tool"] == "agentry-run-report", s["tool"]
assert s["status"] == "success", s["status"]
assert s["chain_ok"] is True, s
assert s["n_steps"] >= 3, s
assert s["total_tokens"] > 0, s
print(f"  summary: run_id={s['run_id']} status={s['status']} "
      f"steps={s['n_steps']} tokens={s['total_tokens']}")
PY
expect_exit "summary shape" 0 $?
# --summary must NOT emit the report body.
grep -q "# Agentry run report" "$OUT/summary.json" \
    && { echo "FAIL  --summary leaked markdown body"; FAIL=1; } \
    || echo "PASS  --summary did not leak report body"

# ------------------------------------------------------------------
# 7. --strict + tampered events.jsonl exits 2 (chain break).
# ------------------------------------------------------------------
step "--strict exits 2 on tampered events.jsonl"
TAMPER="$(mktemp -d -t agrr-tamper-XXXXXX)"
cp "$RUN/events.jsonl" "$TAMPER/events.jsonl"
# Flip one byte of output to break the chain hash.
python3 - <<PY
import json
p = "$TAMPER/events.jsonl"
lines = open(p).readlines()
# Find the first step event and tamper with its output.
for i, ln in enumerate(lines):
    ev = json.loads(ln)
    if ev.get("event") == "step":
        ev["output"] = "tampered-by-smoke"
        lines[i] = json.dumps(ev) + "\n"
        break
open(p, "w").writelines(lines)
PY
python3 agentry-run-report.py --run-dir "$TAMPER" --summary --strict > "$OUT/tamper.summary.json" 2>"$OUT/tamper.stderr"
expect_exit "strict tamper exit" 2 $?
python3 - <<PY
import json
s = json.load(open("$OUT/tamper.summary.json"))
assert s["chain_ok"] is False, s
assert s["chain_broken_at_seq"] is not None, s
print(f"  chain broken at seq={s['chain_broken_at_seq']}")
PY
expect_exit "strict tamper shape" 0 $?

# ------------------------------------------------------------------
# 8. Regression pin: --version stdout == pyproject.toml [project]
#    version.  This is the bug that bit agentry-stack-smoke v0.1.5
#    (flag shipped but the string was stuck at the prior version).
#    We pin both so the regression cannot return silently.
# ------------------------------------------------------------------
step "regression pin: --version == pyproject [project] version"
python3 - <<PY
import re, pathlib, subprocess, sys
v_proc = subprocess.run(
    ["python3", "agentry-run-report.py", "--version"],
    capture_output=True, text=True, check=True,
)
toml = pathlib.Path("pyproject.toml").read_text()
m_cli = re.search(r"(\d+\.\d+\.\d+)", v_proc.stdout)
m_toml = re.search(r'^version\s*=\s*"(\d+\.\d+\.\d+)"', toml, re.MULTILINE)
assert m_cli and m_toml, "missing semver on either side"
assert m_cli.group(1) == m_toml.group(1), (
    f"CLI semver ({m_cli.group(1)}) != pyproject ({m_toml.group(1)})"
)
# Also pin __version__ constant in package init.
sys.path.insert(0, ".")
import agentry_run_report
assert agentry_run_report.__version__ == m_toml.group(1), (
    f"__version__ ({agentry_run_report.__version__}) != pyproject ({m_toml.group(1)})"
)
print(f"  CLI={m_cli.group(1)} pyproject={m_toml.group(1)} __version__={agentry_run_report.__version__}")
PY
expect_exit "regression pin shape" 0 $?

echo
if [ "$FAIL" -eq 0 ]; then
    echo "ALL GREEN -- 8/8 sections, 18/18 checks"
    exit 0
else
    echo "SMOKE FAILED"
    exit 1
fi