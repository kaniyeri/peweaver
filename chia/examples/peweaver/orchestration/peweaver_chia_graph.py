#!/usr/bin/env python3
"""PEWeaver native CHIA loop: clean-room pe-reuse merge on chialoops machinery.

    ChiaMerge(FFT64 references + FFT128 references + contract)
        = ChiaAdvise(architecture)   # once: derive the sharing strategy
          + ChiaIterate{ ChiaAdvise -> ChiaImplement -> ChiaCheckCondition
                         -> jump to top }

The worker starts from NOTHING but the pinned reference designs and the
behavioral contract; every attempt is a fresh sandbox judged by a
deterministic gate ladder (lint -> bit-exact functional -> physical ->
portfolio). Model stages run through CHIA's own adapter (``chia.models.
opencode.OpenCodeLLM``); gates are ``@ChiaFunction`` nodes dispatched onto
the Ray worker advertising the ``yosys`` resource.

Usage (on the VM, after `ray start --head` with yosys+opencode_creds):
    python orchestration/peweaver_chia_graph.py --run-id merge-clean-1
    python orchestration/peweaver_chia_graph.py --run-id merge-clean-1 --resume
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import shlex
import subprocess
import time
from pathlib import Path

import ray
from chia.base.ChiaFunction import ChiaFunction, get
from chia.models.opencode import OpenCodeLLM
from chia_merge import (MODE_DISCOVERY, MODE_PARENT, ChiaMerge, GateOutcome,
                        CheckResult, IterationState, _rmrf, workspace_manifest)
from evaluator_nodes import dispatch, timing_probe_node
from peweaver_archive import SQLiteArchive
from peweaver_evaluator import config_fingerprint, timing_feedback

DEPLOYED = Path(os.environ.get(
    "PEWEAVER_DEPLOYED", "/work/peweaver/source/chia/examples/peweaver_deployed"))
RUNS_BASE = Path(os.environ.get("PEWEAVER_RUNS_BASE", "/work/peweaver/runs"))
BASELINE_AREA_UM2 = 424885.0
CANDIDATE = "peweaver_shared_fft.v"
HISTORICAL_CANDIDATE_SHA256 = (
    "ce64c71552f0aa1750ae62c15a081d16d52e92396d9d67243088aeec4723e92e"
)

OSS = os.environ.get("PEWEAVER_OSS", "/work/peweaver/toolchains/oss-cad-suite/bin")
PDK_ROOT = os.environ.get("PEWEAVER_PDK_ROOT", "/work/peweaver/toolchains/.volare")

INPUTS = {
    "FFT64.v": DEPLOYED / "third_party" / "r22sdf" / "FFT64.v",
    "FFT128.v": DEPLOYED / "third_party" / "r22sdf" / "FFT128.v",
    "SdfUnit.v": DEPLOYED / "third_party" / "r22sdf" / "SdfUnit.v",
    "SdfUnit2.v": DEPLOYED / "third_party" / "r22sdf" / "SdfUnit2.v",
    "Multiply.v": DEPLOYED / "third_party" / "r22sdf" / "Multiply.v",
    "Butterfly.v": DEPLOYED / "third_party" / "r22sdf" / "Butterfly.v",
    "DelayBuffer.v": DEPLOYED / "third_party" / "r22sdf" / "DelayBuffer.v",
    "Twiddle64.v": DEPLOYED / "third_party" / "r22sdf" / "Twiddle64.v",
    "Twiddle128.v": DEPLOYED / "third_party" / "r22sdf" / "Twiddle128.v",
}

CONTRACT = """INTERFACE
- One top module named peweaver_shared_fft with exactly these ports:
  input clock, reset (active-high asynchronous assertion), mode
  (0 = 64-point, 1 = 128-point), di_en, di_re[15:0], di_im[15:0];
  output do_en, do_re[15:0], do_im[15:0]. No other external signals.

STREAMING CONTRACT
- One sample per clock accepted when di_en=1; no backpressure. Exactly N
  consecutive di_en samples form one frame (N=64 when mode=0, N=128 when
  mode=1), natural order.
- First do_en at exactly cycle 71 (64-point) or 137 (128-point), counted from
  the clock edge that accepts input sample 0; do_en stays high for exactly N
  cycles, then returns low.
- Sustained same-mode streaming: one frame accepted every N input cycles
  (one-output-per-cycle throughput during emission).
- mode may only be latched while idle; mode transitions require reset and an
  idle drain; after reset no output from a previous mode/frame may appear.

ARITHMETIC CONTRACT (16-bit two's-complement words interpreted as Q1.15)
- Butterfly: signed 17-bit add/sub; store (sum + RH) >>> 1 with arithmetic
  right shift (floor). First butterfly of every SdfUnit has RH=0, the second
  RH=1; SdfUnit2 has RH=0.
- Complex multiply: exact signed 16x16 products, each >>> 15 with no rounding
  bias, then real = pr - pi_shifted and imaginary = pr_shifted + pi
  (mod 2^16, no saturation).
- -j path: (re, im) -> (im, -re mod 2^16).
- Twiddles: the literal Q1.15 values of the reference tables; address zero
  bypasses the multiplier (as in Multiply.v).
- Total scaling 1/N. Input natural order, output bit-reversed emission order.

ACCEPTANCE GATES (checked by a deterministic judge after each attempt)
- Bit-exact match against both reference cores: single frames, continuous
  multi-frame bursts, and reset/mode-transition schedules, in both modes.
- Then synthesis, mapped-netlist gate-level simulation, place & route on
  sky130A at 10 ns: timing met with TNS 0, DRC 0, and placed cell area
  strictly below 424,885 um^2 (the combined two-core baseline).

FORBIDDEN: $readmem*, $fopen/system tasks, initial/final blocks, delays,
DPI/PLI, testbench constructs."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tool_env() -> dict:
    env = dict(os.environ)
    env["PATH"] = OSS + ":" + env.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    env["PEWEAVER_YOSYS"] = f"{OSS}/yosys"
    env["PEWEAVER_VERILATOR"] = f"{OSS}/verilator"
    env["PEWEAVER_IVERILOG"] = f"{OSS}/iverilog"
    env["PEWEAVER_VVP"] = f"{OSS}/vvp"
    env["PEWEAVER_OPENROAD"] = "/work/peweaver/toolchains/openroad/usr/bin/openroad"
    env["PEWEAVER_VOLARE_VENV"] = "/work/peweaver/toolchains/physical-venv"
    env["PEWEAVER_PDK_ROOT"] = PDK_ROOT
    return env


# ---------------------------------------------------------------------------
# Deterministic gates (dispatched onto the yosys worker)
# ---------------------------------------------------------------------------

_ANTI_CHEAT = (
    (re.compile(r"\$system\b|\$readmem(?:h|b)?\b", re.I), "system or readmem I/O"),
    (re.compile(r"\$(?:fopen|fread|fwrite|fscanf|fclose)\b", re.I), "file I/O"),
    (re.compile(r"\b(?:DPI|PLI)\b|import\s+\"DPI-C\"", re.I), "DPI/PLI"),
    (re.compile(r"\$test\$plusargs\b", re.I), "plusargs"),
    (re.compile(r"\b(?:initial|final)\b", re.I), "initial/final block"),
    (re.compile(r"\b(?:tb|testbench|uut|dut)\s*\.", re.I), "hierarchical tb ref"),
)


@ChiaFunction(resources={"yosys": 1})
def lint_gate(rtl_text: str) -> dict:
    """Static anti-cheat + synthesizability scan of the candidate text."""
    code = re.sub(r"/\*.*?\*/", " ", rtl_text, flags=re.S)
    code = re.sub(r"//[^\n]*", " ", code)
    code = re.sub(r'"(?:[^"\\]|\\.)*"', " ", code)
    errors = [label for pattern, label in _ANTI_CHEAT if pattern.search(code)]
    no_params = re.sub(r"#\s*\(\s*(?:\.|parameter\b|localparam\b)", "PARAMS(", code)
    if re.search(r"#\s*(?:\d|\w+)", no_params):
        errors.append("simulation delay")
    for port in ("clock", "mode", "di_re", "di_im", "di_en",
                 "do_re", "do_im", "do_en"):
        if not re.search(rf"\b{port}\b", rtl_text):
            errors.append(f"missing port: {port}")
    if not re.search(r"\breset\b|\breset_n\b", rtl_text):
        errors.append("missing port: reset/reset_n")
    if "module peweaver_shared_fft" not in rtl_text:
        errors.append("module peweaver_shared_fft not found")
    return {"passed": not errors, "errors": errors}


@ChiaFunction(resources={"yosys": 1})
def functional_gate(run_root: str) -> dict:
    """Bit-exact judge (Verilator RTL, both modes) from the immutable script."""
    src = Path(run_root) / "source"
    proc = subprocess.run(
        ["python3", "orchestration/shared_fft_regression.py",
         "--candidate", "physical/rtl/peweaver_shared_fft.v", "--json"],
        cwd=str(src), env=tool_env(), capture_output=True, text=True, timeout=900)
    parsed = {}
    for line in reversed(proc.stdout.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                parsed = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
    tail = str(parsed.get("log_tail", ""))
    summary = "".join(ch for ch in tail.replace("\n", " | ") if ch.isprintable())[-900:]
    return {"passed": proc.returncode == 0 and bool(parsed.get("passed")),
            "summary": summary, "returncode": proc.returncode}


def _run_child(cmd: list, cwd: str, env: dict, timeout: int):
    """Run *cmd* in its own process group; kill the whole group on timeout."""
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True,
                            start_new_session=True)
    try:
        return proc.communicate(timeout=timeout) + (proc.returncode,)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            proc.kill()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            pass
        raise


@ChiaFunction(resources={"yosys": 1})
def physical_gate(run_root: str, candidate_sha256: str) -> dict:
    """Full physical flow: Yosys -> Icarus GLS -> OpenROAD -> OpenSTA -> JSON."""
    phys = Path(run_root) / "source" / "physical"
    env = tool_env()
    env["PEWEAVER_DESIGN"] = "shared"
    try:
        out, err, rc = _run_child(["./run-physical.sh"], cwd=str(phys), env=env,
                                  timeout=7200)
    except subprocess.TimeoutExpired:
        return {"passed": False, "retry": True,
                "error": "physical flow timeout (7200s)"}
    result_path = phys / "results" / "shared_baseline_sky130.json"
    ppa: dict = {}
    if result_path.is_file():
        try:
            d = json.loads(result_path.read_text())
            pnr = d.get("results", {}).get("pnr", {})
            power = d.get("results", {}).get("power_mw", {})
            ppa = {
                "cell_area_um2": pnr.get("cell_area_um2"),
                "instance_count": pnr.get("instance_count"),
                "timing_met": pnr.get("timing_met"),
                "setup_slack_ns": pnr.get("setup_slack_ns"),
                "hold_slack_ns": pnr.get("hold_slack_ns"),
                "total_negative_slack_max_ns": pnr.get("total_negative_slack_max_ns"),
                "drc_violations": d.get("drc_violation_lines"),
                "streaming_power_64_mw": (power.get("streaming_window_64", {}) or {}).get("total_mw"),
                "streaming_power_128_mw": (power.get("streaming_window_128", {}) or {}).get("total_mw"),
            }
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            return {"passed": False, "error": f"result parse failed: {exc}"}
        if ppa.get("cell_area_um2") is None or ppa.get("timing_met") is None:
            return {"passed": False, "ppa": ppa,
                    "error": "physical result incomplete (missing area/timing)"}
    else:
        err_tail = "".join(ch for ch in (err[-600:] if err else "").replace("\n", " | ") if ch.isprintable())
        out_tail = "".join(ch for ch in (out[-600:] if out else "").replace("\n", " | ") if ch.isprintable())
        detail_msg = err_tail or out_tail or f"rc={rc}"
        return {"passed": False, "retry": rc != 0,
                "error": f"physical result JSON missing (rc={rc}): {detail_msg}",
                "returncode": rc, "summary": detail_msg}
    errors = []
    if d.get("schema") != "peweaver-physical-result-2":
        errors.append("unexpected physical result schema")
    flow_hashes = d.get("flow_input_hashes_sha256", {})
    if not isinstance(flow_hashes, dict):
        errors.append("physical result input hash map missing")
    elif flow_hashes.get("rtl/peweaver_shared_fft.v") != candidate_sha256:
        errors.append("physical result candidate hash mismatch")
    tail = "".join(ch for ch in (out[-900:]).replace("\n", " | ") if ch.isprintable())
    return {"passed": rc == 0 and bool(ppa) and not errors,
            "retry": False, "ppa": ppa, "errors": errors,
            "summary": tail, "returncode": rc,
            "candidate_sha256": candidate_sha256}


# ---------------------------------------------------------------------------
# Gate ladder adapters: sandbox -> deterministic judges (dispatched via Ray)
# ---------------------------------------------------------------------------


def make_gate_ladder(run_root: Path, timing_probe_command: list[str] | None = None,
                     evaluator_root: Path | None = None,
                     immutable_manifest: dict[str, str] | None = None):
    """Return the ordered evaluator ladder.

    Each takes the attempt sandbox path and returns a GateOutcome. They copy
    the candidate into the judge's source tree so the worker never touches
    evaluator files.  A timing probe is optional because its command must be
    supplied by the controller and pinned with the campaign configuration.
    """
    evaluator_root = evaluator_root or run_root
    source = evaluator_root / "source"
    immutable_root = evaluator_root / "immutable"
    rtl_dir = source / "physical" / "rtl"
    ppa_holder: dict = {}

    def reset_source() -> None:
        if immutable_manifest is None or workspace_manifest(immutable_root) != immutable_manifest:
            raise RuntimeError("immutable evaluator snapshot changed")
        _rmrf(source)
        shutil.copytree(immutable_root, source, symlinks=True)

    def copy_candidate(sandbox: Path) -> Path | None:
        cand = sandbox / CANDIDATE
        if not cand.is_file():
            return None
        reset_source()
        rtl_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cand, rtl_dir / CANDIDATE)
        return cand

    def g_lint(sandbox: Path) -> GateOutcome:
        cand = sandbox / CANDIDATE
        if not cand.is_file():
            return GateOutcome("lint", False,
                               note=f"{CANDIDATE} missing from the attempt")
        return dispatch(lint_gate, cand.read_text(), name="lint", note_len=300)

    def g_functional(sandbox: Path) -> GateOutcome:
        if copy_candidate(sandbox) is None:
            return GateOutcome("functional", False, note="candidate missing")
        return dispatch(functional_gate, str(evaluator_root), name="functional",
                        note_len=400)

    def g_timing_probe(sandbox: Path) -> GateOutcome:
        if copy_candidate(sandbox) is None:
            return GateOutcome("timing_probe", False, note="candidate missing")
        result = dispatch(
            timing_probe_node,
            timing_probe_command or [],
            str(source),
            OSS,
            name="timing_probe",
            note_len=600,
        )
        metrics = result.detail.get("metrics", {})
        return GateOutcome(
            "timing_probe",
            result.passed,
            note=(timing_feedback(metrics) if isinstance(metrics, dict)
                  else result.note),
            detail={"metrics": metrics, "probe": result.detail},
            retry=result.retry,
        )

    def g_physical(sandbox: Path) -> GateOutcome:
        cand = copy_candidate(sandbox)
        if cand is None:
            return GateOutcome("physical", False, note="candidate missing")
        stale = source / "physical" / "results" / "shared_baseline_sky130.json"
        stale.unlink(missing_ok=True)
        result = dispatch(
            physical_gate, str(evaluator_root), sha256_file(cand),
            name="physical", note_len=400)
        ppa_holder["ppa"] = result.detail.get("ppa") or {}
        result.detail["metrics"] = ppa_holder["ppa"]
        return result

    def g_portfolio(sandbox: Path) -> GateOutcome:
        ppa = ppa_holder.get("ppa") or {}
        area = ppa.get("cell_area_um2")
        if ppa.get("timing_met") is not True:
            return GateOutcome("portfolio", False, note="timing not met")
        if ppa.get("total_negative_slack_max_ns") != 0.0:
            return GateOutcome(
                "portfolio", False,
                note=("TNS is not zero: "
                      f"{ppa.get('total_negative_slack_max_ns')!r}"))
        drc = ppa.get("drc_violations")
        if drc != 0:
            return GateOutcome("portfolio", False, note=f"DRC violations: {drc}")
        try:
            area_f = float(area)
        except (TypeError, ValueError):
            return GateOutcome("portfolio", False, note=f"bad area: {area}")
        if not 0 < area_f < BASELINE_AREA_UM2:
            return GateOutcome(
                "portfolio", False,
                note=f"area {area_f} um^2 not below baseline {BASELINE_AREA_UM2}")
        reduction = round(100 * (1 - area_f / BASELINE_AREA_UM2), 2)
        return GateOutcome(
            "portfolio", True,
            note=f"area {area_f} um^2 = {reduction}% below the combined baseline",
            detail={"area_um2": area_f, "reduction_pct": reduction})

    gates = [g_lint, g_functional]
    if timing_probe_command is not None:
        gates.append(g_timing_probe)
    gates.extend([g_physical, g_portfolio])
    return gates


# ---------------------------------------------------------------------------
# Driver: thin CLI over ChiaMerge (primitives live in chia_merge.py)
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--turns", type=int, default=12)
    parser.add_argument("--planner-model", default="openrouter/openai/gpt-5.6-sol")
    parser.add_argument("--worker-model", default="gemini/gemini-3.8-flash")
    parser.add_argument("--advise-timeout", type=int, default=1500)
    parser.add_argument("--implement-timeout", type=int, default=1200)
    parser.add_argument("--mode", choices=(MODE_DISCOVERY, MODE_PARENT),
                        default=MODE_DISCOVERY,
                        help="clean-room discovery or explicit-parent optimization")
    parser.add_argument("--parent-candidate", type=Path,
                        help="accepted candidate file for ParentOptimization")
    parser.add_argument(
        "--timing-probe-command",
        help="fixed controller command, run in the evaluator source checkout; "
             "it must print JSON with boolean passed and optional metrics",
    )
    parser.add_argument("--resume", action="store_true",
                        help="continue the saved iterate state for this run id")
    args = parser.parse_args()

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", args.run_id):
        parser.error("--run-id must be a simple artifact name, not a path")

    if args.mode == MODE_PARENT and args.parent_candidate is None:
        parser.error("--parent-candidate is required for ParentOptimization")
    if args.mode == MODE_DISCOVERY and args.parent_candidate is not None:
        parser.error("--parent-candidate is only valid for ParentOptimization")

    run_root = RUNS_BASE / args.run_id
    evaluator_root = RUNS_BASE / ".evaluators" / args.run_id
    if not args.resume and run_root.exists() and any(run_root.iterdir()):
        print(json.dumps({"error": "run id already exists",
                          "path": str(run_root)}))
        return 2
    immutable_root = evaluator_root / "immutable"
    source = evaluator_root / "source"
    if args.resume:
        if not immutable_root.is_dir() or not source.is_dir():
            print(json.dumps({"error": "evaluator source missing on resume"}))
            return 2
    else:
        if evaluator_root.exists():
            print(json.dumps({"error": "evaluator run id already exists",
                              "path": str(evaluator_root)}))
            return 2
        print(f"[driver] copying deployed source tree -> {source}", flush=True)
        evaluator_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(DEPLOYED, immutable_root, symlinks=True)
        shutil.copytree(immutable_root, source, symlinks=True)
        immutable_manifest_file = evaluator_root / "immutable_manifest.json"
        immutable_manifest_file.write_text(
            json.dumps(workspace_manifest(immutable_root), indent=1,
                       sort_keys=True))
    immutable_manifest_file = evaluator_root / "immutable_manifest.json"
    try:
        immutable_manifest = json.loads(immutable_manifest_file.read_text())
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": f"immutable evaluator manifest invalid: {exc}"}))
        return 2
    if workspace_manifest(immutable_root) != immutable_manifest:
        print(json.dumps({"error": "immutable evaluator snapshot changed"}))
        return 2
    missing = [str(p) for p in INPUTS.values() if not p.is_file()]
    if missing:
        print(json.dumps({"error": "missing input designs", "missing": missing}))
        return 2

    timing_probe_command = (shlex.split(args.timing_probe_command)
                            if args.timing_probe_command else None)
    source_manifest = immutable_manifest
    gates = make_gate_ladder(run_root, timing_probe_command, evaluator_root,
                             immutable_manifest)
    input_hashes = {name: sha256_file(path) for name, path in INPUTS.items()}
    parent_hash = ""
    if args.parent_candidate is not None:
        parent_hash = sha256_file(args.parent_candidate)
    config_hash = config_fingerprint({
        "mode": args.mode,
        "inputs": input_hashes,
        "contract": CONTRACT,
        "candidate": CANDIDATE,
        "gates": ["lint", "functional"]
                 + (["timing_probe"] if timing_probe_command is not None else [])
                 + ["physical", "portfolio"],
        "timing_probe_command": timing_probe_command,
        "planner_model": args.planner_model,
        "worker_model": args.worker_model,
        "turns": args.turns,
        "advise_timeout": args.advise_timeout,
        "implement_timeout": args.implement_timeout,
        "evaluator_source_manifest": source_manifest,
        "forbidden_candidate_hashes": ([HISTORICAL_CANDIDATE_SHA256]
                                        if args.mode == MODE_DISCOVERY else []),
    })
    archive_holder: dict[str, SQLiteArchive] = {}

    def archive_start(run, state: IterationState) -> IterationState | None:
        archive = SQLiteArchive(run.artifacts / "lineage.sqlite3")
        archive_holder["archive"] = archive
        checkpoint = archive.start_run(
            run_id=args.run_id, mode=args.mode, parent_hash=parent_hash,
            config_hash=config_hash,
            metadata={"candidate": CANDIDATE, "inputs": input_hashes,
                      "evaluator_source_manifest": source_manifest},
            checkpoint=state.to_dict(), resume=args.resume)
        if args.resume and checkpoint != state.to_dict():
            return IterationState.from_dict(checkpoint)
        return None

    def archive_attempt(turn: int, workspace_hash: str, result: CheckResult,
                        state: IterationState, evidence_path: Path) -> None:
        archive = archive_holder["archive"]
        metrics: dict = {}
        for gate_name, gate in result.detail.items():
            if not isinstance(gate, dict):
                continue
            candidate_metrics = gate.get("metrics") or gate.get("ppa")
            if isinstance(candidate_metrics, dict):
                metrics[gate_name] = candidate_metrics
        evidence_path = evidence_path.resolve()
        artifacts_root = (run_root / "artifacts").resolve()
        try:
            evidence_path.relative_to(artifacts_root)
        except ValueError as exc:
            raise RuntimeError("attempt evidence escaped artifact directory") from exc
        if not evidence_path.is_file():
            raise RuntimeError(f"attempt evidence missing: {evidence_path}")
        model_status = state.model_status.get(str(turn), {})
        if turn == 0:
            candidate_sha256 = state.parent_hash
        else:
            manifest_path = run_root / "artifacts" / f"manifest_turn{turn}.json"
            manifest = json.loads(manifest_path.read_text())
            candidate_sha256 = manifest.get(CANDIDATE, "")
            if not candidate_sha256:
                raise RuntimeError("candidate hash missing from attempt manifest")
        archive.record_attempt(
            run_id=args.run_id,
            turn=turn,
            workspace_hash=workspace_hash,
            base_workspace_hash=model_status.get("base_workspace_hash", ""),
            candidate_sha256=candidate_sha256,
            verdict=result.verdict,
            level=result.level,
            status=model_status.get("transition_status", result.verdict.lower()),
            metrics=metrics,
            detail=result.detail,
            artifact_refs={"check": {
                "path": str(evidence_path.relative_to(run_root)),
                "sha256": sha256_file(evidence_path),
                "size": evidence_path.stat().st_size,
            }},
            checkpoint=state.to_dict(),
        )

    def archive_checkpoint(state: IterationState) -> None:
        archive_holder["archive"].update_checkpoint(args.run_id, state.to_dict())

    archive: SQLiteArchive | None = None
    try:
        state = ChiaMerge(
            run_id=args.run_id, run_base=RUNS_BASE, inputs=INPUTS,
            contract=CONTRACT, gates=gates, accept_level=len(gates),
            adviser_model=args.planner_model, implementer_model=args.worker_model,
            candidate_filename=CANDIDATE, turns=args.turns,
            advise_timeout=args.advise_timeout,
            implement_timeout=args.implement_timeout, resume=args.resume,
            mode=args.mode, parent_candidate=args.parent_candidate,
            config_hash=config_hash, on_start=archive_start,
            on_attempt=archive_attempt, on_checkpoint=archive_checkpoint,
            forbidden_candidate_hashes=(
                [HISTORICAL_CANDIDATE_SHA256]
                if args.mode == MODE_DISCOVERY else []))
        archive = archive_holder["archive"]
        final_status = ("accepted" if state.accepted else
                        "infra_blocked" if (state.pending_evaluation
                                             or state.model_infra_blocked) else
                        "exhausted")
        archive.finish_run(args.run_id, final_status)
    except Exception:
        archive = archive_holder.get("archive")
        if archive is not None:
            archive.finish_run(args.run_id, "failed")
        raise
    finally:
        archive = archive_holder.get("archive")
        if archive is not None:
            archive.close()

    print(json.dumps({"run_id": args.run_id, "accepted": state.accepted,
                      "infra_blocked": bool(state.pending_evaluation
                                             or state.model_infra_blocked),
                      "best_level": state.best_level,
                      "turns": [h.get("status") for h in state.history]}), flush=True)
    return 0 if state.accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
