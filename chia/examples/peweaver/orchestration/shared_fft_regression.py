#!/usr/bin/env python3
"""Fast, fail-closed functional regression for the shared FFT candidate.

This is the immutable outer-loop judge.  It compiles a fresh Verilator binary
and accepts only the explicit activity-testbench success marker after both the
64- and 128-point single-frame and continuous-streaming tests pass.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    peweaver = Path(__file__).resolve().parents[1]
    physical = peweaver / "physical"
    candidate = (args.candidate or physical / "rtl" / "peweaver_shared_fft.v").resolve()
    wrapper = physical / "rtl" / "peweaver_ppa_shared_fft.v"
    testbench = physical / "activity" / "shared_activity_tb.sv"
    fixture = peweaver / "benchmarks" / "halo_fft64_reference"
    verilator = os.environ.get("PEWEAVER_VERILATOR") or shutil.which("verilator")

    started = time.monotonic()
    result: dict[str, object] = {
        "schema": "peweaver-shared-regression-1",
        "candidate": str(candidate),
        "passed": False,
        "status": "tool_error",
        "compile_returncode": None,
        "run_returncode": None,
        "log_tail": "",
    }
    if not verilator:
        result["log_tail"] = "verilator not found (set PEWEAVER_VERILATOR)"
        print(json.dumps(result, sort_keys=True) if args.json else result["log_tail"])
        return 2
    for path in (candidate, wrapper, testbench, fixture):
        if not path.exists():
            result["log_tail"] = f"required path missing: {path}"
            print(json.dumps(result, sort_keys=True) if args.json else result["log_tail"])
            return 2

    try:
        with tempfile.TemporaryDirectory(prefix="peweaver-shared-") as tmp:
            build = Path(tmp) / "obj"
            compile_cmd = [
                verilator, "--binary", "--timing", "--x-assign", "0",
                "--x-initial", "0", "-Wno-fatal",
                "--top-module", "peweaver_shared_activity_tb",
                "--Mdir", str(build), str(wrapper), str(candidate), str(testbench),
            ]
            compiled = subprocess.run(
                compile_cmd, cwd=physical, capture_output=True, text=True,
                timeout=args.timeout, check=False)
            result["compile_returncode"] = compiled.returncode
            compile_log = (compiled.stdout or "") + (compiled.stderr or "")
            if compiled.returncode != 0:
                result["status"] = "compile_failed"
                result["log_tail"] = compile_log[-12000:]
            else:
                binary = build / "Vpeweaver_shared_activity_tb"
                executed = subprocess.run(
                    [str(binary)], cwd=fixture, capture_output=True, text=True,
                    timeout=args.timeout, check=False)
                result["run_returncode"] = executed.returncode
                run_log = (executed.stdout or "") + (executed.stderr or "")
                passed = (
                    executed.returncode == 0
                    and "PEWEAVER_ACTIVITY_DONE" in run_log
                    and "PEWEAVER_ACTIVITY_ERROR" not in run_log
                )
                result["passed"] = passed
                result["status"] = "passed" if passed else "functional_failed"
                result["log_tail"] = run_log[-12000:]
    except subprocess.TimeoutExpired as exc:
        result["status"] = "timeout"
        result["log_tail"] = f"timed out after {exc.timeout}s"
    except Exception as exc:  # outer judge fails closed on every tool error
        result["status"] = "tool_error"
        result["log_tail"] = f"{type(exc).__name__}: {exc}"

    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"shared regression: {result['status']}")
        if result["log_tail"]:
            print(result["log_tail"])
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(run())
