"""Generic-cell synthesis proxy for PEWeaver benchmark alternatives.

This produces reproducible Yosys post-techmap cell counts. It is deliberately
not an ASIC PPA report: area, timing, leakage, and power require a named cell
library, constraints, and an activity model.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

try:
    from .equivalence_runner import DEFAULT_BENCHMARK_ROOT, Manifest, discover_manifests, resolve_yosys
except ImportError:
    from equivalence_runner import DEFAULT_BENCHMARK_ROOT, Manifest, discover_manifests, resolve_yosys


@dataclass(frozen=True)
class SynthesisSpec:
    baseline_top: str
    candidate_top: str


@dataclass
class SynthesisResult:
    name: str
    expected_equivalent: bool
    comparison_eligible: bool
    status: str
    passed: bool
    duration_seconds: float
    yosys: str | None
    baseline: dict[str, Any] | None
    candidate: dict[str, Any] | None
    cell_delta: int | None
    cell_reduction_percent: float | None
    note: str
    log: str

    def json_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_synthesis_spec(manifest: Manifest) -> SynthesisSpec:
    data = json.loads(manifest.path.read_text(encoding="utf-8"))
    spec = data.get("synthesis")
    if not isinstance(spec, dict):
        raise ValueError("manifest must define synthesis object")
    baseline, candidate = spec.get("baseline_top"), spec.get("candidate_top")
    if not all(isinstance(value, str) and value for value in (baseline, candidate)):
        raise ValueError("synthesis.baseline_top and synthesis.candidate_top must be non-empty strings")
    return SynthesisSpec(baseline, candidate)


def _quote(path: Path) -> str:
    return '"' + str(path).replace("\\", "/").replace('"', '\\"') + '"'


def make_script(manifest: Manifest, top: str) -> str:
    files = " ".join(_quote(source) for source in manifest.sources)
    return f"read_verilog -sv {files}\nhierarchy -top {top}\nproc\nopt\ntechmap\nopt\nstat -json\n"


def _extract_stat(log: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    for index, char in enumerate(log):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(log[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get("design"), dict):
            return value["design"]
    raise ValueError("Yosys did not emit a stat -json design object")


def _run_top(manifest: Manifest, top: str, tool: str, timeout: float | None) -> tuple[dict[str, Any], str]:
    proc = subprocess.run([tool, "-Q", "-p", make_script(manifest, top)], capture_output=True,
                          text=True, timeout=timeout, check=False)
    log = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    if proc.returncode:
        raise RuntimeError(f"Yosys exited {proc.returncode}: {log}")
    return _extract_stat(log), log


def run_manifest(manifest: Manifest, yosys: str | None = None, timeout: float | None = None) -> SynthesisResult:
    started = time.monotonic()
    tool = yosys or resolve_yosys()
    if tool is None:
        return SynthesisResult(manifest.name, manifest.expected_equivalent, False, "tool_error", False,
                               time.monotonic() - started, None, None, None, None, None,
                               "Yosys executable not found.", "")
    try:
        spec = load_synthesis_spec(manifest)
        baseline, baseline_log = _run_top(manifest, spec.baseline_top, tool, timeout)
        candidate, candidate_log = _run_top(manifest, spec.candidate_top, tool, timeout)
        baseline_cells, candidate_cells = baseline["num_cells"], candidate["num_cells"]
        delta = candidate_cells - baseline_cells
        reduction = round((baseline_cells - candidate_cells) * 100.0 / baseline_cells, 3) if baseline_cells else None
        eligible = manifest.expected_equivalent
        note = ("Generic-cell RTL synthesis proxy only; no ASIC PPA claim. "
                + ("Candidate is formally eligible for comparison." if eligible else
                   "Candidate is intentionally inequivalent and is ineligible for optimization."))
        return SynthesisResult(manifest.name, manifest.expected_equivalent, eligible, "ok", True,
                               time.monotonic() - started, tool, baseline, candidate, delta, reduction,
                               note, baseline_log + "\n--- candidate ---\n" + candidate_log)
    except (OSError, subprocess.TimeoutExpired, RuntimeError, ValueError, KeyError) as exc:
        return SynthesisResult(manifest.name, manifest.expected_equivalent, False, "tool_error", False,
                               time.monotonic() - started, tool, None, None, None, None,
                               "Synthesis proxy did not complete.", str(exc))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=DEFAULT_BENCHMARK_ROOT)
    parser.add_argument("--json", dest="json_path", type=Path)
    parser.add_argument("--timeout", type=float)
    args = parser.parse_args(argv)
    results = [run_manifest(manifest, timeout=args.timeout) for manifest in discover_manifests(args.root)]
    if not results:
        print(f"No benchmark manifests found under {args.root}")
        return 2
    for result in results:
        cells = "n/a" if result.cell_delta is None else f"{result.cell_delta:+d} cells"
        eligibility = "eligible" if result.comparison_eligible else "ineligible"
        print(f"{result.name}: {result.status} ({eligibility}; {cells})")
    if args.json_path:
        args.json_path.write_text(json.dumps([result.json_dict() for result in results], indent=2), encoding="utf-8")
    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
