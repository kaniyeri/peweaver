"""Deterministic Yosys equivalence checks for PEWeaver benchmark manifests.

The module intentionally has no third-party dependencies.  A manifest is JSON and
may contain ``sources`` (or ``verilog``/``files``), ``miter``/``top``, and
``expected_equivalent``.  Source paths are relative to the manifest directory.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

try:
    from .manifest_schema import validate_manifest
except ImportError:  # direct script execution from examples/peweaver
    from manifest_schema import validate_manifest

DEFAULT_BENCHMARK_ROOT = Path(__file__).resolve().parent / "benchmarks"


@dataclass(frozen=True)
class Manifest:
    path: Path
    sources: tuple[Path, ...]
    miter: str
    expected_equivalent: bool
    name: str


@dataclass
class EquivalenceResult:
    name: str
    manifest: str
    expected_equivalent: bool
    actual_equivalent: bool | None
    status: str
    passed: bool
    duration_seconds: float
    yosys: str | None
    log: str
    script: str

    def json_dict(self) -> dict[str, Any]:
        return asdict(self)


def _source_values(data: dict[str, Any]) -> list[str]:
    for key in ("sources", "source", "verilog", "files"):
        value = data.get(key)
        if value is not None:
            if isinstance(value, str):
                return [value]
            if isinstance(value, list) and all(isinstance(x, str) for x in value):
                return value
    raise ValueError("manifest must define a string/list field: sources, verilog, or files")


def load_manifest(path: Path) -> Manifest:
    data = json.loads(path.read_text(encoding="utf-8"))
    validate_manifest(data, path=str(path))
    sources = tuple((path.parent / x).resolve() for x in _source_values(data))
    top = data.get("miter", data.get("top"))
    if not isinstance(top, str) or not top:
        raise ValueError("manifest must define miter or top")
    expected = data.get("expected_equivalent", data.get("expected", True))
    if not isinstance(expected, bool):
        raise ValueError("expected_equivalent must be boolean")
    return Manifest(path.resolve(), sources, top, expected, str(data.get("name", path.stem)))


def discover_manifests(root: Path) -> list[Manifest]:
    """Load JSON manifests below *root*, in stable path order."""
    manifests: list[Manifest] = []
    for path in sorted(root.rglob("*.json")):
        # Ignore ordinary metadata files that are not benchmark manifests.
        try:
            manifests.append(load_manifest(path))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return manifests


def resolve_yosys() -> str | None:
    configured = os.environ.get("PEWEAVER_YOSYS")
    if configured:
        return configured
    return shutil.which("yosys") or shutil.which("yowasp-yosys")


def _ys_quote(path: Path) -> str:
    # Yosys scripts use double-quoted filenames; this handles Windows backslashes.
    return '"' + str(path).replace('\\', '/').replace('"', '\\"') + '"'


def make_script(manifest: Manifest) -> str:
    files = " ".join(_ys_quote(x) for x in manifest.sources)
    return (f"read_verilog -formal -sv {files}\n"
            f"prep -top {manifest.miter} -flatten\n"
            "sat -verify -prove mismatch 0 -show-inputs -show-outputs\n")


def _classify(returncode: int, log: str) -> tuple[str, bool | None]:
    lower = log.lower()
    if returncode == 0 and ("no model found" in lower or "proof finished" in lower or "success" in lower):
        return "equivalent", True
    if "model found" in lower or "counterexample" in lower:
        return "inequivalent", False
    return "tool_error", None


def run_manifest(manifest: Manifest, yosys: str | None = None, timeout: float | None = None) -> EquivalenceResult:
    tool = yosys or resolve_yosys()
    script = make_script(manifest)
    started = time.monotonic()
    if tool is None:
        return EquivalenceResult(manifest.name, str(manifest.path), manifest.expected_equivalent, None,
                                 "tool_error", False, time.monotonic() - started, None,
                                 "Yosys executable not found (set PEWEAVER_YOSYS or install yosys).", script)
    missing = [str(p) for p in manifest.sources if not p.is_file()]
    if missing:
        return EquivalenceResult(manifest.name, str(manifest.path), manifest.expected_equivalent, None,
                                 "tool_error", False, time.monotonic() - started, tool,
                                 "Missing source file(s): " + ", ".join(missing), script)
    try:
        proc = subprocess.run([tool, "-p", script], capture_output=True, text=True,
                              timeout=timeout, check=False)
        log = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        status, actual = _classify(proc.returncode, log)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log, status, actual = str(exc), "tool_error", None
    return EquivalenceResult(manifest.name, str(manifest.path), manifest.expected_equivalent, actual,
                             status, actual is not None and actual == manifest.expected_equivalent,
                             time.monotonic() - started, tool, log, script)


def run_all(root: Path, yosys: str | None = None, timeout: float | None = None) -> list[EquivalenceResult]:
    return [run_manifest(m, yosys=yosys, timeout=timeout) for m in discover_manifests(root)]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=DEFAULT_BENCHMARK_ROOT)
    parser.add_argument("--json", dest="json_path", type=Path)
    parser.add_argument("--timeout", type=float)
    args = parser.parse_args(argv)
    results = run_all(args.root, timeout=args.timeout)
    if not results:
        print(f"No benchmark manifests found under {args.root}", file=sys.stderr)
        return 2
    for result in results:
        print(f"{result.name}: {result.status} ({'PASS' if result.passed else 'FAIL'}) "
              f"{result.duration_seconds:.3f}s")
        if result.status == "tool_error":
            print(result.log, file=sys.stderr)
    if args.json_path:
        args.json_path.write_text(json.dumps([r.json_dict() for r in results], indent=2), encoding="utf-8")
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
