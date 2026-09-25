#!/usr/bin/env bash
# Run the real PEWeaver ChiaMerge FFT loop from this checkout.
#
# What this does:
#   1. Fail-closed preflight for the pinned EDA toolchain (before any model call).
#   2. Stages the evaluator source snapshot the controller hashes and re-verifies.
#   3. Starts a Ray head advertising the yosys / opencode_creds resources.
#   4. Runs orchestration/peweaver_chia_graph.py (ChiaMerge, MergeDiscovery):
#      adviser + implementer propose candidates; lint, bit-exact functional,
#      physical (Yosys -> mapped Icarus GLS -> OpenROAD -> OpenSTA), and
#      portfolio gates decide promotion. Acceptance is not guaranteed.
#
# Configuration (environment variables, all optional):
#   PEWEAVER_OSS          oss-cad-suite bin dir (yosys, verilator, iverilog, vvp)
#   PEWEAVER_OPENROAD     OpenROAD binary
#   PEWEAVER_VOLARE_VENV  volare virtualenv (physical flow)
#   PEWEAVER_PDK_ROOT     volare PDK root containing sky130A
#   PEWEAVER_RUNS_BASE    output directory for runs           [~/peweaver-review-runs]
#   PEWEAVER_DEPLOYED     evaluator snapshot dir              [<runs>/peweaver_deployed]
#   PLANNER_MODEL         adviser model string                [openai/gpt-5.6-sol]
#   WORKER_MODEL          implementer model string            [opencode-go/deepseek-v4.1-flash]
#   TURNS                 optimization turns                  [12]
#   RUN_ID                run id                              [fft-chiamerge-<timestamp>]
#
# Usage:
#   ./run-fft-chiamerge.sh            # preflight + full loop (hours; physical per turn)
#   ./run-fft-chiamerge.sh --dry-run  # preflight + resolved env only; no Ray, no model calls
#
# Both model roles use the opencode CLI; log in first (opencode auth login).
# A worker/planner model string starting with gemini/ uses the Gemini Developer
# API instead and additionally requires GEMINI_API_KEY.
set -Eeuo pipefail

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
die() { printf 'run-fft-chiamerge: %s\n' "$*" >&2; exit 1; }

DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
CHIA_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd -P)"
PEWEAVER_DIR="$CHIA_ROOT/examples/peweaver"

OSS_BIN="${PEWEAVER_OSS:-/work/peweaver/toolchains/oss-cad-suite/bin}"
OPENROAD_BIN="${PEWEAVER_OPENROAD:-/work/peweaver/toolchains/openroad/usr/bin/openroad}"
VOLARE_VENV="${PEWEAVER_VOLARE_VENV:-/work/peweaver/toolchains/physical-venv}"
PDK_ROOT="${PEWEAVER_PDK_ROOT:-/work/peweaver/toolchains/.volare}"
RUNS_BASE="${PEWEAVER_RUNS_BASE:-$HOME/peweaver-review-runs}"
DEPLOYED="${PEWEAVER_DEPLOYED:-$RUNS_BASE/peweaver_deployed}"
PLANNER_MODEL="${PLANNER_MODEL:-openai/gpt-5.6-sol}"
WORKER_MODEL="${WORKER_MODEL:-opencode-go/deepseek-v4.1-flash}"
TURNS="${TURNS:-12}"
RUN_ID="${RUN_ID:-fft-chiamerge-$(date +%Y%m%d-%H%M%S)}"

log "chia root: $CHIA_ROOT"

command -v python3 >/dev/null 2>&1 || die "python3 not found on PATH"
python3 -c "import ray" 2>/dev/null \
  || die "python module 'ray' missing; run: python3 -m pip install -e $CHIA_ROOT"
for tool in yosys verilator iverilog vvp; do
  if [ ! -x "$OSS_BIN/$tool" ] && ! command -v "$tool" >/dev/null 2>&1; then
    die "tool '$tool' not executable in $OSS_BIN or PATH (set PEWEAVER_OSS)"
  fi
done
[ -x "$OPENROAD_BIN" ] \
  || die "OpenROAD not executable: $OPENROAD_BIN (set PEWEAVER_OPENROAD)"
[ -x "$VOLARE_VENV/bin/python" ] \
  || die "volare venv python missing: $VOLARE_VENV/bin/python (set PEWEAVER_VOLARE_VENV)"
if [ ! -d "$PDK_ROOT/sky130A" ] && [ ! -d "$PDK_ROOT/volare" ]; then
  log "WARN: $PDK_ROOT does not look like a volare/sky130A PDK root; the physical flow will enforce this itself"
fi
command -v opencode >/dev/null 2>&1 || die "opencode CLI not on PATH (see https://opencode.ai)"
opencode --version >/dev/null 2>&1 || die "opencode CLI is installed but not runnable"

NEEDS_GEMINI=0
case "$WORKER_MODEL" in gemini/*) NEEDS_GEMINI=1 ;; esac
case "$PLANNER_MODEL" in gemini/*) NEEDS_GEMINI=1 ;; esac
RAY_RESOURCES='{"yosys":1,"opencode_creds":1}'
if [ "$NEEDS_GEMINI" = 1 ]; then
  [ -n "${GEMINI_API_KEY:-}" ] \
    || die "a gemini/* model was selected but GEMINI_API_KEY is unset"
  RAY_RESOURCES='{"yosys":1,"opencode_creds":1,"gemini_creds":1}'
fi

if [ ! -d "$DEPLOYED" ]; then
  log "staging evaluator snapshot -> $DEPLOYED"
  mkdir -p "$RUNS_BASE"
  cp -a "$PEWEAVER_DIR" "$DEPLOYED"
  find "$DEPLOYED" -type d \( -name __pycache__ -o -name .pytest_cache \) \
    -prune -exec rm -rf {} + 2>/dev/null || true
fi
for need in \
  orchestration/peweaver_chia_graph.py \
  orchestration/shared_fft_regression.py \
  orchestration/evaluator_nodes.py \
  physical/run-physical.sh \
  physical/rtl/peweaver_shared_fft.v \
  physical/synth/sky130_simple_map.v \
  physical/results/leakage_check/nand2_leakage_check.json \
  third_party/r22sdf/FFT64.v \
  third_party/r22sdf/FFT128.v; do
  [ -f "$DEPLOYED/$need" ] \
    || die "evaluator snapshot incomplete: $DEPLOYED/$need missing (delete $DEPLOYED and rerun to restage)"
done

export PYTHONPATH="$CHIA_ROOT:$CHIA_ROOT/examples/peweaver/orchestration${PYTHONPATH:+:$PYTHONPATH}"
export PEWEAVER_OSS="$OSS_BIN"
export PEWEAVER_OPENROAD="$OPENROAD_BIN"
export PEWEAVER_VOLARE_VENV="$VOLARE_VENV"
export PEWEAVER_PDK_ROOT="$PDK_ROOT"
export PEWEAVER_DEPLOYED="$DEPLOYED"
export PEWEAVER_RUNS_BASE="$RUNS_BASE"

log "planner=$PLANNER_MODEL worker=$WORKER_MODEL turns=$TURNS"
log "run base : $RUNS_BASE"
log "run id   : $RUN_ID"

if [ "$DRY_RUN" = 1 ]; then
  log "dry run: preflight passed; not starting Ray and not making any model call"
  exit 0
fi

RAY_STARTED_HERE=0
if ! ray status >/dev/null 2>&1; then
  log "starting Ray head with resources $RAY_RESOURCES"
  ray start --head --resources="$RAY_RESOURCES" >/dev/null
  RAY_STARTED_HERE=1
else
  log "using existing Ray cluster"
fi
cleanup() {
  if [ "$RAY_STARTED_HERE" = 1 ]; then
    log "stopping Ray"
    ray stop --force >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

python3 - "$RAY_RESOURCES" <<'PY' || die "Ray cluster resource check failed"
import json, sys

import ray

ray.init(address="auto", ignore_reinit_error=True)
resources = ray.cluster_resources()
required = json.loads(sys.argv[1])
missing = [name for name, amount in required.items()
           if float(resources.get(name, 0.0)) < float(amount)]
if missing:
    raise SystemExit(f"Ray cluster lacks required resources: {missing}")
PY

cd "$CHIA_ROOT"
log "running ChiaMerge FFT driver (per-turn physical flow takes about an hour; total runtime scales with turns)"
set +e
python3 examples/peweaver/orchestration/peweaver_chia_graph.py \
  --run-id "$RUN_ID" \
  --turns "$TURNS" \
  --planner-model "$PLANNER_MODEL" \
  --worker-model "$WORKER_MODEL"
rc=$?
set -e

log "driver exit code: $rc"
log "run record  : $RUNS_BASE/$RUN_ID (controller log + artifacts/, lineage in artifacts/lineage.sqlite3)"
log "best RTL    : $RUNS_BASE/$RUN_ID/best/peweaver_shared_fft.v (only after ACCEPT)"
log "physical JSON: $RUNS_BASE/.evaluators/$RUN_ID/source/physical/results/shared_baseline_sky130.json"
exit "$rc"
