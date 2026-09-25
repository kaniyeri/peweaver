#!/usr/bin/env python3
"""Bounded CHIA + direct-Gemini repair and physical-evaluation loop.

Gemini receives a CHIA BashTool and may edit the shared FFT candidate.  An
outer controller, not the model, owns the immutable regression and physical
judges.  Paid execution requires both --allow-gemini and
PEWEAVER_ALLOW_GEMINI_BILLABLE=1.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import signal
import stat
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any


PROPOSAL_GOAL = """Build an open-source pe-reuse CHIA loop that receives two
workload pipelines plus RTL/tests/interface/timing/power constraints, ranks
common computation, has an agent generate and repair a configurable shared PE
from compiler and physical-design feedback, and validates it with Verilator,
Yosys, OpenROAD/OpenSTA, connectivity/DRC, timing, and matched activity power.
For this experiment the shared 64/128 FFT PE must be bit-exact in both modes,
preserve the one-sample-per-cycle contract, and determine experimentally—not
assume—whether the placed area reduction reaches the 44% upper-bound target."""

SYSTEM = """You are the implementation agent inside the PEWeaver CHIA loop.
You have a Bash tool rooted at the CHIA source checkout. Use it actively:
inspect the reference RTL, architecture notes, candidate, and regression logs;
edit and rerun tests until the shared FFT is correct. You may use normal bash
editing/build tools. You must edit ONLY
examples/peweaver/physical/rtl/peweaver_shared_fft.v. The controller owns all
tests, vectors, wrappers, synthesis scripts, constraints, and physical-flow
files; never modify them. Never inspect /work/peweaver/secrets, environment
variables, credentials, cloud metadata, or unrelated user files. Do not claim
success from compilation alone. Preserve exact fixed-point behavior, 64/128
mode semantics, contiguous multi-frame streaming, and the existing interface.
When the immutable functional judge already passes but the physical objective
does not, optimize the RTL architecture instead of continuing diagnosis. In
particular, look for mode-specific state or delay storage that can safely use
one max-depth structure with exact mode-dependent addressing and control.
End with a compact summary of edits and tests actually run."""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def path_kind(path: Path) -> str:
    """Describe a path without following a model-created symlink or FIFO."""
    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError:
        return "missing"
    if stat.S_ISREG(mode):
        return "regular"
    if stat.S_ISLNK(mode):
        return "symlink"
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISFIFO(mode):
        return "fifo"
    return "other"


def restore_regular_file(path: Path, contents: bytes, mode: int, *,
                         quarantine_dir: Path) -> str | None:
    """Atomically restore one file without reading or following its old path.

    A directory cannot be replaced directly by a regular file, so quarantine
    it in the run record first.  Symlinks, FIFOs, missing paths, and regular
    files are all replaced by os.replace without following the old object.
    """
    quarantine: Path | None = None
    if path_kind(path) == "directory":
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        quarantine = quarantine_dir / f"{path.name}.invalid-{uuid.uuid4().hex[:8]}"
        os.replace(path, quarantine)

    temp = path.with_name(f".{path.name}.restore-{uuid.uuid4().hex}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(temp, flags, mode)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(contents)
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass
    return str(quarantine) if quarantine is not None else None


def changed_protected_files(repo: Path,
                            expected_hashes: dict[str, str]) -> list[str]:
    changed: list[str] = []
    for rel, expected in expected_hashes.items():
        path = repo / rel
        try:
            intact = (path_kind(path) == "regular" and sha256(path) == expected)
        except OSError:
            intact = False
        if not intact:
            changed.append(rel)
    return changed


def restore_protected_files(
        repo: Path, changed: list[str], snapshots: dict[str, tuple[bytes, int]],
        *, quarantine_dir: Path) -> tuple[list[str], list[str]]:
    restored: list[str] = []
    errors: list[str] = []
    for rel in changed:
        try:
            contents, mode = snapshots[rel]
            restore_regular_file(
                repo / rel, contents, mode, quarantine_dir=quarantine_dir)
            restored.append(rel)
        except Exception as exc:
            errors.append(f"{rel}: {type(exc).__name__}: {exc}")
    return restored, errors


def run_command(command: list[str], *, cwd: Path, timeout: int,
                env: dict[str, str] | None = None) -> dict[str, Any]:
    started = time.monotonic()
    try:
        proc = subprocess.Popen(
            command, cwd=cwd, env=env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True)
        stdout, stderr = proc.communicate(timeout=timeout)
        output = (stdout or "") + (stderr or "")
        return {"returncode": proc.returncode, "passed": proc.returncode == 0,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "output_tail": output[-20000:]}
    except subprocess.TimeoutExpired as exc:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        return {"returncode": None, "passed": False, "status": "timeout",
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "output_tail": f"timed out after {exc.timeout}s"}
    except Exception as exc:
        return {"returncode": None, "passed": False, "status": "tool_error",
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "output_tail": f"{type(exc).__name__}: {exc}"}


def protected_files(repo: Path) -> list[Path]:
    pe = repo / "examples" / "peweaver"
    paths = [
        pe / "orchestration" / "shared_fft_regression.py",
        pe / "physical" / "activity" / "shared_activity_tb.sv",
        pe / "physical" / "rtl" / "peweaver_ppa_shared_fft.v",
        pe / "physical" / "run-physical.sh",
        pe / "physical" / "assemble_results.py",
        pe / "physical" / "synth" / "shared_synth.ys",
        pe / "physical" / "synth" / "sky130_simple_map.v",
        pe / "physical" / "synth" / "filter_liberty.py",
        pe / "physical" / "constraints" / "shared_baseline.sdc",
        pe / "physical" / "openroad" / "fft64_frontend.tcl",
        pe / "physical" / "openroad" / "fft64_backend.tcl",
        pe / "physical" / "tool-lock.json",
        pe / "physical" / "vcd_normalize.py",
        pe / "SHARED_FFT_ARCHITECTURE.md",
        Path(__file__).resolve(),
    ]
    paths.extend(sorted((pe / "physical" / "pdk" / "sky130hd").glob("*")))
    for fixture in ("halo_fft64_reference", "halo_fft128_reference"):
        root = pe / "benchmarks" / fixture
        paths.extend(sorted((root / "vectors").glob("*.txt")))
        paths.append(root / "manifest.json")
        paths.extend(sorted(root.glob("*.v")))
    reference = pe / "third_party" / "r22sdf"
    for name in ("FFT64.v", "FFT128.v", "SdfUnit.v", "SdfUnit2.v",
                 "Butterfly.v", "DelayBuffer.v", "Multiply.v",
                 "Twiddle64.v", "Twiddle128.v"):
        paths.append(reference / name)
    # Enforce the prompt's "edit only the candidate" boundary across the whole
    # experiment source tree, not merely the files currently used by the judge.
    # Generated physical results and Python caches are deliberately excluded.
    candidate = pe / "physical" / "rtl" / "peweaver_shared_fft.v"
    for path in pe.rglob("*"):
        if not path.is_file() or path.is_symlink() or path == candidate:
            continue
        rel_parts = path.relative_to(pe).parts
        if "__pycache__" in rel_parts:
            continue
        if rel_parts[:2] in {("physical", "results"),
                             ("orchestration", "runs")}:
            continue
        paths.append(path)
    paths.extend([
        repo / "chia" / "models" / "vertex.py",
        repo / "chia" / "base" / "tools" / "BashTool.py",
    ])
    return sorted(set(paths))


def candidate_is_regular(candidate: Path, expected: Path) -> bool:
    return (path_kind(candidate) == "regular"
            and os.path.abspath(candidate) == os.path.abspath(expected))


def write_json(path: Path, value: object) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def candidate_diff(before: str, after: str) -> str:
    return "".join(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile="peweaver_shared_fft.before.v",
        tofile="peweaver_shared_fft.after.v"))


def write_candidate_artifacts(run_dir: Path, candidate: Path, original: str) -> None:
    final = candidate.read_text(encoding="utf-8")
    (run_dir / "candidate.after.v").write_text(final, encoding="utf-8")
    (run_dir / "candidate.diff").write_text(
        candidate_diff(original, final), encoding="utf-8")


def evaluate_objective(result: dict[str, Any], *, target_area_reduction_pct: float,
                       max_mode64_power_mw: float,
                       max_mode128_power_mw: float) -> dict[str, Any]:
    values = result["results"]
    area_reduction = float(
        values["area_comparison"]["placed_reduction_vs_standalone_sum_pct"])
    mode64_power = float(values["power_mw"]["streaming_window_64"]["total_mw"])
    mode128_power = float(values["power_mw"]["streaming_window_128"]["total_mw"])
    timing_met = bool(values["pnr"]["timing_met"])
    drc_clean = int(result["drc_violation_lines"]) == 0
    checks = {
        "area_target_met": area_reduction >= target_area_reduction_pct,
        "mode64_power_target_met": mode64_power <= max_mode64_power_mw,
        "mode128_power_target_met": mode128_power <= max_mode128_power_mw,
        "timing_met": timing_met,
        "drc_clean": drc_clean,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "measured": {
            "placed_area_reduction_pct": area_reduction,
            "mode64_streaming_power_mw": mode64_power,
            "mode128_streaming_power_mw": mode128_power,
        },
        "targets": {
            "minimum_placed_area_reduction_pct": target_area_reduction_pct,
            "maximum_mode64_streaming_power_mw": max_mode64_power_mw,
            "maximum_mode128_streaming_power_mw": max_mode128_power_mw,
        },
    }


def objective_feedback(objective: dict[str, Any]) -> str:
    measured = objective["measured"]
    targets = objective["targets"]
    if measured["placed_area_reduction_pct"] >= 20.0:
        next_step = (
            "The six delay-bank pairs are already compacted; do not redesign "
            "them or alter counters/control. Make only the low-risk 64-mode "
            "stage-3 operand change: in the existing clocked s3 twiddle-ROM "
            "block, assign s3_tw_re and s3_tw_im to zero when effective_mode "
            "is false, and execute the existing twiddle case unchanged when "
            "effective_mode is true. Stage 3 is bypassed in 64 mode, so this "
            "must not alter functional output or latency. Do not gate the "
            "clock and do not change any other block."
        )
    else:
        next_step = (
            "The current functionally passing RTL contains separate mode-0 "
            "and mode-1 delay arrays. For the first optimization, keep "
            "counters, arithmetic, ROM contents, and pipeline boundaries "
            "unchanged; merge only the six paired delay banks "
            "s1_db1_{0,1}, s1_db2_{0,1}, s2_db1_{0,1}, s2_db2_{0,1}, "
            "s3_db1_{0,1}, and s3_db2_{0,1} into one max-depth array per "
            "pair. In 128 mode shift the full range; in 64 mode shift only "
            "the lower range and hold upper entries. Preserve the existing "
            "mode-selected taps (63/31, 31/15, 15/7, 7/3, 3/1, and 1/0), "
            "exact latency, and continuous-frame behavior. Do not add derived "
            "clocks or x-valued defaults."
        )
    return (
        "Functional regression and the fail-closed physical flow passed, but "
        "the optimization objective was missed. "
        f"Placed-area reduction is {measured['placed_area_reduction_pct']:.3f}% "
        f"(target >= {targets['minimum_placed_area_reduction_pct']:.3f}%). "
        f"Mode-64 streaming power is {measured['mode64_streaming_power_mw']:.4f} mW "
        f"(target <= {targets['maximum_mode64_streaming_power_mw']:.4f} mW). "
        f"Mode-128 streaming power is {measured['mode128_streaming_power_mw']:.4f} mW "
        f"(target <= {targets['maximum_mode128_streaming_power_mw']:.4f} mW). "
        "Timing and zero-DRC closure remain mandatory. " + next_step
    )


def validate_physical_result(result: dict[str, Any], candidate: Path) -> list[str]:
    errors: list[str] = []
    try:
        if result["schema"] != "peweaver-physical-result-2":
            errors.append("unexpected result schema")
        if result["design"]["top"] != "peweaver_ppa_shared_fft":
            errors.append("unexpected physical top module")
        recorded = result["design"]["reference_source_hashes_sha256"][
            "rtl/peweaver_shared_fft.v"]
        if recorded != sha256(candidate):
            errors.append("physical result candidate hash mismatch")
        pnr = result["results"]["pnr"]
        if not pnr["timing_met"] or float(pnr["setup_slack_ns"]) <= 0.0:
            errors.append("setup timing is not clean")
        if float(pnr["hold_slack_ns"]) <= 0.0:
            errors.append("hold timing is not clean")
        if int(result["drc_violation_lines"]) != 0:
            errors.append("DRC is not clean")
        power = result["results"]["power_mw"]
        for mode in ("streaming_window_64", "streaming_window_128"):
            if float(power[mode]["total_mw"]) <= 0.0:
                errors.append(f"non-positive {mode} power")
        activity = result["activity"]
        if int(activity["annotated_pins_streaming"]) <= 0:
            errors.append("missing streaming activity annotation")
        if int(activity["annotated_pins_streaming_128"]) <= 0:
            errors.append("missing 128-mode activity annotation")
    except (KeyError, TypeError, ValueError) as exc:
        errors.append(f"malformed physical result: {exc}")
    return errors


def build_prompt(iteration: int, feedback: str) -> str:
    return f"""{PROPOSAL_GOAL}

This is repair iteration {iteration}. The candidate already exists at
examples/peweaver/physical/rtl/peweaver_shared_fft.v. Read
examples/peweaver/SHARED_FFT_ARCHITECTURE.md for the exact cycle/arithmetic
contract, then inspect the candidate and the pinned FFT64/FFT128 references.

If the evidence below says the functional regression already passes, this is
an optimization turn, not a correctness investigation. Do not broadly reread
the references or re-derive the architecture. Implement only the exact,
single-block optimization target stated in the feedback, run the immutable
regression, and finish the turn.

The outer judge's latest evidence follows. Treat a missing/unknown result as a
failure. Use the Bash tool to diagnose, edit the candidate, and run
`python examples/peweaver/orchestration/shared_fft_regression.py --json` as
often as useful. Do not edit the judge.
Do not run the physical flow yourself; the outer controller owns that expensive
step. Never edit even temporarily any evaluator, vector, wrapper, synthesis,
mapping, constraint, PDK, orchestration, or physical-flow file.

--- latest judge/physical feedback ---
{feedback[-16000:]}
--- end feedback ---

Work autonomously now. Functional correctness is mandatory; area is measured
only after it passes. Do not weaken tests or constraints."""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-gemini", action="store_true")
    parser.add_argument("--model", default=os.environ.get("GEMINI_MODEL", "gemini-3.1-pro-preview"))
    parser.add_argument("--max-repairs", type=int, default=3)
    parser.add_argument("--max-tool-iterations", type=int, default=24)
    parser.add_argument("--max-model-tokens", type=int, default=12000)
    parser.add_argument("--model-retries", type=int, default=1)
    parser.add_argument(
        "--thinking-level", choices=("minimal", "low", "medium", "high"),
        default="low")
    parser.add_argument("--target-area-reduction-pct", type=float, default=44.0)
    parser.add_argument("--max-mode64-power-mw", type=float, default=23.314)
    parser.add_argument("--max-mode128-power-mw", type=float, default=41.040)
    parser.add_argument("--model-timeout", type=int, default=1800)
    parser.add_argument("--physical-timeout", type=int, default=10800)
    parser.add_argument("--skip-physical", action="store_true")
    parser.add_argument(
        "--reuse-initial-physical-result", action="store_true",
        help=("validate and reuse physical/results/shared_baseline_sky130.json "
              "for the unchanged initial candidate; every new passing candidate "
              "still runs the full physical flow"))
    parser.add_argument("--run-dir", type=Path)
    args = parser.parse_args(argv)

    if not 1 <= args.max_repairs <= 5:
        print("peweaver_gemini_loop: --max-repairs must be in [1, 5]", file=sys.stderr)
        return 2
    if not 1 <= args.max_tool_iterations <= 40:
        print("peweaver_gemini_loop: --max-tool-iterations must be in [1, 40]",
              file=sys.stderr)
        return 2
    if not 1024 <= args.max_model_tokens <= 24000:
        print("peweaver_gemini_loop: --max-model-tokens must be in [1024, 24000]",
              file=sys.stderr)
        return 2
    if not 1 <= args.model_retries <= 2:
        print("peweaver_gemini_loop: --model-retries must be in [1, 2]",
              file=sys.stderr)
        return 2
    if not 0.0 <= args.target_area_reduction_pct < 100.0:
        print("peweaver_gemini_loop: area target must be in [0, 100)", file=sys.stderr)
        return 2
    if args.max_mode64_power_mw <= 0.0 or args.max_mode128_power_mw <= 0.0:
        print("peweaver_gemini_loop: power targets must be positive", file=sys.stderr)
        return 2

    repo = Path(__file__).resolve().parents[3]
    pe = repo / "examples" / "peweaver"
    physical = pe / "physical"
    candidate = physical / "rtl" / "peweaver_shared_fft.v"
    if not candidate_is_regular(candidate, physical / "rtl" / "peweaver_shared_fft.v"):
        print("peweaver_gemini_loop: candidate must be the expected regular file",
              file=sys.stderr)
        return 2
    run_root = Path(os.environ.get("PEWEAVER_RUN_MANIFEST_DIR", pe / "orchestration" / "runs"))
    run_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-gemini-" + uuid.uuid4().hex[:8]
    run_dir = (args.run_dir or run_root / run_id).resolve()
    run_dir.mkdir(parents=True, exist_ok=False)

    original_bytes = candidate.read_bytes()
    original = original_bytes.decode("utf-8")
    candidate_mode = stat.S_IMODE(os.stat(candidate, follow_symlinks=False).st_mode)
    best_functional_candidate: str | None = None
    (run_dir / "candidate.before.v").write_text(original, encoding="utf-8")
    protected_snapshots: dict[str, tuple[bytes, int]] = {}
    for path in protected_files(repo):
        rel = str(path.relative_to(repo))
        protected_snapshots[rel] = (
            path.read_bytes(),
            stat.S_IMODE(os.stat(path, follow_symlinks=False).st_mode),
        )
    protected = {
        rel: hashlib.sha256(contents).hexdigest()
        for rel, (contents, _mode) in protected_snapshots.items()
    }
    manifest: dict[str, Any] = {
        "schema": "peweaver-gemini-loop-1", "run_id": run_id,
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model": args.model, "goal": PROPOSAL_GOAL,
        "authorization": "no billable model call made",
        "credential_recorded": False, "max_repairs": args.max_repairs,
        "max_tool_iterations": args.max_tool_iterations,
        "max_model_tokens": args.max_model_tokens,
        "model_retries": args.model_retries,
        "thinking_level": args.thinking_level,
        "targets": {
            "minimum_placed_area_reduction_pct": args.target_area_reduction_pct,
            "maximum_mode64_streaming_power_mw": args.max_mode64_power_mw,
            "maximum_mode128_streaming_power_mw": args.max_mode128_power_mw,
        },
        "status": "running", "iterations": [],
        "baseline": {
            "fft64_placed_um2": 164408.0, "fft128_placed_um2": 260477.0,
            "standalone_placed_sum_um2": 424885.0,
            "target_reduction_pct_upper_bound": 44.0,
            "standalone_synthesis_sum_um2": 360122.8864,
        },
    }
    manifest_path = run_dir / "manifest.json"
    write_json(manifest_path, manifest)

    # The initial failure is useful model evidence, but a timeout/tool error is
    # not: hard-stop before spending tokens when the judge itself is broken.
    base_env = os.environ.copy()
    base_env.pop("GEMINI_API_KEY", None)
    regression_cmd = [sys.executable, str(pe / "orchestration" / "shared_fft_regression.py"), "--json"]
    initial = run_command(regression_cmd, cwd=repo, timeout=240, env=base_env)
    (run_dir / "initial_regression.log").write_text(initial["output_tail"] + "\n", encoding="utf-8")
    manifest["initial_regression"] = initial
    if initial.get("status") in {"timeout", "tool_error"} or initial["returncode"] not in (0, 1):
        manifest.update(status="blocked", error="initial immutable judge tool failure",
                        initial_regression=initial)
        write_json(manifest_path, manifest)
        write_candidate_artifacts(run_dir, candidate, original)
        print(manifest_path)
        return 2

    feedback = initial["output_tail"]
    if initial.get("passed"):
        best_functional_candidate = original
        record: dict[str, Any] = {
            "iteration": 0,
            "source": "initial_candidate",
            "regression": initial,
        }
        if args.skip_physical:
            record["status"] = "functional_pass_physical_skipped"
            manifest["iterations"].append(record)
            manifest.update(status="functional_pass_physical_skipped",
                            completed_iteration=0)
            write_json(manifest_path, manifest)
            write_candidate_artifacts(run_dir, candidate, original)
            print(manifest_path)
            return 0

        result_path = physical / "results" / "shared_baseline_sky130.json"
        if args.reuse_initial_physical_result:
            physical_result = {
                "returncode": 0, "passed": True,
                "status": "reused_prevalidated_result",
                "elapsed_seconds": 0.0,
                "output_tail": str(result_path),
            }
        else:
            physical_env = base_env.copy()
            physical_env["PEWEAVER_DESIGN"] = "shared"
            physical_result = run_command(
                [str(physical / "run-physical.sh")], cwd=physical,
                timeout=args.physical_timeout, env=physical_env)
        record["physical"] = physical_result
        (run_dir / "initial_physical.log").write_text(
            physical_result["output_tail"] + "\n", encoding="utf-8")
        if physical_result.get("passed"):
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                record["status"] = "invalid_physical_result"
                manifest["iterations"].append(record)
                manifest.update(status="blocked",
                                error=f"cannot load physical result: {exc}")
                write_json(manifest_path, manifest)
                write_candidate_artifacts(run_dir, candidate, original)
                print(manifest_path)
                return 2
            result_errors = validate_physical_result(result, candidate)
            record["physical_result_validation_errors"] = result_errors
            if result_errors:
                record["status"] = "invalid_physical_result"
                manifest["iterations"].append(record)
                manifest.update(status="blocked", error="; ".join(result_errors))
                write_json(manifest_path, manifest)
                write_candidate_artifacts(run_dir, candidate, original)
                print(manifest_path)
                return 2
            objective = evaluate_objective(
                result,
                target_area_reduction_pct=args.target_area_reduction_pct,
                max_mode64_power_mw=args.max_mode64_power_mw,
                max_mode128_power_mw=args.max_mode128_power_mw)
            record.update(physical_result=result, objective=objective)
            if objective["passed"]:
                record["status"] = "passed"
                manifest["iterations"].append(record)
                manifest.update(status="passed", completed_iteration=0,
                                result_record=str(result_path))
                write_json(manifest_path, manifest)
                write_candidate_artifacts(run_dir, candidate, original)
                print(manifest_path)
                return 0
            record["status"] = "objective_missed"
            manifest["iterations"].append(record)
            write_json(manifest_path, manifest)
            feedback = objective_feedback(objective)
        else:
            record["status"] = "physical_failed"
            manifest["iterations"].append(record)
            write_json(manifest_path, manifest)
            feedback = ("Functional regression passed, but physical evaluation failed:\n"
                        + physical_result["output_tail"])

    if not args.allow_gemini or os.environ.get("PEWEAVER_ALLOW_GEMINI_BILLABLE") != "1":
        manifest.update(status="model_authorization_required",
                        error="two-gate Gemini authorization required for repair")
        write_json(manifest_path, manifest)
        write_candidate_artifacts(run_dir, candidate, original)
        print(manifest_path)
        return 2
    if not os.environ.get("GEMINI_API_KEY", "").strip():
        manifest.update(status="blocked", error="GEMINI_API_KEY is unset")
        write_json(manifest_path, manifest)
        write_candidate_artifacts(run_dir, candidate, original)
        print(manifest_path)
        return 2
    manifest["authorization"] = "explicit two-gate direct Gemini Developer API"
    write_json(manifest_path, manifest)

    ray = None
    ray_started = False
    bash_tool = None
    seen_candidate_hashes = {sha256(candidate)}
    try:
        import ray
        from chia.base.tools.BashTool import BashTool
        from chia.models.vertex import DirectGeminiLLM

        if not ray.is_initialized():
            ray.init(address=os.environ.get("RAY_ADDRESS", "auto"), ignore_reinit_error=True)
            ray_started = True
        bash_tool = BashTool(
            name=f"peweaver_bash_{uuid.uuid4().hex[:8]}",
            work_dir=str(repo), timeout_seconds=600,
            task_options={"num_cpus": 0.25},
        )
        llm = DirectGeminiLLM(
            model=args.model, system_message=SYSTEM,
            timeout_seconds=args.model_timeout, retries=args.model_retries,
            max_tokens=args.max_model_tokens,
            max_tool_iterations=args.max_tool_iterations,
            thinking_level=args.thinking_level,
            log_dir=str(run_dir / "model_logs"),
        )

        for iteration in range(1, args.max_repairs + 1):
            print(f"PEWEAVER_GEMINI_ITERATION {iteration}/{args.max_repairs}", flush=True)
            response = llm.prompt(build_prompt(iteration, feedback), tools=[bash_tool])
            (run_dir / f"iteration_{iteration}_model.txt").write_text(
                response.stream_result or response.result or response.stderr or "",
                encoding="utf-8")

            changed_protected = changed_protected_files(repo, protected)
            record: dict[str, Any] = {
                "iteration": iteration, "model_success": bool(response.success),
                "protected_files_changed": changed_protected,
                "model_metadata": dict(getattr(llm, "_last_metadata", {}) or {}),
            }
            if not response.success:
                record["status"] = "model_failed"
                manifest["iterations"].append(record)
                manifest.update(status="blocked", error="Gemini model call failed")
                write_json(manifest_path, manifest)
                break
            if changed_protected:
                record["status"] = "judge_tampering_detected"
                restored, restore_errors = restore_protected_files(
                    repo, changed_protected, protected_snapshots,
                    quarantine_dir=run_dir / "quarantined_protected_paths")
                record["protected_files_restored"] = restored
                record["protected_restore_errors"] = restore_errors
                manifest["iterations"].append(record)
                error = "model modified protected evaluator inputs"
                if restore_errors:
                    error += "; protected-file restoration incomplete"
                manifest.update(status="blocked", error=error)
                write_json(manifest_path, manifest)
                break
            if not candidate_is_regular(
                    candidate, physical / "rtl" / "peweaver_shared_fft.v"):
                record["status"] = "invalid_candidate_file"
                record["attempted_candidate_kind"] = path_kind(candidate)
                try:
                    quarantine = restore_regular_file(
                        candidate, (best_functional_candidate or original).encode("utf-8"),
                        candidate_mode,
                        quarantine_dir=run_dir / "quarantined_candidate_paths")
                    record["candidate_restored"] = True
                    if quarantine is not None:
                        record["candidate_quarantine_path"] = quarantine
                except Exception as exc:
                    record["candidate_restore_error"] = (
                        f"{type(exc).__name__}: {exc}")
                manifest["iterations"].append(record)
                manifest.update(status="blocked",
                                error="candidate was replaced by a non-regular file")
                write_json(manifest_path, manifest)
                break

            candidate_hash = sha256(candidate)
            record["candidate_sha256"] = candidate_hash
            if candidate_hash in seen_candidate_hashes:
                record["status"] = "duplicate_or_unchanged_candidate"
                manifest["iterations"].append(record)
                feedback = ("The previous model turn produced no new candidate. "
                            "Make one focused structural-sharing change, then run "
                            "the immutable functional judge before responding.")
                write_json(manifest_path, manifest)
                continue
            seen_candidate_hashes.add(candidate_hash)

            regression = run_command(regression_cmd, cwd=repo, timeout=240, env=base_env)
            record["regression"] = regression
            (run_dir / f"iteration_{iteration}_regression.log").write_text(
                regression["output_tail"] + "\n", encoding="utf-8")
            current = candidate.read_text(encoding="utf-8")
            (run_dir / f"iteration_{iteration}.diff").write_text(
                candidate_diff(original, current), encoding="utf-8")

            if (regression.get("status") in {"timeout", "tool_error"}
                    or regression["returncode"] not in (0, 1)):
                record["status"] = "judge_tool_failure"
                manifest["iterations"].append(record)
                manifest.update(status="blocked",
                                error="immutable judge timeout/tool failure")
                write_json(manifest_path, manifest)
                break

            if regression.get("passed"):
                best_functional_candidate = current

            if regression.get("passed") and not args.skip_physical:
                physical_env = base_env.copy()
                physical_env["PEWEAVER_DESIGN"] = "shared"
                physical_result = run_command(
                    [str(physical / "run-physical.sh")], cwd=physical,
                    timeout=args.physical_timeout, env=physical_env)
                record["physical"] = physical_result
                (run_dir / f"iteration_{iteration}_physical.log").write_text(
                    physical_result["output_tail"] + "\n", encoding="utf-8")
                if physical_result.get("status") in {"timeout", "tool_error"}:
                    record["status"] = "physical_tool_failure"
                    manifest["iterations"].append(record)
                    manifest.update(status="blocked",
                                    error="physical evaluator timeout/tool failure")
                    write_json(manifest_path, manifest)
                    break
                if physical_result.get("passed"):
                    result_path = physical / "results" / "shared_baseline_sky130.json"
                    result = json.loads(result_path.read_text(encoding="utf-8"))
                    result_errors = validate_physical_result(result, candidate)
                    record["physical_result_validation_errors"] = result_errors
                    if result_errors:
                        record["status"] = "invalid_physical_result"
                        manifest["iterations"].append(record)
                        manifest.update(status="blocked",
                                        error="; ".join(result_errors))
                        write_json(manifest_path, manifest)
                        break
                    objective = evaluate_objective(
                        result,
                        target_area_reduction_pct=args.target_area_reduction_pct,
                        max_mode64_power_mw=args.max_mode64_power_mw,
                        max_mode128_power_mw=args.max_mode128_power_mw)
                    record.update(physical_result=result, objective=objective)
                    if objective["passed"]:
                        record["status"] = "passed"
                        manifest["iterations"].append(record)
                        manifest.update(status="passed", completed_iteration=iteration,
                                        result_record=str(result_path))
                        write_json(manifest_path, manifest)
                        break
                    feedback = objective_feedback(objective)
                    record["status"] = "objective_missed"
                else:
                    feedback = ("Functional regression passed, but physical "
                                "evaluation failed:\n" + physical_result["output_tail"])
                    record["status"] = "physical_failed"
            elif regression.get("passed"):
                record["status"] = "functional_pass_physical_skipped"
                manifest["iterations"].append(record)
                manifest.update(status="functional_pass_physical_skipped",
                                completed_iteration=iteration)
                write_json(manifest_path, manifest)
                break
            else:
                feedback = regression["output_tail"]
                record["status"] = "functional_failed"
                (run_dir / f"iteration_{iteration}.attempted.v").write_text(
                    current, encoding="utf-8")
                if best_functional_candidate is not None:
                    try:
                        restore_regular_file(
                            candidate, best_functional_candidate.encode("utf-8"),
                            candidate_mode,
                            quarantine_dir=run_dir / "quarantined_candidate_paths")
                        record["candidate_restored_after_regression_failure"] = True
                        record["restored_candidate_sha256"] = sha256(candidate)
                    except Exception as exc:
                        record["candidate_restore_error"] = (
                            f"{type(exc).__name__}: {exc}")
                        manifest["iterations"].append(record)
                        manifest.update(
                            status="blocked",
                            error="failed to restore last passing candidate")
                        write_json(manifest_path, manifest)
                        break

            manifest["iterations"].append(record)
            write_json(manifest_path, manifest)
        else:
            manifest.update(status="exhausted", error="repair budget exhausted")
            write_json(manifest_path, manifest)
    except KeyboardInterrupt:
        manifest.update(status="interrupted",
                        error="controller interrupted during model/evaluator work")
        write_json(manifest_path, manifest)
    except Exception as exc:
        manifest.update(status="blocked", error=f"{type(exc).__name__}: {exc}")
        write_json(manifest_path, manifest)
    finally:
        os.environ.pop("GEMINI_API_KEY", None)
        finalization_errors: list[str] = []
        integrity_finalization_failed = False

        try:
            changed = changed_protected_files(repo, protected)
            if changed:
                restored, restore_errors = restore_protected_files(
                    repo, changed, protected_snapshots,
                    quarantine_dir=run_dir / "quarantined_protected_paths")
                manifest["protected_files_restored_at_finalization"] = restored
                if restore_errors:
                    finalization_errors.extend(restore_errors)
                    integrity_finalization_failed = True
        except Exception as exc:
            finalization_errors.append(
                f"protected finalization: {type(exc).__name__}: {exc}")
            integrity_finalization_failed = True

        try:
            restore_text = best_functional_candidate or original
            restore_bytes = restore_text.encode("utf-8")
            attempted_kind = path_kind(candidate)
            restore_needed = attempted_kind != "regular"
            if attempted_kind == "regular":
                attempted_bytes = candidate.read_bytes()
                restore_needed = attempted_bytes != restore_bytes
                if restore_needed:
                    (run_dir / "candidate.attempted_final.v").write_bytes(
                        attempted_bytes)
            else:
                manifest["attempted_final_candidate_kind"] = attempted_kind

            if restore_needed:
                quarantine = restore_regular_file(
                    candidate, restore_bytes, candidate_mode,
                    quarantine_dir=run_dir / "quarantined_candidate_paths")
                manifest["candidate_restored_after_failure"] = True
                manifest["restored_candidate_sha256"] = sha256(candidate)
                if quarantine is not None:
                    manifest["candidate_quarantine_path"] = quarantine

            if not candidate_is_regular(
                    candidate, physical / "rtl" / "peweaver_shared_fft.v"):
                raise RuntimeError("candidate restoration did not produce expected file")
            write_candidate_artifacts(run_dir, candidate, original)
        except Exception as exc:
            finalization_errors.append(
                f"candidate finalization: {type(exc).__name__}: {exc}")
            integrity_finalization_failed = True

        if bash_tool is not None:
            try:
                bash_tool.stop()
            except Exception as exc:
                finalization_errors.append(
                    f"BashTool cleanup: {type(exc).__name__}: {exc}")
        if ray_started and ray is not None:
            try:
                ray.shutdown()
            except Exception as exc:
                finalization_errors.append(
                    f"Ray cleanup: {type(exc).__name__}: {exc}")

        if finalization_errors:
            manifest["finalization_errors"] = finalization_errors
            if integrity_finalization_failed:
                manifest.update(status="blocked",
                                error="controller finalization was incomplete")
        write_json(manifest_path, manifest)

    print(manifest_path)
    return 0 if manifest["status"] in {"passed", "functional_pass_physical_skipped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
