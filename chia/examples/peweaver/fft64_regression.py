"""Fail-closed directed Verilator regression for the FFT64 reference fixture.

Phase A stateful reference integration: compiles the curated r22sdf 64-point
FFT (HALO-inspired stateful FFT proxy) with its PEWeaver wrapper and directed
testbench, runs it, and passes only on an explicit ``PEWEAVER_SIM_PASS`` marker
with exit status zero. A missing tool, compile error, timeout, or unknown
result fails closed. This fixture has no formal miter; it is intentionally not
part of the formal-equivalence corpus.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

try:
    from .manifest_schema import validate_manifest
except ImportError:  # direct script execution from examples/peweaver
    from manifest_schema import validate_manifest

DEFAULT_FIXTURE = Path(__file__).resolve().parent / "benchmarks" / "halo_fft64_reference"
PASS_MARKER = "PEWEAVER_SIM_PASS halo_fft64_reference"
SAMPLES_PER_FRAME = 64
_WIDTH_BITS = 16
_VECTOR_LINE = re.compile(r"^\s*([0-9A-Fa-f]{1,4})\s+([0-9A-Fa-f]{1,4})(?:\s|//|$)")


@dataclass
class RegressionResult:
    name: str
    fixture: str
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
    """Resolve Verilator like run-local.sh: env override, OSS CAD Suite, PATH."""
    configured = os.environ.get("PEWEAVER_VERILATOR")
    if configured:
        return configured
    # <repo>/examples/peweaver/fft64_regression.py -> <repo>/../toolchains
    suite = Path(__file__).resolve().parent.parent.parent.parent / "toolchains" / "oss-cad-suite" / "bin" / "verilator"
    if suite.is_file() and os.access(suite, os.X_OK):
        return str(suite)
    return shutil.which("verilator")


def load_vector_file(path: Path) -> list[tuple[int, int]]:
    """Parse an upstream r22sdf hex vector file into 64 (re, im) sample pairs."""
    pairs: list[tuple[int, int]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        match = _VECTOR_LINE.match(line)
        if match is None:
            raise ValueError(f"{path}:{line_number}: malformed vector line: {line!r}")
        re_value, im_value = int(match.group(1), 16), int(match.group(2), 16)
        if not (0 <= re_value < (1 << _WIDTH_BITS) and 0 <= im_value < (1 << _WIDTH_BITS)):
            raise ValueError(f"{path}:{line_number}: sample outside unsigned 16-bit range")
        pairs.append((re_value, im_value))
    if len(pairs) != SAMPLES_PER_FRAME:
        raise ValueError(f"{path}: expected {SAMPLES_PER_FRAME} samples, found {len(pairs)}")
    return pairs


def load_fixture(fixture: Path) -> dict[str, Any]:
    """Load and validate the reference fixture manifest (fail closed)."""
    manifest_path = fixture / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_manifest(data, path=str(manifest_path))
    for field in ("sources", "directed_testbench", "directed_top"):
        if field not in data:
            raise ValueError(f"{manifest_path}: missing required field {field!r}")
    forbidden_corpus_fields = ("miter", "top", "expected_equivalent", "synthesis")
    if any(field in data for field in forbidden_corpus_fields):
        raise ValueError(
            f"{manifest_path}: reference fixture must not define formal or synthesis-corpus fields"
        )
    for key in ("sources", "directed_testbench"):
        value = data[key]
        entries = value if isinstance(value, list) else [value]
        if not entries or not all(isinstance(entry, str) and entry for entry in entries):
            raise ValueError(f"{manifest_path}: {key!r} must be a non-empty string or list of strings")
    if not isinstance(data["directed_top"], str) or not data["directed_top"].startswith("peweaver_"):
        raise ValueError(f"{manifest_path}: directed_top must be a peweaver_-prefixed module name")
    return data


def run_regression(fixture: Path, verilator: str | None = None, timeout: float = 180.0) -> RegressionResult:
    fixture = fixture.resolve()
    started = time.monotonic()
    name = fixture.name
    tool = verilator or resolve_verilator()
    if tool is None:
        return RegressionResult(name, str(fixture), "tool_error", False, time.monotonic() - started,
                                None, [], [], "Verilator executable not found "
                                "(set PEWEAVER_VERILATOR, install oss-cad-suite, or add verilator to PATH).")
    try:
        manifest = load_fixture(fixture)
        testbench = (fixture / manifest["directed_testbench"]).resolve()
        if not testbench.is_file():
            raise ValueError(f"missing directed testbench: {testbench}")
        sources = [(fixture / entry).resolve() for entry in manifest["sources"]]
        missing = [str(path) for path in [*sources, testbench] if not path.is_file()]
        if missing:
            raise ValueError("Missing source file(s): " + ", ".join(missing))
        for vector in sorted((fixture / "vectors").glob("*.txt")):
            load_vector_file(vector)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return RegressionResult(name, str(fixture), "tool_error", False, time.monotonic() - started,
                                tool, [], [], str(exc))

    files = [*map(str, sources), str(testbench)]
    with tempfile.TemporaryDirectory(prefix=f"peweaver-{name}-") as temp_dir:
        build_dir = Path(temp_dir) / "obj_dir"
        compile_command = [tool, "--binary", "--timing", "--x-assign", "0", "--x-initial", "0",
                           "--top-module", str(manifest["directed_top"]), "--Mdir", str(build_dir),
                           "-Wno-fatal", *files]
        try:
            compiled = subprocess.run(compile_command, capture_output=True, text=True,
                                      timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return RegressionResult(name, str(fixture), "tool_error", False, time.monotonic() - started,
                                    tool, compile_command, [], str(exc))
        compile_log = (compiled.stdout or "") + ("\n" + compiled.stderr if compiled.stderr else "")
        binary = build_dir / f"V{manifest['directed_top']}"
        run_command = [str(binary)]
        if compiled.returncode != 0 or not binary.is_file():
            return RegressionResult(name, str(fixture), "compile_error", False, time.monotonic() - started,
                                    tool, compile_command, run_command, compile_log)
        try:
            # Run from the fixture directory so $readmemh("vectors/...") resolves.
            executed = subprocess.run(run_command, capture_output=True, text=True,
                                      timeout=timeout, check=False, cwd=str(fixture))
        except (OSError, subprocess.TimeoutExpired) as exc:
            return RegressionResult(name, str(fixture), "tool_error", False, time.monotonic() - started,
                                    tool, compile_command, run_command, compile_log + "\n" + str(exc))
        run_log = (executed.stdout or "") + ("\n" + executed.stderr if executed.stderr else "")
        passed = executed.returncode == 0 and PASS_MARKER in run_log
        status = "passed" if passed else "simulation_failed"
        return RegressionResult(name, str(fixture), status, passed, time.monotonic() - started, tool,
                                compile_command, run_command, compile_log + "\n" + run_log)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", nargs="?", type=Path, default=DEFAULT_FIXTURE,
                        help="reference fixture directory containing manifest.json (default: %(default)s)")
    parser.add_argument("--json", dest="json_path", type=Path)
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args(argv)
    if not args.fixture.is_dir():
        print(f"fft64_regression.py: fixture directory not found: {args.fixture}", file=sys.stderr)
        return 2
    result = run_regression(args.fixture, timeout=args.timeout)
    print(f"{result.name}: {result.status} ({'PASS' if result.passed else 'FAIL'}) "
          f"{result.duration_seconds:.3f}s")
    if not result.passed:
        print(result.log, file=sys.stderr)
    if args.json_path:
        args.json_path.write_text(json.dumps([result.json_dict()], indent=2), encoding="utf-8")
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
