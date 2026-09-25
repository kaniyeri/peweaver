#!/usr/bin/env python3
"""FFT ChiaPowerSave driver: power optimization of the accepted shared FFT.

Same domain-neutral ChiaPowerSave composition, FFT-specific inputs/gates:
the incumbent is the accepted clean-room shared candidate; candidates are
one-file `peweaver_shared_fft.v` rewrites under one atomic hypothesis.

Gate cascade: lint -> functional (deterministic judge script) -> synth
proxy (area floor pre-check) -> physical (full run-physical.sh flow:
mapped GLS, P&R, extracted activity power). Objectives all minimized:
placed area, mode-64/128 streaming power, mode-64/128 finite energy.

Hard constraint: >=20% placed-area reduction vs the standalone sum
(424,885 um^2) is retained. Targets: per-mode standalone power/energy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

from chia.base.ChiaFunction import ChiaFunction, get

from chia_merge import ChiaAdvise, ChiaImplement, GateOutcome, RunPaths
from chia_power_save import ChiaPowerSave, PowerObjectives
from evaluator_nodes import (call_node, dispatch, lint_node,
                             yosys_node, RetryableError)

PE = Path(__file__).resolve().parents[1]
DEPLOYED = Path("/work/peweaver/source/chia/examples/peweaver")
RUNS_BASE = Path("/work/peweaver/runs")
OSS = "/work/peweaver/toolchains/oss-cad-suite/bin"
CANDIDATE = "peweaver_shared_fft.v"
WRAPPER = "peweaver_ppa_shared_fft.v"

STANDALONE_SUM = 424885.0
AREA_FLOOR = 0.20                      # >=20% placed-area reduction retained
TARGETS = {"p64": 23.314, "p128": 41.040, "e64": 20.40, "e128": 71.20}

INCUMBENT_SHA = "ce64c715"             # first 16 hex; verified at startup

CONTRACT = """BEHAVIORAL CONTRACT (immutable; the incumbent already satisfies it)
- Streaming 64/128-point FFT, one module peweaver_shared_fft, parameter
  WIDTH=16, ports: clock, reset (synchronous active-high), mode (0=64,
  1=128), di_en, di_re[15:0], di_im[15:0], do_en, do_re[15:0], do_im[15:0].
- Exact first-valid latency: 71 cycles (mode 64) / 137 cycles (mode 128)
  after the first di_en edge post-reset.
- One output sample per valid cycle, continuous frames, no gaps in do_en
  during a frame; frame lengths 64/128.
- Scaled 1/N fixed-point FFT; outputs bit-exact to the frozen references
  on the full directed + randomized judges (do NOT touch arithmetic).
- reset clears all pipeline state; mode changes only via the reset-
  separated transition protocol; aborting a frame mid-input is allowed and
  must not corrupt the next frame after reset.
- The next frame must be correct even if the previous frame's outputs were
  not drained.

OPTIMIZATION OBJECTIVE (power) with hard correctness floor
- Reduce measured power/energy (clocked-state and clock-tree activity
  dominate; leakage is tiny). Candidates must hold: bit-exact behavior,
  exact latency/valid windows, mapped GLS, timing met TNS 0, DRC 0, and
  placed cell area at least 20% below 424,885 um^2.
- Clock gating ONLY via characterized cells (sky130_fd_sc_hd__dlclkp) is
  acceptable; NEVER generate a clock with `clock & enable`, a ternary
  clock, or uncharacterized combinational gating.

FORBIDDEN: $readmem*/$fopen/initial/final/delays/DPI/PLI/tb constructs;
changing ports, latency, arithmetic, or the frozen corner.
"""


@ChiaFunction(resources={"yosys": 1})
def fft_physical_gate(run_root: str) -> dict:
    """Full physical flow via run-physical.sh; returns measured objectives.

    passed=False (with detail) means REGRESSION (hard-gate failure);
    retry=True means infrastructure failure.
    """
    phys = Path(run_root) / "source" / "physical"
    env = dict(os.environ)
    env["PATH"] = OSS + ":/work/peweaver/toolchains/openroad/bin:" + env.get("PATH", "")
    env["PEWEAVER_VOLARE_VENV"] = "/work/peweaver/toolchains/physical-venv"
    env["PEWEAVER_PDK_ROOT"] = "/work/peweaver/toolchains/.volare"
    env["PEWEAVER_PYTHON"] = "/work/peweaver/toolchains/miniforge3/envs/chia_env/bin/python"
    env["PEWEAVER_DESIGN"] = "shared"
    stale = phys / "results" / "shared_baseline_sky130.json"
    if stale.exists():
        stale.unlink()
    # the design-independent leakage sanity record lives in the deployed
    # physical results; restore it (assembly requires it, fail-closed)
    leak_src = Path(__file__).resolve().parents[1] / "physical" / "results" / "leakage_check"
    leak_dst = phys / "results" / "leakage_check"
    if leak_src.is_dir() and not leak_dst.is_dir():
        shutil.copytree(leak_src, leak_dst)
    import subprocess
    try:
        p = subprocess.Popen(["./run-physical.sh"], cwd=str(phys), env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, start_new_session=True)
        out, _ = p.communicate(timeout=10800)
        rc = p.returncode
    except subprocess.TimeoutExpired:
        import signal
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass
        return {"passed": False, "retry": True, "note": "physical flow timeout"}
    result_path = phys / "results" / "shared_baseline_sky130.json"
    if not result_path.is_file():
        tail = (out or "")[-400:]
        return {"passed": False, "note": f"result JSON missing; rc={rc}; {tail}"}
    d = json.loads(result_path.read_text())
    pnr = d.get("results", {}).get("pnr", {})
    power = d.get("results", {}).get("power_mw", {})
    energy = d.get("results", {}).get("energy_per_fft_nj", {})
    metrics = {
        "area": pnr.get("cell_area_um2"),
        "p64": (power.get("streaming_window_64", {}) or {}).get("total_mw"),
        "p128": (power.get("streaming_window_128", {}) or {}).get("total_mw"),
        "e64": (energy.get("mode64", {}) or {}).get("value"),
        "e128": (energy.get("mode128", {}) or {}).get("value"),
    }
    timing_met = pnr.get("timing_met")
    drc = d.get("drc_violation_lines")
    if metrics["area"] is None or timing_met is None:
        return {"passed": False, "note": "physical result incomplete"}
    if not timing_met or (drc or 0) > 0:
        return {"passed": False,
                "detail": {k: v for k, v in metrics.items() if v is not None},
                "note": f"timing_met={timing_met} drc={drc}"}
    return {"passed": True, "note": "physical flow passed",
            "detail": metrics}


def _physical_outcome(r: dict) -> GateOutcome:
    """Convert the physical node dict to a GateOutcome (name='physical')."""
    return GateOutcome("physical", bool(r.get("passed")),
                       note=str(r.get("note", ""))[:400],
                       retry=bool(r.get("retry", False)),
                       detail={k: v for k, v in r.get("detail", {}).items()
                               if isinstance(v, (int, float))
                               and not isinstance(v, bool)})


def make_cheap_gates(run_root: Path):
    rtl_dir = run_root / "source" / "physical" / "rtl"

    def g_lint(sandbox: Path) -> GateOutcome:
        cand = sandbox / CANDIDATE
        if not cand.is_file():
            return GateOutcome("lint", False, note=f"{CANDIDATE} missing")
        return dispatch(lint_node, cand.read_text(), "peweaver_shared_fft",
                        ["clock", "reset", "mode", "di_en", "di_re", "di_im",
                         "do_en", "do_re", "do_im"], name="lint")

    def g_functional(sandbox: Path) -> GateOutcome:
        cand = sandbox / CANDIDATE
        if not cand.is_file():
            return GateOutcome("functional", False, note="candidate missing")
        rtl_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cand, rtl_dir / CANDIDATE)
        import subprocess
        src = run_root / "source"
        env = dict(os.environ)
        env["PATH"] = OSS + ":/work/peweaver/toolchains/openroad/bin:" + env.get("PATH", "")
        proc = subprocess.run(
            ["python3", "orchestration/shared_fft_regression.py",
             "--candidate", f"physical/rtl/{CANDIDATE}", "--json"],
            cwd=str(src), env=env, capture_output=True, text=True,
            timeout=1800)
        parsed = {}
        for line in reversed(proc.stdout.splitlines()):
            if line.strip().startswith("{"):
                try:
                    parsed = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
        ok = proc.returncode == 0 and bool(parsed.get("passed"))
        tail = str(parsed.get("log_tail", ""))[-300:]
        return GateOutcome("functional", ok, note=tail or "no judge output")

    def g_area_proxy(sandbox: Path) -> GateOutcome:
        cand = sandbox / CANDIDATE
        if not cand.is_file():
            return GateOutcome("area_proxy", False, note="candidate missing")
        work = run_root / "synth_work"
        work.mkdir(parents=True, exist_ok=True)
        vf = work / "cand_proxy.v"
        vf.write_text(cand.read_text())
        script = (f"read_verilog -sv {vf}; synth -top peweaver_shared_fft "
                  f"-flatten; stat")
        try:
            raw = call_node(yosys_node, script, oss_bin=OSS, timeout=900)
        except RetryableError as exc:
            return GateOutcome("area_proxy", False, note=str(exc),
                               retry=True)
        # full post-mortem capture (attribution: gate diagnostics only)
        (run_root / "artifacts" / f"area_proxy_full.log").write_text(
            "RC=" + str(raw.get("rc")) + "\n== STDOUT ==\n"
            + raw.get("note", "") + "\n== STDERR ==\n"
            + raw.get("stderr", ""))
        r = GateOutcome("area_proxy", bool(raw.get("passed")),
                        note=str(raw.get("note", ""))[-400:],
                        detail={"stderr": raw.get("stderr", ""),
                                "rc": raw.get("rc")})
        if r.retry:
            return r
        cells = re.findall(r"^\s*(\d+)\s+cells\s*$",
                           raw.get("note", ""), re.M)
        if not r.passed or not cells:
            err_tail = str(r.detail.get("stderr", ""))[-200:] if isinstance(
                r.detail, dict) else ""
            return GateOutcome("area_proxy", False,
                               note=f"proxy synth failed: {err_tail or r.note[-200:]}",
                               retry=not r.passed)
        synth_cells = int(cells[-1])
        # incumbent generic synth cell count 32,745; the proxy only guards
        # against runaway growth (the real area floor is enforced on the
        # placed area by the hard constraint)
        if synth_cells > 32745 * 1.03:
            return GateOutcome(
                "area_proxy", False,
                note=f"synth cell count {synth_cells} exceeds incumbent +3%")
        return GateOutcome("area_proxy", True,
                           note=f"synth cell count {synth_cells} (incumbent "
                                f"32745) ok")

    return [g_lint, g_functional, g_area_proxy]


def make_advise_and_do(run: RunPaths, adviser_model: str,
                       worker_model: str, inc: Path):
    adviser = ChiaAdvise(adviser_model, run.root, timeout=1500,
                         log_dir=run.artifacts)
    implementer = ChiaImplement(worker_model, run.root, timeout=1800,
                                log_dir=run.artifacts)

    attribution_path = run.artifacts / "attribution_summary.json"
    attribution_text = ""
    if attribution_path.is_file():
        attribution_text = ("\nMeasured power attribution (evidence, W; "
                            "region shares from the name-preserving "
                            "attribution flow — use it to rank hypotheses):\n"
                            + attribution_path.read_text()[:4000])

    def advise_fn(state) -> str:
        parts = [
            "You are the power-optimization lead for the accepted shared FFT.",
            "One ATOMIC hypothesis per candidate; complete replacement of the "
            "single candidate file; contract is immutable.",
            "Incumbent measured objectives (lower is better): "
            + json.dumps(state.best_metrics or {}),
            "Pareto archive (metrics only): "
            + json.dumps([p.get("metrics") for p in state.archive[-6:]]),
            "Previous turn feedback: " + (state.feedback or "none")[:800],
            attribution_text,
            "CONTRACT:\n" + CONTRACT,
        ]
        return adviser("\n".join(parts))

    incumbent_text = inc.read_text()

    def do_fn(state, sandbox: Path):
        prompt = (
            "Implement the lead's single atomic hypothesis as a COMPLETE "
            "replacement of peweaver_shared_fft.v. Reply with one fenced "
            "```verilog code block containing the entire module tree needed "
            "for that file (top module peweaver_shared_fft only, no "
            "submodules unless present in the incumbent).\n\n"
            "HYPOTHESIS:\n" + (state.hypothesis or state.advice or "")[:3000]
            + "\n\nPREVIOUS TURN FEEDBACK:\n"
            + (state.feedback or "none")[:2000]
            + "\n\nCONTRACT:\n" + CONTRACT
            + "\n\nINCUMBENT CANDIDATE (complete current source; produce "
              "the full replacement):\n```verilog\n"
            + incumbent_text[:120000] + "\n```")
        ok, reason = implementer(prompt)
        if not ok:
            return False, reason
        code = reason
        (sandbox / CANDIDATE).write_text(code)
        return True, reason[:200]

    return advise_fn, do_fn


def config_fingerprint() -> dict:
    files = ["orchestration/power_save_fft_driver.py",
             "orchestration/chia_power_save.py",
             "orchestration/chia_merge.py",
             "orchestration/evaluator_nodes.py",
             "orchestration/shared_fft_regression.py",
             "physical/run-physical.sh",
             "physical/rtl/peweaver_ppa_shared_fft.v"]
    fp = {}
    for rel in files:
        p = PE / rel
        fp[rel] = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    fp["objectives"] = ["area", "p64", "p128", "e64", "e128"]
    fp["targets"] = TARGETS
    fp["area_floor"] = AREA_FLOOR
    return fp


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--incumbent", required=True, type=Path,
                    help="directory containing the accepted candidate file "
                         "OR the file itself")
    ap.add_argument("--candidates", type=int, default=16)
    ap.add_argument("--physical-runs", type=int, default=5)
    ap.add_argument("--planner-model", default="openrouter/openai/gpt-5.6-sol")
    ap.add_argument("--worker-model", default="gemini/gemini-3.8-flash")
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    inc = args.incumbent
    if inc.is_dir():
        inc = inc / CANDIDATE
    if not inc.is_file():
        print(json.dumps({"error": "incumbent missing", "path": str(inc)}))
        return 2
    sha = hashlib.sha256(inc.read_bytes()).hexdigest()
    if not sha.startswith(INCUMBENT_SHA):
        print(json.dumps({"error": "incumbent hash mismatch",
                          "expected_prefix": INCUMBENT_SHA, "got": sha}))
        return 2

    run_root = RUNS_BASE / args.run_id
    source = run_root / "source"
    if not source.is_dir():
        shutil.copytree(DEPLOYED, source, symlinks=True)
    # stale snapshot results would trip the flow's fail-closed checks
    shutil.rmtree(source / "physical" / "results", ignore_errors=True)
    run = RunPaths.create(run_root)

    def _physical_gate(ws: Path) -> GateOutcome:
        # copy the workspace candidate into the judge's source tree so the
        # physical flow measures THIS candidate (also covers incumbent
        # seeding, which runs before any cheap gate)
        rtl = run_root / "source" / "physical" / "rtl"
        rtl.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ws / CANDIDATE, rtl / CANDIDATE)
        return _physical_outcome(
            get(fft_physical_gate.chia_remote(str(run_root))))

    ps = ChiaPowerSave(
        run, incumbent=inc, candidate_filename=CANDIDATE,
        cheap_gates=make_cheap_gates(run_root),
        physical_gate=_physical_gate,
        objectives=PowerObjectives(
            names=("area", "p64", "p128", "e64", "e128"), targets=TARGETS,
            physical_trigger_frac=0.0),
        hard_constraints=(
            lambda m: (None if m["area"] <= STANDALONE_SUM * (1 - AREA_FLOOR)
                       else f"area {m['area']:.0f} above the 20% floor "
                            f"{STANDALONE_SUM * (1 - AREA_FLOOR):.0f}"),),
        advise_fn=None, do_fn=None,
        max_candidates=args.candidates, max_physical=args.physical_runs,
        config_fingerprint=config_fingerprint())

    # advise/do need the run object; inject after construction
    advise_fn, do_fn = make_advise_and_do(run, args.planner_model,
                                          args.worker_model, inc)
    ps.advise_fn = advise_fn
    ps.do_fn = do_fn

    state = ps.run(resume=args.resume)
    if state.accepted or state.best_verdict in ("PARETO", "TARGET"):
        report = ps.verify_final(state)
    else:
        report = {"verified": False, "reason": "no accepted Pareto point"}
    print(json.dumps({"run_id": args.run_id, "accepted": state.accepted,
                      "best_verdict": state.best_verdict,
                      "best_metrics": state.best_metrics,
                      "archive": len(state.archive),
                      "turns": state.turn,
                      "physical_runs": state.physical_runs,
                      "stop_reason": state.stop_reason,
                      "final_repeat": report}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
