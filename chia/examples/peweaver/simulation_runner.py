"""Fail-closed Verilator simulation gate for PEWeaver manifests."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

try:
    from .equivalence_runner import DEFAULT_BENCHMARK_ROOT, Manifest, discover_manifests
except ImportError:  # direct script execution from examples/peweaver
    from equivalence_runner import DEFAULT_BENCHMARK_ROOT, Manifest, discover_manifests


@dataclass
class SimulationResult:
    name: str
    manifest: str
    expected_equivalent: bool
    status: str
    passed: bool
    duration_seconds: float
    verilator: str | None
    compile_command: list[str]
    run_command: list[str]
    log: str

    def json_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_verilator() -> str | None:
    configured = os.environ.get("PEWEAVER_VERILATOR")
    if configured:
        return configured
    return shutil.which("verilator")


def simulation_spec(manifest: Manifest) -> tuple[Path, str]:
    data = json.loads(manifest.path.read_text(encoding="utf-8"))
    testbench = data.get("simulation_testbench")
    top = data.get("simulation_top")
    if not isinstance(testbench, str) or not testbench:
        raise ValueError("manifest must define simulation_testbench")
    if not isinstance(top, str) or not top:
        raise ValueError("manifest must define simulation_top")
    path = (manifest.path.parent / testbench).resolve()
    if not path.is_file():
        raise ValueError(f"missing simulation testbench: {path}")
    return path, top


def run_manifest(manifest: Manifest, verilator: str | None = None, timeout: float = 60.0) -> SimulationResult:
    tool = verilator or resolve_verilator()
    started = time.monotonic()
    if tool is None:
        return SimulationResult(manifest.name, str(manifest.path), manifest.expected_equivalent,
                                "tool_error", False, time.monotonic() - started, None, [], [],
                                "Verilator executable not found (set PEWEAVER_VERILATOR or install Verilator).")
    try:
        testbench, top = simulation_spec(manifest)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return SimulationResult(manifest.name, str(manifest.path), manifest.expected_equivalent,
                                "tool_error", False, time.monotonic() - started, tool, [], [], str(exc))

    files = [*map(str, manifest.sources), str(testbench)]
    with tempfile.TemporaryDirectory(prefix=f"peweaver-{manifest.name}-") as temp_dir:
        build_dir = Path(temp_dir) / "obj_dir"
        compile_command = [tool, "--binary", "--timing", "--top-module", top,
                           "--Mdir", str(build_dir), "-Wno-fatal", *files]
        try:
            compiled = subprocess.run(compile_command, capture_output=True, text=True,
                                     timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return SimulationResult(manifest.name, str(manifest.path), manifest.expected_equivalent,
                                    "tool_error", False, time.monotonic() - started, tool,
                                    compile_command, [], str(exc))
        compile_log = (compiled.stdout or "") + ("\n" + compiled.stderr if compiled.stderr else "")
        binary = build_dir / f"V{top}"
        run_command = [str(binary)]
        if compiled.returncode != 0 or not binary.is_file():
            return SimulationResult(manifest.name, str(manifest.path), manifest.expected_equivalent,
                                    "compile_error", False, time.monotonic() - started, tool,
                                    compile_command, run_command, compile_log)
        try:
            executed = subprocess.run(run_command, capture_output=True, text=True,
                                     timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return SimulationResult(manifest.name, str(manifest.path), manifest.expected_equivalent,
                                    "tool_error", False, time.monotonic() - started, tool,
                                    compile_command, run_command, compile_log + "\n" + str(exc))
        run_log = (executed.stdout or "") + ("\n" + executed.stderr if executed.stderr else "")
        passed = executed.returncode == 0 and "PEWEAVER_SIM_PASS" in run_log
        status = "passed" if passed else "simulation_failed"
        return SimulationResult(manifest.name, str(manifest.path), manifest.expected_equivalent,
                                status, passed, time.monotonic() - started, tool,
                                compile_command, run_command, compile_log + "\n" + run_log)


def run_all(root: Path, verilator: str | None = None, timeout: float = 60.0) -> list[SimulationResult]:
    return [run_manifest(manifest, verilator=verilator, timeout=timeout)
            for manifest in discover_manifests(root)]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=DEFAULT_BENCHMARK_ROOT)
    parser.add_argument("--json", dest="json_path", type=Path)
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args(argv)
    results = run_all(args.root, timeout=args.timeout)
    if not results:
        print(f"No benchmark manifests found under {args.root}")
        return 2
    for result in results:
        print(f"{result.name}: {result.status} ({'PASS' if result.passed else 'FAIL'}) "
              f"{result.duration_seconds:.3f}s")
    if args.json_path:
        args.json_path.write_text(json.dumps([result.json_dict() for result in results], indent=2),
                                 encoding="utf-8")
    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
