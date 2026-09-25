#!/usr/bin/env python3
"""Fast no-P&R ladder driver for the shared-FFT model sweep.

Ladder: lint -> bit-exact functional (Verilator, both modes) -> synthesis-level
sharing floor (yosys generic cell count vs the two-reference sum) -> hidden
holdout (36 controller-owned cases incl. exact 71/137-cycle latency).

Acceptance = all four gates pass.  Physical P&R is deliberately excluded from
this ladder; accepted candidates can be physically validated separately.
The floor gate is an unweighted generic-cell-count proxy, not placed area.

Calibrate once before the sweep:
    python3 sweep_fft_driver.py --calibrate
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from chia.base.ChiaFunction import get  # noqa: E402
from chia_merge import ChiaMerge, GateOutcome  # noqa: E402
from evaluator_nodes import RetryableError, call_node, yosys_node  # noqa: E402
from hidden_holdout import run_suite as holdout_run_suite  # noqa: E402
from peweaver_chia_graph import (  # noqa: E402
    CANDIDATE,
    CONTRACT,
    INPUTS,
    OSS,
    RUNS_BASE,
    functional_gate,
    lint_gate,
)

FLOOR_RATIO = 0.80
CALIBRATION_FILE = RUNS_BASE / "msweep_area_calibration.json"
CALIBRATION_CANDIDATES = [
    RUNS_BASE / "merge-clean-1/best/peweaver_shared_fft.v",
    RUNS_BASE / "merge-repro-1/best/peweaver_shared_fft.v",
    RUNS_BASE / "merge-repro-2/best/peweaver_shared_fft.v",
    RUNS_BASE / "merge-repro-3/best/peweaver_shared_fft.v",
    RUNS_BASE / "ps-fft-6/best/peweaver_shared_fft.v",
]
CELLS_RE = re.compile(r"^\s*(\d+)\s+cells\s*$", re.M)
DEPLOYED_ROOT = Path("/work/peweaver/source/chia/examples/peweaver_deployed")


def synth_cells_script(script: str, timeout: int = 600) -> tuple[bool, int | None, str]:
    r = call_node(yosys_node, script, oss_bin=OSS, timeout=timeout)
    m = CELLS_RE.search(r["note"])
    if not r["passed"] or not m:
        return False, int(m.group(1)) if m else None, r["note"][-400:]
    return True, int(m.group(1)), "ok"


def synth_cells_from_text(text: str, top: str, work: Path) -> tuple[bool, int | None, str]:
    work.mkdir(parents=True, exist_ok=True)
    vfile = work / f"{top}_{hashlib.sha256(text.encode()).hexdigest()[:12]}.v"
    vfile.write_text(text)
    return synth_cells_script(
        f"read_verilog -sv {vfile}; synth -top {top} -flatten; stat")


def _reference_scripts() -> dict[str, str]:
    """The project's own baseline recipes, relative to deployed/, minus mapping."""
    base = DEPLOYED_ROOT
    r64 = [
        "physical/rtl/peweaver_ppa_fft64.v",
        "benchmarks/halo_fft64_reference/peweaver_halo_fft64_reference.v",
        "third_party/r22sdf/FFT64.v",
        "third_party/r22sdf/SdfUnit.v",
        "third_party/r22sdf/SdfUnit2.v",
        "third_party/r22sdf/Butterfly.v",
        "third_party/r22sdf/DelayBuffer.v",
        "third_party/r22sdf/Multiply.v",
        "third_party/r22sdf/Twiddle64.v",
    ]
    r128 = [
        "physical/rtl/peweaver_ppa_fft128.v",
        "benchmarks/halo_fft128_reference/peweaver_halo_fft128_reference.v",
        "third_party/r22sdf/FFT128.v",
        "third_party/r22sdf/SdfUnit.v",
        "third_party/r22sdf/SdfUnit2.v",
        "third_party/r22sdf/Butterfly.v",
        "third_party/r22sdf/DelayBuffer.v",
        "third_party/r22sdf/Multiply.v",
        "third_party/r22sdf/Twiddle128.v",
    ]
    out = {}
    for top, rels in (("peweaver_ppa_fft64", r64),
                      ("peweaver_ppa_fft128", r128)):
        files = " ".join(str(base / rel) for rel in rels)
        out[top] = (f"read_verilog -sv {files}; hierarchy -check -top {top}; "
                    f"synth -top {top} -flatten; stat")
    return out


def calibrate(floor_ratio: float) -> dict:
    work = RUNS_BASE / "msweep_calibration_work"
    refs: dict[str, int] = {}
    for top, script in _reference_scripts().items():
        ok, cells, note = synth_cells_script(script, timeout=900)
        if not ok or cells is None:
            raise RuntimeError(f"reference synthesis failed for {top}: {note}")
        refs[top] = cells
    reference_sum = sum(refs.values())
    floor_cells = int(reference_sum * floor_ratio)
    entries = []
    for path in CALIBRATION_CANDIDATES:
        if not path.is_file():
            entries.append({"path": str(path), "present": False})
            continue
        ok, cells, note = synth_cells_from_text(path.read_text(),
                                                "peweaver_shared_fft", work)
        entry = {"path": str(path), "present": True, "synth_ok": ok,
                 "cell_count": cells}
        if ok and cells:
            entry["reduction_pct"] = round(100 * (1 - cells / reference_sum), 2)
            entry["passes_floor"] = cells <= floor_cells
        entries.append(entry)
    calibration = {
        "schema": "peweaver-msweep-area-calibration-1",
        "created": time.time(),
        "floor_ratio": floor_ratio,
        "reference_cells": refs,
        "reference_sum_cells": reference_sum,
        "floor_cells": floor_cells,
        "metric": ("unweighted Yosys generic cell count after 'synth -top' "
                   "(proxy only; not mapped or placed area)"),
        "candidates": entries,
    }
    CALIBRATION_FILE.write_text(json.dumps(calibration, indent=1))
    return calibration


def make_sweep_ladder(run_root: Path):
    """[lint, functional, area, holdout] gate callables over a sandbox."""
    source = run_root / "source"
    rtl_dir = source / "physical" / "rtl"
    area_holder: dict = {}

    def copy_candidate(sandbox: Path):
        cand = sandbox / CANDIDATE
        if not cand.is_file():
            return None
        rtl_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cand, rtl_dir / CANDIDATE)
        return cand

    def g_lint(sandbox: Path) -> GateOutcome:
        cand = sandbox / CANDIDATE
        if not cand.is_file():
            return GateOutcome("lint", False,
                               note=f"{CANDIDATE} missing from the attempt")
        r = get(lint_gate.chia_remote(cand.read_text()))
        return GateOutcome("lint", bool(r["passed"]),
                           note="; ".join(r["errors"])[:300] or "clean")

    def g_functional(sandbox: Path) -> GateOutcome:
        if copy_candidate(sandbox) is None:
            return GateOutcome("functional", False, note="candidate missing")
        r = get(functional_gate.chia_remote(str(run_root)))
        return GateOutcome("functional", bool(r.get("passed")),
                           note=(r.get("summary") or "no judge output")[-400:])

    def g_area(sandbox: Path) -> GateOutcome:
        cand = sandbox / CANDIDATE
        if not cand.is_file():
            return GateOutcome("area", False, note="candidate missing")
        if not CALIBRATION_FILE.is_file():
            return GateOutcome("area", False,
                               note="area calibration missing", retry=True)
        calibration = json.loads(CALIBRATION_FILE.read_text())
        text = cand.read_text()
        key = hashlib.sha256(text.encode()).hexdigest()
        if key not in area_holder:
            ok, cells, note = synth_cells_from_text(
                text, "peweaver_shared_fft", run_root / "yosys_work")
            if not ok:
                return GateOutcome("area", False,
                                   note=f"yosys could not synthesize candidate: {note}")
            area_holder[key] = cells
        cells = area_holder[key]
        reference_sum = calibration["reference_sum_cells"]
        floor = calibration["floor_cells"]
        reduction = round(100 * (1 - cells / reference_sum), 2)
        detail = {"cand_cell_count": cells,
                  "baseline_cell_count": reference_sum,
                  "floor_cell_count": floor,
                  "reduction_pct": reduction}
        if cells > floor:
            return GateOutcome(
                "area", False,
                note=(f"generic cell count {cells} = {reduction:.1f}% below the "
                      f"two-reference sum {reference_sum}; floor is "
                      f"{calibration['floor_ratio'] * 100:.0f}% "
                      f"(<= {floor} cells)"),
                detail=detail)
        return GateOutcome(
            "area", True,
            note=(f"generic cell count {cells} = {reduction:.1f}% below the "
                  f"two-reference sum {reference_sum} (unweighted generic cell "
                  f"count, not mapped area)"),
            detail=detail)

    def g_holdout(sandbox: Path) -> GateOutcome:
        if copy_candidate(sandbox) is None:
            return GateOutcome("holdout", False, note="candidate missing")
        work = run_root / "evaluator_holdout" / f"gate_{int(time.time() * 1000)}"
        res = holdout_run_suite(rtl_dir / CANDIDATE, work)
        cases = int(res.get("cases") or 0)
        failed = res.get("failed") or []
        if cases:
            note = f"{cases - len(failed)}/{cases} hidden cases passed"
        else:
            note = str(res.get("error") or res.get("status") or "no cases")
        return GateOutcome("holdout", bool(res.get("passed")), note=note[:300])

    return [g_lint, g_functional, g_area, g_holdout]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id")
    parser.add_argument("--planner-model")
    parser.add_argument("--worker-model")
    parser.add_argument("--turns", type=int, default=16)
    parser.add_argument("--advise-timeout", type=int, default=1500)
    parser.add_argument("--implement-timeout", type=int, default=1200)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--calibrate", action="store_true")
    parser.add_argument("--floor-ratio", type=float, default=FLOOR_RATIO)
    parser.add_argument("--harness-v2", action="store_true",
                        help="retries + long provider timeouts + reply re-asks")
    args = parser.parse_args()

    if args.calibrate:
        import ray
        ray.init(address="auto", ignore_reinit_error=True)
        print(json.dumps(calibrate(args.floor_ratio), indent=1))
        return 0
    if not (args.run_id and args.planner_model and args.worker_model):
        parser.error("--run-id, --planner-model, --worker-model are required")

    import ray
    from peweaver_chia_graph import DEPLOYED

    started = time.time()
    run_root = RUNS_BASE / args.run_id
    source = run_root / "source"
    if not source.is_dir():
        print(f"[driver] copying deployed source tree -> {source}", flush=True)
        shutil.copytree(DEPLOYED, source, symlinks=True)
    missing = [str(p) for p in INPUTS.values() if not p.is_file()]
    if missing:
        print(json.dumps({"error": "missing input designs", "missing": missing}))
        return 2

    llm_retries, implement_attempts, provider_options = 1, 1, None
    if args.harness_v2:
        # Sol-reviewed protocol: three total attempts per call (initial + 2
        # retries, adapter-level, identical prompt, capped backoff); one
        # mechanical re-ask when the reply has no extractable code block
        # (same prompt, same turn); per-model viability config below.
        llm_retries, implement_attempts = 3, 2
        providers = sorted({m.split("/", 1)[0]
                            for m in (args.planner_model, args.worker_model)
                            if not m.startswith("gemini/")})
        provider_options = {p: {"options": {"timeout": 3_600_000,
                                            "headerTimeout": 600_000,
                                            "chunkTimeout": 1_800_000}}
                            for p in providers}
        # Per-model viability config (Sol-reviewed, predeclared): routes whose
        # gateway caps total output at 32k tokens cannot carry reasoning-heavy
        # models through long implement prompts, so thinking is disabled where
        # the backend supports it (deepseek, minimax) and reasoning budget is
        # otherwise bounded (kimi via OpenRouter).
        MODEL_OPTIONS = {
            "opencode-go/deepseek-v4.1-flash": (
                "opencode-go", "deepseek-v4.1-flash",
                {"thinking": {"type": "disabled"}}),
            "opencode-go/deepseek-v4-pro": (
                "opencode-go", "deepseek-v4-pro",
                {"thinking": {"type": "disabled"}}),
            "opencode-go/minimax-m3": (
                "opencode-go", "minimax-m3",
                {"thinking": {"type": "disabled"}}),
            "openrouter/moonshotai/kimi-k2.7-code": (
                "openrouter", "moonshotai/kimi-k2.7-code",
                {"reasoning": {"effort": "low"}}),
        }
        for model in (args.planner_model, args.worker_model):
            spec = MODEL_OPTIONS.get(model)
            if spec:
                provider, model_id, options = spec
                provider_options.setdefault(provider, {}).setdefault(
                    "models", {})[model_id] = {"options": options}

    gates = make_sweep_ladder(run_root)
    state = ChiaMerge(
        run_id=args.run_id, run_base=RUNS_BASE, inputs=INPUTS, contract=CONTRACT,
        gates=gates, accept_level=len(gates),
        adviser_model=args.planner_model, implementer_model=args.worker_model,
        candidate_filename=CANDIDATE, turns=args.turns,
        advise_timeout=args.advise_timeout,
        implement_timeout=args.implement_timeout, resume=args.resume,
        llm_retries=llm_retries, implement_attempts=implement_attempts,
        provider_options=provider_options,
        log_dir=run_root / "artifacts")

    ended = time.time()
    summary = {
        "run_id": args.run_id,
        "planner_model": args.planner_model,
        "worker_model": args.worker_model,
        "turns_cap": args.turns,
        "accepted": bool(state.accepted),
        "best_level": state.best_level,
        "turns_used": state.turn,
        "history_statuses": [h.get("status") for h in state.history],
        "started": started,
        "ended": ended,
        "seconds": round(ended - started, 1),
    }
    out = run_root / "artifacts" / "sweep_run_summary.json"
    try:
        out.write_text(json.dumps(summary, indent=1))
    except OSError as exc:
        print(f"[driver] could not write summary: {exc}", file=sys.stderr)
    print(json.dumps(summary), flush=True)
    return 0 if state.accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
