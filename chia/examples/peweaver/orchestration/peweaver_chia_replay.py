#!/usr/bin/env python3
"""Minimal CHIA-composed replay of the verified shared FFT result.

This is intentionally not another merge framework.  The controller owns only
the PEWeaver policy and run record; CHIA owns model/evaluator dispatch through
Ray, resource scheduling, and profiling.  The evaluator remains the frozen
Yosys -> Icarus/Verilator -> OpenROAD -> OpenSTA flow.

The default candidate is the accepted clean-room candidate
``ce64c71552f0aa1750ae62c15a081d16d52e92396d9d67243088aeec4723e92e``.
Replay mode does not ask a model to rewrite the candidate.  ``--model`` adds
one bounded CHIA-native advice call and records it without changing the
verified input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
PEWEAVER = HERE.parent
DEFAULT_CANDIDATE = HERE / "runs" / "merge_clean_1" / "peweaver_shared_fft.mergerun1.v"
DEFAULT_SOURCE = PEWEAVER
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
EXPECTED_CANDIDATE_SHA256 = (
    "ce64c71552f0aa1750ae62c15a081d16d52e92396d9d67243088aeec4723e92e"
)
STANDALONE_AREA_SUM_UM2 = 424885.0
PORTS = [
    "clock",
    "reset",
    "mode",
    "di_en",
    "di_re",
    "di_im",
    "do_en",
    "do_re",
    "do_im",
]


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


def json_from_tail(text: str) -> dict[str, Any]:
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def finite_number(value: Any) -> bool:
    try:
        return value is not None and float(value) == float(value)
    except (TypeError, ValueError):
        return False


def physical_metrics(result: dict[str, Any]) -> dict[str, Any]:
    results = result.get("results", {})
    pnr = results.get("pnr", {})
    power = results.get("power_mw", {})
    energy = results.get("energy_per_fft_nj", {})
    return {
        "area_um2": pnr.get("cell_area_um2"),
        "timing_met": pnr.get("timing_met"),
        "setup_slack_ns": pnr.get("setup_slack_ns"),
        "hold_slack_ns": pnr.get("hold_slack_ns"),
        "drc_violations": result.get("drc_violation_lines"),
        "streaming_power_64_mw": (
            power.get("streaming_window_64", {}) or {}
        ).get("total_mw"),
        "streaming_power_128_mw": (
            power.get("streaming_window_128", {}) or {}
        ).get("total_mw"),
        "energy_64_nj": (energy.get("mode64", {}) or {}).get("value"),
        "energy_128_nj": (energy.get("mode128", {}) or {}).get("value"),
    }


def physical_verdict(
    result: dict[str, Any], candidate_sha256: str
) -> tuple[bool, str, dict[str, Any]]:
    metrics = physical_metrics(result)
    errors: list[str] = []
    if result.get("schema") != "peweaver-physical-result-2":
        errors.append("unexpected physical result schema")
    hashes = result.get("flow_input_hashes_sha256", {})
    if hashes.get("rtl/peweaver_shared_fft.v") != candidate_sha256:
        errors.append("physical result RTL hash does not match candidate")
    if metrics["timing_met"] is not True:
        errors.append(f"timing_met={metrics['timing_met']!r}")
    if metrics["drc_violations"] != 0:
        errors.append(f"drc_violations={metrics['drc_violations']!r}")
    area = metrics["area_um2"]
    if not finite_number(area) or not 0 < float(area) < STANDALONE_AREA_SUM_UM2:
        errors.append(f"area={area!r} is not below {STANDALONE_AREA_SUM_UM2:g}")
    for name in (
        "streaming_power_64_mw",
        "streaming_power_128_mw",
        "energy_64_nj",
        "energy_128_nj",
    ):
        if not finite_number(metrics[name]):
            errors.append(f"missing finite metric: {name}")
    return not errors, "; ".join(errors) or "timing, DRC, area, power, and energy passed", metrics


def resource_snapshot(ray_module) -> dict[str, dict[str, float]]:
    return {
        "cluster": dict(ray_module.cluster_resources()),
        "available": dict(ray_module.available_resources()),
    }


def require_resource(resources: dict[str, dict[str, float]], name: str, amount: float) -> None:
    if float(resources["cluster"].get(name, 0.0)) < amount:
        raise RuntimeError(f"Ray cluster does not advertise {name}>={amount:g}")
    if float(resources["available"].get(name, 0.0)) < amount:
        raise RuntimeError(f"Ray has no currently available {name} capacity")


def copy_fresh_source(source_root: Path, run_root: Path) -> Path:
    if run_root.exists():
        raise FileExistsError(f"run root already exists; use a new run id: {run_root}")
    source = run_root / "source"
    run_root.mkdir(parents=True)
    def ignore(path: str, names: list[str]) -> set[str]:
        relative = Path(path).relative_to(source_root)
        if relative == Path("physical") and "results" in names:
            # The flow creates fresh results.  The source tree can contain
            # multi-gigabyte historical VCD/DEF/SPEF artifacts.
            return {"results"}
        if relative == Path("orchestration") and "runs" in names:
            return {"runs"}
        return {
            name
            for name in names
            if name in {".git", "__pycache__", ".pytest_cache"}
        }

    shutil.copytree(source_root, source, symlinks=True, ignore=ignore)
    leakage = source_root / "physical" / "results" / "leakage_check"
    if leakage.is_dir():
        shutil.copytree(leakage, source / "physical" / "results" / "leakage_check")
    return source


def call_chia(node, *args, **kwargs) -> dict[str, Any]:
    """Call an existing CHIA node; infrastructure errors remain distinguishable."""
    from evaluator_nodes import RetryableError, call_node

    try:
        return call_node(node, *args, **kwargs)
    except RetryableError as exc:
        raise RuntimeError(f"retryable CHIA infrastructure failure: {exc}") from exc


def run_advice(model: str, run_root: Path, candidate_sha256: str, timeout: int) -> dict[str, Any]:
    from chia.base.ChiaFunction import get
    from chia.models.opencode import OpenCodeLLM

    prompt = f"""You are advising a hardware-sharing reproduction, not rewriting it.
The candidate is the already verified shared 64/128-point FFT, SHA-256
{candidate_sha256}. Give at most three concise observations about why a CHIA
execution graph should preserve reproducibility, exact latency, and the
frozen physical-flow comparison. Do not propose a code change and do not use
tools."""
    llm = OpenCodeLLM(
        model=model,
        system_message="Return concise architecture advice only.",
        timeout_seconds=timeout,
        retries=1,
        log_dir=str(run_root / "artifacts" / "model"),
    )
    # The bound ChiaFunction method follows CHIA's existing method-dispatch
    # convention: the instance is explicit in the remote call.
    response = get(llm.prompt.options(resources={"opencode_creds": 0.01}).chia_remote(
        llm, prompt, []
    ))
    text = response.result or response.stream_result or response.stderr or ""
    (run_root / "artifacts" / "model" / "advice.txt").write_text(text)
    return {
        "status": "passed" if response.success else "failed",
        "success": bool(response.success),
        "returncode": response.returncode,
        "model": model,
        "response_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "metadata": dict(getattr(llm, "_last_metadata", {}) or {}),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--run-base", type=Path, default=DEFAULT_RUN_BASE)
    parser.add_argument("--model", help="optional one-call CHIA-native advice model")
    parser.add_argument("--model-timeout", type=int, default=900)
    parser.add_argument("--skip-physical", action="store_true")
    parser.add_argument("--allow-other-candidate", action="store_true")
    args = parser.parse_args(argv)

    run_root = args.run_base / args.run_id
    manifest: dict[str, Any] = {
        "schema": "peweaver-chia-replay-1",
        "run_id": args.run_id,
        "created_unix": time.time(),
        "status": "starting",
        "controller": str(Path(__file__).resolve()),
        "candidate_input": str(args.candidate.resolve()),
        "source_root": str(args.source_root.resolve()),
        "stages": [],
    }

    ray_module = None
    ray_started_here = False
    collector = None
    try:
        if not args.candidate.is_file():
            raise FileNotFoundError(f"candidate not found: {args.candidate}")
        candidate_sha256 = sha256_file(args.candidate)
        manifest["candidate_sha256"] = candidate_sha256
        if not args.allow_other_candidate and candidate_sha256 != EXPECTED_CANDIDATE_SHA256:
            raise ValueError(
                f"candidate hash {candidate_sha256} is not the verified accepted hash "
                f"{EXPECTED_CANDIDATE_SHA256}"
            )
        if not args.source_root.is_dir():
            raise FileNotFoundError(f"source root not found: {args.source_root}")

        import ray

        ray_module = ray
        if not ray.is_initialized():
            ray.init(address=os.environ.get("RAY_ADDRESS", "auto"), ignore_reinit_error=True)
            ray_started_here = True
        resources = resource_snapshot(ray)
        manifest["chia"] = {"ray_resources": resources}
        require_resource(resources, "yosys", 1.0)

        source = copy_fresh_source(args.source_root, run_root)
        manifest["run_root"] = str(run_root)
        candidate_target = source / "physical" / "rtl" / CANDIDATE_NAME
        candidate_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(args.candidate, candidate_target)
        manifest["candidate_target"] = str(candidate_target)

        from chia.trace.profiler import get_collector, start_collector, stop_collector

        start_collector(log_dir=str(run_root / "artifacts" / "chia_trace"))
        collector = get_collector()
        if collector is not None:
            ray.get(collector.clear.remote())

        if args.model:
            require_resource(resources, "opencode_creds", 0.01)
            manifest["advice"] = run_advice(
                args.model, run_root, candidate_sha256, args.model_timeout
            )
            if not manifest["advice"]["success"]:
                raise RuntimeError("CHIA-native advice call failed")
        else:
            manifest["advice"] = {
                "status": "skipped",
                "reason": "verified-candidate replay; no model rewrite requested",
            }

        from evaluator_nodes import call_node, lint_node, sim_node

        lint = call_chia(lint_node, candidate_target.read_text(), TOP, PORTS)
        lint_record = {"name": "lint", **lint}
        manifest["stages"].append(lint_record)
        if not lint.get("passed"):
            manifest["status"] = "rejected_lint"
            return 1

        functional_command = [
            DEFAULT_PYTHON,
            "orchestration/shared_fft_regression.py",
            "--candidate",
            f"physical/rtl/{CANDIDATE_NAME}",
            "--json",
        ]
        functional = call_chia(
            sim_node,
            functional_command,
            str(source),
            env_path_prefix=DEFAULT_OSS,
            timeout=1800,
        )
        functional_json = json_from_tail(str(functional.get("note", "")))
        functional_record = {
            "name": "functional",
            "node_passed": bool(functional.get("passed")),
            "judge": functional_json,
        }
        manifest["stages"].append(functional_record)
        if not functional.get("passed") or not functional_json.get("passed"):
            manifest["status"] = "rejected_functional"
            return 1

        if args.skip_physical:
            manifest["status"] = "functional_pass_physical_skipped"
            return 0

        result_path = source / "physical" / "results" / "shared_baseline_sky130.json"
        result_path.unlink(missing_ok=True)
        physical_command = [
            "env",
            "PEWEAVER_DESIGN=shared",
            f"PEWEAVER_YOSYS={DEFAULT_OSS}/yosys",
            f"PEWEAVER_VERILATOR={DEFAULT_OSS}/verilator",
            f"PEWEAVER_OPENROAD={DEFAULT_OPENROAD}/openroad",
            f"PEWEAVER_VOLARE_VENV={DEFAULT_VOLARE}",
            f"PEWEAVER_PDK_ROOT={DEFAULT_PDK}",
            f"PEWEAVER_PYTHON={DEFAULT_PYTHON}",
            "./run-physical.sh",
        ]
        physical = call_chia(
            sim_node,
            physical_command,
            str(source / "physical"),
            env_path_prefix=f"{DEFAULT_OSS}:{DEFAULT_OPENROAD}",
            timeout=10800,
        )
        physical_result = (
            json.loads(result_path.read_text()) if result_path.is_file() else {}
        )
        passed, note, metrics = physical_verdict(physical_result, candidate_sha256)
        manifest["stages"].append(
            {
                "name": "physical",
                "node_passed": bool(physical.get("passed")),
                "verdict": passed,
                "note": note,
                "metrics": metrics,
                "result_path": str(result_path),
                "result": physical_result,
            }
        )
        if not physical.get("passed") or not passed:
            manifest["status"] = "rejected_physical"
            return 1
        manifest["status"] = "accepted_verified_fft"
        return 0
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
                    manifest.setdefault("trace_errors", []).append(
                        f"collect: {type(exc).__name__}: {exc}"
                    )
                try:
                    from chia.trace.profiler import stop_collector

                    stop_collector()
                except Exception as exc:
                    manifest.setdefault("trace_errors", []).append(
                        f"stop: {type(exc).__name__}: {exc}"
                    )
            manifest_path = run_root / "manifest.json"
            write_json(manifest_path, manifest)
            stage_results = []
            for stage in manifest["stages"]:
                if stage.get("name") == "functional":
                    passed = bool(stage.get("node_passed")) and bool(
                        stage.get("judge", {}).get("passed")
                    )
                elif stage.get("name") == "physical":
                    passed = bool(stage.get("node_passed")) and bool(
                        stage.get("verdict")
                    )
                else:
                    passed = stage.get("passed")
                stage_results.append({"name": stage.get("name"), "passed": passed})
            trace_path = run_root / "artifacts" / "chia_trace" / "events.json"
            print(
                json.dumps(
                    {
                        "status": manifest["status"],
                        "candidate_sha256": manifest.get("candidate_sha256"),
                        "stages": stage_results,
                        "manifest": str(manifest_path),
                        "trace": str(trace_path) if trace_path.is_file() else None,
                    },
                    sort_keys=True,
                )
            )
        if ray_started_here and ray_module is not None:
            ray_module.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
