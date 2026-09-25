#!/usr/bin/env python3
"""Bounded, model-to-candidate PEWeaver loop using native CHIA primitives.

This controller deliberately does not import ``ChiaMerge``.  A turn is:

    reference inputs -> OpenCodeLLM.prompt -> fresh candidate sandbox
        -> CHIA lint/functional/physical nodes -> deterministic disposition

The historical shared FFT is comparison evidence only.  It is never supplied
to the model, copied into the candidate sandbox, or counted as a generated
candidate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
PEWEAVER = HERE.parent
DEFAULT_EVALUATOR_ROOT = Path(
    os.environ.get("PEWEAVER_EVALUATOR_ROOT", str(PEWEAVER))
)
DEFAULT_RUN_BASE = Path(os.environ.get("PEWEAVER_RUNS", "/work/peweaver/runs"))
DEFAULT_OSS = os.environ.get(
    "PEWEAVER_OSS_BIN", "/work/peweaver/toolchains/oss-cad-suite/bin"
)
DEFAULT_OPENROAD = os.environ.get(
    "PEWEAVER_OPENROAD_BIN", "/work/peweaver/toolchains/openroad/bin"
)
DEFAULT_PDK = os.environ.get("PEWEAVER_PDK_ROOT", "/work/peweaver/toolchains/.volare")
DEFAULT_VOLARE = os.environ.get(
    "PEWEAVER_VOLARE_VENV", "/work/peweaver/toolchains/physical-venv"
)
DEFAULT_PYTHON = os.environ.get("PEWEAVER_PYTHON", sys.executable)

CANDIDATE_NAME = "peweaver_shared_fft.v"
TOP = "peweaver_shared_fft"
STANDALONE_AREA_SUM_UM2 = 424885.0
HISTORICAL_CANDIDATE_HASHES = {
    "ce64c71552f0aa1750ae62c15a081d16d52e92396d9d67243088aeec4723e92e":
        "accepted historical shared candidate",
    "6a56b8326993d091cd989fc45a68ac341e5a25a33aaace47e81fa42a1ab78499":
        "historical fallback shared candidate",
}
PORTS = [
    "clock", "reset", "mode", "di_en", "di_re", "di_im",
    "do_en", "do_re", "do_im",
]
REFERENCE_FILES = (
    "third_party/r22sdf/FFT64.v",
    "third_party/r22sdf/FFT128.v",
    "third_party/r22sdf/SdfUnit.v",
    "third_party/r22sdf/SdfUnit2.v",
    "third_party/r22sdf/Multiply.v",
    "third_party/r22sdf/Butterfly.v",
    "third_party/r22sdf/DelayBuffer.v",
    "third_party/r22sdf/Twiddle64.v",
    "third_party/r22sdf/Twiddle128.v",
)
CONTRACT = """Create one complete synthesizable Verilog file containing module
peweaver_shared_fft with exactly these ports: clock, reset, mode, di_en,
di_re[15:0], di_im[15:0], do_en, do_re[15:0], do_im[15:0]. reset is active
high. mode 0 is a 64-point FFT and mode 1 is a 128-point FFT. Each frame is
N consecutive input samples in natural order. The first do_en edge is exactly
71 cycles after sample 0 in mode 64 and exactly 137 cycles after sample 0 in
mode 128. Outputs are valid for exactly N consecutive cycles, with sustained
same-mode streaming and no output from an abandoned frame after reset. The
arithmetic and fixed-point behavior must be bit-exact to the supplied FFT64
and FFT128 references, including their scaling, twiddles, rounding, and
bit-reversed output order. No external ports, file I/O, delays, initial/final
blocks, testbench code, DPI, or PLI. The candidate must be synthesizable by
the frozen Yosys flow. All helper modules must be at file scope, never nested
inside another module. Do not use initial blocks for ROM/table contents;
implement constant tables with synthesizable case logic or continuous
assignments. Before responding, check that every module is balanced with
endmodule, that there are no placeholders or testbench constructs, and that
the candidate is a complete file rather than a truncated excerpt."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def extract_verilog(text: str) -> str:
    blocks = re.findall(r"```(?:verilog|systemverilog|sv)?\s*\n(.*?)```", text, re.S | re.I)
    if blocks:
        return max(blocks, key=len).strip() + "\n"
    stripped = text.strip()
    return stripped + "\n" if stripped.startswith(("module", "`timescale")) else ""


def copy_fresh_source(source_root: Path, attempt_root: Path) -> Path:
    if attempt_root.exists():
        raise FileExistsError(f"attempt already exists: {attempt_root}")
    destination = attempt_root / "source"
    attempt_root.mkdir(parents=True)

    def ignore(path: str, names: list[str]) -> set[str]:
        relative = Path(path).relative_to(source_root)
        excluded = {name for name in names if name in {".git", "__pycache__", ".pytest_cache"}}
        if relative == Path("physical"):
            # The evaluator snapshot may contain large archived results.* trees.
            # They are not inputs to a fresh attempt; the leakage fixture below
            # is copied separately after all result directories are excluded.
            excluded.update(
                name for name in names if name == "results" or name.startswith("results.")
            )
        if relative == Path("orchestration") and "runs" in names:
            excluded.add("runs")
        return excluded

    shutil.copytree(source_root, destination, symlinks=True, ignore=ignore)
    leakage = source_root / "physical" / "results" / "leakage_check"
    if leakage.is_dir():
        shutil.copytree(leakage, destination / "physical" / "results" / "leakage_check")
    return destination


def finite(value: Any) -> bool:
    try:
        return value is not None and float(value) == float(value)
    except (TypeError, ValueError):
        return False


def physical_verdict(result: dict[str, Any], candidate_sha256: str) -> tuple[bool, str, dict[str, Any]]:
    results = result.get("results", {})
    pnr = results.get("pnr", {})
    power = results.get("power_mw", {})
    energy = results.get("energy_per_fft_nj", {})
    metrics = {
        "area_um2": pnr.get("cell_area_um2"),
        "timing_met": pnr.get("timing_met"),
        "setup_slack_ns": pnr.get("setup_slack_ns"),
        "hold_slack_ns": pnr.get("hold_slack_ns"),
        "drc_violations": result.get("drc_violation_lines"),
        "power_64_mw": (power.get("streaming_window_64", {}) or {}).get("total_mw"),
        "power_128_mw": (power.get("streaming_window_128", {}) or {}).get("total_mw"),
        "energy_64_nj": (energy.get("mode64", {}) or {}).get("value"),
        "energy_128_nj": (energy.get("mode128", {}) or {}).get("value"),
    }
    errors: list[str] = []
    if result.get("schema") != "peweaver-physical-result-2":
        errors.append("unexpected physical result schema")
    flow_hashes = result.get("flow_input_hashes_sha256", {})
    if flow_hashes.get("rtl/peweaver_shared_fft.v") != candidate_sha256:
        errors.append("physical result candidate hash mismatch")
    if metrics["timing_met"] is not True:
        errors.append(f"timing_met={metrics['timing_met']!r}")
    if metrics["drc_violations"] != 0:
        errors.append(f"drc_violations={metrics['drc_violations']!r}")
    if not finite(metrics["area_um2"]) or not 0 < float(metrics["area_um2"]) < STANDALONE_AREA_SUM_UM2:
        errors.append("placed area gate failed")
    for key in ("power_64_mw", "power_128_mw", "energy_64_nj", "energy_128_nj"):
        if not finite(metrics[key]):
            errors.append(f"missing finite metric: {key}")
    return not errors, "; ".join(errors) or "all physical gates passed", metrics


def build_prompt(reference_root: Path, previous: str = "", feedback: str = "") -> str:
    references: list[str] = []
    for relative in REFERENCE_FILES:
        path = reference_root / relative
        if not path.is_file():
            raise FileNotFoundError(f"reference input missing: {path}")
        references.append(f"===== {relative} =====\n{path.read_text()}")
    previous_section = ""
    if previous:
        previous_section = (
            "\nA prior candidate was generated by you in this same bounded run. "
            "Repair it using the feedback below; do not use any historical shared "
            "candidate.\n===== PRIOR GENERATED CANDIDATE =====\n" + previous
        )
    feedback_section = f"\nGATE FEEDBACK:\n{feedback}\n" if feedback else ""
    return (
        "You are the implementation stage of a hardware-sharing experiment. "
        "The controller, evaluator, and reference inputs are outside your control. "
        "Generate a new candidate from the supplied references and behavioral "
        "contract only. No pre-existing shared candidate is supplied.\n\n"
        + CONTRACT
        + "\n\nReturn exactly one complete fenced ```verilog code block and no prose."
        " The module must be named peweaver_shared_fft.\n"
        + previous_section
        + feedback_section
        + "\nREFERENCE INPUTS:\n"
        + "\n\n".join(references)
    )


def model_generate(llm, prompt: str) -> tuple[str, dict[str, Any]]:
    from chia.base.ChiaFunction import get

    response = get(llm.prompt.options(resources={"opencode_creds": 0.01}).chia_remote(
        llm, prompt, []
    ))
    raw = response.result or response.stream_result or response.stderr or ""
    candidate = extract_verilog(raw)
    return extract_verilog(raw), {
        "success": bool(response.success),
        "returncode": response.returncode,
        "response_sha256": hashlib.sha256(raw.encode()).hexdigest(),
        "candidate_sha256": hashlib.sha256(candidate.encode()).hexdigest()
        if candidate else "",
        "model_metadata": dict(getattr(llm, "_last_metadata", {}) or {}),
        "raw_response": raw,
    }


def require_resource(resources: dict[str, dict[str, float]], name: str, amount: float) -> None:
    if float(resources["cluster"].get(name, 0.0)) < amount:
        raise RuntimeError(f"Ray cluster does not advertise {name}>={amount:g}")
    if float(resources["available"].get(name, 0.0)) < amount:
        raise RuntimeError(f"Ray has no available {name} capacity")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--evaluator-root", type=Path, default=DEFAULT_EVALUATOR_ROOT)
    parser.add_argument("--run-base", type=Path, default=DEFAULT_RUN_BASE)
    parser.add_argument("--turns", type=int, default=1)
    parser.add_argument("--model-timeout", type=int, default=1800)
    parser.add_argument("--skip-physical", action="store_true")
    args = parser.parse_args(argv)
    if not 1 <= args.turns <= 2:
        parser.error("--turns must be 1 or 2; broad sweeps are not permitted")

    run_root = args.run_base / args.run_id
    manifest: dict[str, Any] = {
        "schema": "peweaver-chia-generated-loop-1",
        "run_id": args.run_id,
        "created_unix": time.time(),
        "status": "starting",
        "model": args.model,
        "evaluator_root": str(args.evaluator_root.resolve()),
        "historical_comparison": {
            "hashes": HISTORICAL_CANDIDATE_HASHES,
            "used_as_candidate": False,
            "provided_to_model": False,
        },
        "turns": [],
    }
    ray_module = None
    ray_started_here = False
    collector = None
    try:
        if not args.evaluator_root.is_dir():
            raise FileNotFoundError(f"evaluator root not found: {args.evaluator_root}")
        import ray

        ray_module = ray
        if not ray.is_initialized():
            ray.init(address=os.environ.get("RAY_ADDRESS", "auto"), ignore_reinit_error=True)
            ray_started_here = True
        resources = {
            "cluster": dict(ray.cluster_resources()),
            "available": dict(ray.available_resources()),
        }
        manifest["chia_resources"] = resources
        require_resource(resources, "opencode_creds", 0.01)
        require_resource(resources, "yosys", 1.0)

        from chia.models.opencode import OpenCodeLLM
        from chia.trace.profiler import get_collector, start_collector

        start_collector(log_dir=str(run_root / "artifacts" / "chia_trace"))
        collector = get_collector()
        if collector is not None:
            ray.get(collector.clear.remote())
        llm = OpenCodeLLM(
            model=args.model,
            system_message=(
                "You are a Verilog implementation engine. Return only one complete "
                "fenced Verilog code block. Do not use tools or edit files."
            ),
            timeout_seconds=args.model_timeout,
            retries=1,
            log_dir=str(run_root / "artifacts" / "model"),
            work_dir=str(run_root),
            opencode_bin=os.environ.get("PEWEAVER_OPENCODE_BIN", "opencode"),
            provider_options=(
                {
                    args.model.split("/", 1)[0]: {
                        "models": {
                            args.model.split("/", 1)[1]: {
                                "options": {"thinking": {"type": "disabled"}}
                            }
                        }
                    }
                }
                if "/" in args.model and args.model.startswith("opencode-go/")
                else None
            ),
        )

        previous = ""
        feedback = ""
        for turn in range(1, args.turns + 1):
            attempt_root = run_root / f"attempt-{turn}"
            source = copy_fresh_source(args.evaluator_root, attempt_root)
            candidate_target = source / "physical" / "rtl" / CANDIDATE_NAME
            # The evaluator snapshot may contain an old candidate.  Remove it
            # before generation so every accepted candidate is written from the
            # current model response in this turn.
            candidate_target.unlink(missing_ok=True)
            prompt = build_prompt(args.evaluator_root, previous, feedback)
            prompt_path = run_root / "artifacts" / f"prompt_turn{turn}.txt"
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text(prompt)
            candidate_text, model_record = model_generate(llm, prompt)
            raw_response = model_record.pop("raw_response")
            (run_root / "artifacts" / f"response_turn{turn}.txt").write_text(raw_response)
            turn_record: dict[str, Any] = {
                "turn": turn,
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "model": model_record,
                "attempt_root": str(attempt_root),
            }
            manifest["turns"].append(turn_record)
            if not model_record["success"] or not candidate_text:
                turn_record["status"] = "model_output_invalid"
                feedback = "The response contained no usable Verilog code block."
                previous = ""
                continue
            candidate_sha256 = hashlib.sha256(candidate_text.encode()).hexdigest()
            turn_record["candidate_sha256"] = candidate_sha256
            if candidate_sha256 in HISTORICAL_CANDIDATE_HASHES:
                turn_record["status"] = "historical_candidate_reuse_rejected"
                manifest["status"] = "rejected_historical_reuse"
                return 1
            candidate_target.parent.mkdir(parents=True, exist_ok=True)
            candidate_target.write_text(candidate_text)
            manifest["generated_candidate_sha256"] = candidate_sha256

            from evaluator_nodes import call_node, lint_node, sim_node

            lint = call_node(lint_node, candidate_text, TOP, PORTS)
            turn_record["lint"] = lint
            if not lint.get("passed"):
                turn_record["status"] = "lint_rejected"
                feedback = json.dumps(lint, sort_keys=True)
                previous = candidate_text
                continue

            functional = call_node(
                sim_node,
                [DEFAULT_PYTHON, "orchestration/shared_fft_regression.py", "--candidate",
                 f"physical/rtl/{CANDIDATE_NAME}", "--json"],
                str(source), env_path_prefix=DEFAULT_OSS, timeout=1800,
            )
            turn_record["functional_node"] = functional
            if not functional.get("passed"):
                turn_record["status"] = "functional_rejected"
                feedback = str(functional.get("note", "functional gate failed"))[-6000:]
                previous = candidate_text
                continue

            if args.skip_physical:
                turn_record["status"] = "functional_pass_physical_skipped"
                manifest["status"] = "functional_pass_physical_skipped"
                return 0

            result_path = source / "physical" / "results" / "shared_baseline_sky130.json"
            result_path.unlink(missing_ok=True)
            physical = call_node(
                sim_node,
                ["env", "PEWEAVER_DESIGN=shared",
                 f"PEWEAVER_YOSYS={DEFAULT_OSS}/yosys",
                 f"PEWEAVER_VERILATOR={DEFAULT_OSS}/verilator",
                 f"PEWEAVER_OPENROAD={DEFAULT_OPENROAD}/openroad",
                 f"PEWEAVER_VOLARE_VENV={DEFAULT_VOLARE}",
                 f"PEWEAVER_PDK_ROOT={DEFAULT_PDK}",
                 f"PEWEAVER_PYTHON={DEFAULT_PYTHON}", "./run-physical.sh"],
                str(source / "physical"),
                env_path_prefix=f"{DEFAULT_OSS}:{DEFAULT_OPENROAD}",
                timeout=10800,
            )
            result = json.loads(result_path.read_text()) if result_path.is_file() else {}
            passed, note, metrics = physical_verdict(result, candidate_sha256)
            turn_record.update({
                "physical_node": physical,
                "physical_verdict": passed,
                "physical_note": note,
                "metrics": metrics,
                "result_path": str(result_path),
            })
            if physical.get("passed") and passed:
                turn_record["status"] = "promoted"
                manifest["status"] = "accepted_model_generated_fft"
                manifest["accepted_attempt"] = turn
                return 0
            turn_record["status"] = "physical_rejected"
            feedback = note
            previous = candidate_text

        manifest["status"] = "exhausted_without_acceptance"
        return 1
    except Exception as exc:
        manifest["status"] = "blocked"
        manifest["error"] = f"{type(exc).__name__}: {exc}"
        return 2
    finally:
        if run_root.exists():
            if collector is not None and ray_module is not None:
                try:
                    events = ray_module.get(collector.get_events.remote())
                    write_json(run_root / "artifacts" / "chia_trace" / "events.json", events)
                except Exception as exc:
                    manifest.setdefault("trace_errors", []).append(str(exc))
                try:
                    from chia.trace.profiler import stop_collector

                    stop_collector()
                except Exception as exc:
                    manifest.setdefault("trace_errors", []).append(str(exc))
            write_json(run_root / "manifest.json", manifest)
        if ray_started_here and ray_module is not None:
            ray_module.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
