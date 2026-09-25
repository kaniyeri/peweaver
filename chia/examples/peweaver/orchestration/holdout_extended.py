#!/usr/bin/env python3
"""Extended rejudge of accepted candidates (Sol review items 1 and 5).

Fresh seed, new stress patterns (boundary / conjugate-symmetric / periodic /
complex tones), more randomized cases, and long continuous streams (4 and 16
frames) via a controller-owned stream testbench. Every output is compared
against the independent Python oracles; latency, pulse width, and gapless
emission are asserted in the testbench. Fail-closed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path

ORCH = Path(__file__).resolve().parent
PEW = ORCH.parent
sys.path.insert(0, str(PEW))
import fft64_oracle  # noqa: E402
import fft128_oracle  # noqa: E402
from hidden_holdout import (  # noqa: E402
    PHYSICAL, TB, WRAPPER, _oracle_frame, _write_vec,
)

RUNS = Path("/work/peweaver/runs")
REJUDGE_TB = ORCH / "sweep_scripts" / "rejudge_stream_tb.sv"
ICARUS_TB = ORCH / "sweep_scripts" / "rejudge_icarus_tb.sv"
OUT_DIR = RUNS / "rejudge_extended"
TOOLS = Path("/work/peweaver/toolchains/oss-cad-suite/bin")
VERILATOR = shutil.which("verilator") or str(TOOLS / "verilator")
IVERILOG = shutil.which("iverilog") or str(TOOLS / "iverilog")
VVP = shutil.which("vvp") or str(TOOLS / "vvp")


def _boundary_frame(n: int, rng: random.Random) -> list[tuple[int, int]]:
    vals = (0x7FFF, 0x8000, 0x0000, 0xFFFF, 0x0001, 0x8001, 0x7FFE, 0x8002)
    return [(rng.choice(vals), rng.choice(vals)) for _ in range(n)]


def _conj_frame(n: int, rng: random.Random) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = [(0, 0)] * n
    for k in range(1, n // 2):
        re = rng.randrange(65536)
        im = rng.randrange(65536)
        out[k] = (re, im)
        out[n - k] = (re, (-im) & 0xFFFF)
    out[0] = (rng.randrange(65536), 0)
    out[n // 2] = (rng.randrange(65536), 0)
    return out


def _periodic_frame(n: int, rng: random.Random, period: int) -> list[tuple[int, int]]:
    base = [(rng.randrange(65536), rng.randrange(65536)) for _ in range(period)]
    return [base[k % period] for k in range(n)]


def _tone_frame(n: int, bin_index: int) -> list[tuple[int, int]]:
    amp = int(0.45 * 32767)
    out = []
    for k in range(n):
        re = int(round(amp * math.cos(2 * math.pi * bin_index * k / n)))
        im = int(round(amp * math.sin(2 * math.pi * bin_index * k / n)))
        out.append((re & 0xFFFF, im & 0xFFFF))
    return out


def _random_frame(n: int, rng: random.Random) -> list[tuple[int, int]]:
    return [(rng.randrange(65536), rng.randrange(65536)) for _ in range(n)]


def build_cases(seed: int = 0x5EEDBEEF) -> list[dict]:
    rng = random.Random(seed)
    cases: list[dict] = []
    for mode in (64, 128):
        lat = 71 if mode == 64 else 137

        def add(case, label, frames, **extra):
            cases.append({"case": case, "mode": mode, "label": f"{label}_{mode}",
                          "frames": frames, "lat": lat, **extra})

        for kind, builder in (
            ("boundary", lambda: _boundary_frame(mode, rng)),
            ("conj", lambda: _conj_frame(mode, rng)),
            ("periodic4", lambda: _periodic_frame(mode, rng, mode // 4)),
            ("periodic8", lambda: _periodic_frame(mode, rng, mode // 8)),
            ("tone7", lambda: _tone_frame(mode, 7)),
            ("tone23", lambda: _tone_frame(mode, 23 % mode)),
            ("tone_nyq2", lambda: _tone_frame(mode, mode // 2)),
        ):
            add("single", kind, [builder()])
        for i in range(16):
            add("single", f"random{i}", [_random_frame(mode, rng)])
        for i in range(6):
            add("burst", f"burst{i}", [_random_frame(mode, rng) for _ in range(3)])
        for i in range(6):
            add("abort_then_frame", f"abort{i}", [_random_frame(mode, rng)])
        for i in range(3):
            add("midreset_then_frame", f"midreset{i}", [_random_frame(mode, rng)])
    for first, second in ((64, 128), (128, 64)):
        for i in range(4):
            cases.append({
                "case": "switch_then_frame", "mode": first,
                "label": f"switch{i}_{first}_to_{second}",
                "frames": [_random_frame(first, rng), _random_frame(second, rng)],
                "lat": 71 if first == 64 else 137,
                "second_lat": 71 if second == 64 else 137,
                "second_mode": second})
    for mode in (64, 128):
        for frames in (4, 16):
            lat = 71 if mode == 64 else 137
            stream = [_random_frame(mode, rng) for _ in range(frames)]
            cases.append({"case": "stream", "mode": mode,
                          "label": f"stream{frames}_{mode}",
                          "frames": stream, "lat": lat, "stream_frames": frames})
    return cases


def compile_tb(top: str, tb_path: Path, candidate: Path, build: Path) -> bool:
    build.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [VERILATOR, "--binary", "--timing", "--x-assign", "0", "--x-initial", "0",
         "-Wno-fatal", "--top-module", top, "--Mdir", str(build),
         str(WRAPPER), str(candidate), str(tb_path)],
        cwd=PHYSICAL, capture_output=True, text=True, timeout=600)
    return proc.returncode == 0


def run_case(binary: Path, case: dict, vec_dir: Path, out_path: Path) -> tuple[bool, str]:
    mode = case["mode"]
    names = []
    if case["case"] == "stream":
        stream = []
        for frame in case["frames"]:
            stream.extend(frame)
        name = f"{case['label']}.txt"
        _write_vec(vec_dir / name, stream)
        names = [name]
    else:
        for i, frame in enumerate(case["frames"]):
            name = f"{case['label']}_{i}.txt"
            _write_vec(vec_dir / name, frame)
            names.append(name)
    argv = [str(binary), f"+CASE={case['case']}", f"+N={mode}",
            f"+MODE={1 if mode == 128 else 0}", f"+EXPECT_LAT={case['lat']}",
            f"+DIR={vec_dir}", f"+OUT={out_path}", f"+F0={names[0]}"]
    if case["case"] == "stream":
        argv.append(f"+FRAMES={case['stream_frames']}")
    if len(names) > 1:
        argv.append(f"+F1={names[1]}")
    if len(names) > 2:
        argv.append(f"+F2={names[2]}")
    try:
        proc = subprocess.run(argv, cwd=PHYSICAL, capture_output=True,
                              text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return False, "sim timeout"
    log = (proc.stdout or "") + (proc.stderr or "")
    return ("HIDDEN_DONE" in log and "HIDDEN_ERROR" not in log), log


def compare(case: dict, out_path: Path) -> tuple[bool, str]:
    captured = [line.split() for line in out_path.read_text().splitlines()
                if line.strip()]
    expected: list[tuple[int, int]] = []
    for index, frame in enumerate(case["frames"]):
        if case["case"] == "switch_then_frame":
            mode = case["mode"] if index == 0 else case["second_mode"]
        else:
            mode = case["mode"]
        expected.extend(_oracle_frame(mode, frame))
    if len(captured) != len(expected):
        return False, f"captured {len(captured)} expected {len(expected)}"
    bad = 0
    for idx, (line, (re_e, im_e)) in enumerate(zip(captured, expected)):
        if len(line) != 2:
            return False, f"malformed line {idx}"
        if int(line[0], 16) != re_e or int(line[1], 16) != im_e:
            bad += 1
    return (bad == 0), (f"{bad}/{len(expected)} mismatches" if bad else "bit-exact")


def rejudge(candidate: Path, work: Path) -> dict:
    cases = build_cases()
    result = {"candidate": str(candidate),
              "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
              "cases": len(cases), "passed": 0, "failed": 0, "failures": []}
    work.mkdir(parents=True, exist_ok=True)
    build_main = work / "obj_main"
    build_stream = work / "obj_stream"
    if not compile_tb("hidden_holdout_tb", TB, candidate, build_main):
        result["compile_error"] = "main TB"
        return result
    if not compile_tb("rejudge_stream_tb", REJUDGE_TB, candidate, build_stream):
        result["compile_error"] = "stream TB"
        return result
    vec_dir = work / "vectors"
    vec_dir.mkdir(exist_ok=True)
    for case in cases:
        binary = (build_stream / "Vrejudge_stream_tb" if case["case"] == "stream"
                  else build_main / "Vhidden_holdout_tb")
        out_path = work / f"cap_{case['label']}.txt"
        ok, log = run_case(binary, case, vec_dir, out_path)
        if ok:
            ok, why = compare(case, out_path)
        else:
            why = log[-160:].replace("\n", " ")
        if ok:
            result["passed"] += 1
        else:
            result["failed"] += 1
            result["failures"].append({"case": case["label"], "why": why})
    return result


def icarus_rejudge(candidate: Path, work: Path, cases: list[dict]) -> dict:
    """Four-state (Icarus) pass over a deterministic subset of the case list."""
    build = work / "icarus"
    build.mkdir(parents=True, exist_ok=True)
    simv = build / "simv"
    proc = subprocess.run(
        [IVERILOG, "-g2012", "-o", str(simv), "-s", "rejudge_icarus_tb",
         str(WRAPPER), str(candidate), str(ICARUS_TB)],
        cwd=PHYSICAL, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        return {"icarus_compile_error": ((proc.stdout or "") + (proc.stderr or ""))[-300:]}
    subset = [c for c in cases if c["case"] == "single"][:12]
    subset += [c for c in cases if c["case"] == "stream"][:2]
    passed = failed = 0
    failures = []
    vec_dir = work / "vectors"
    vec_dir.mkdir(exist_ok=True)
    for case in subset:
        stream = []
        for frame in case["frames"]:
            stream.extend(frame)
        vec_path = (vec_dir / f"icarus_{case['label']}.txt").resolve()
        _write_vec(vec_path, stream)
        out_path = (work / f"icarus_cap_{case['label']}.txt").resolve()
        frames = case.get("stream_frames", 1)
        argv = [VVP, str(simv), f"+N={case['mode']}",
                f"+MODE={1 if case['mode'] == 128 else 0}",
                f"+EXPECT_LAT={case['lat']}", f"+FRAMES={frames}",
                f"+IN={vec_path}", f"+OUT={out_path}"]
        try:
            run = subprocess.run(argv, cwd=PHYSICAL, capture_output=True,
                                 text=True, timeout=300)
        except subprocess.TimeoutExpired:
            failed += 1
            failures.append({"case": case["label"], "why": "timeout"})
            continue
        log = (run.stdout or "") + (run.stderr or "")
        if "HIDDEN_DONE" in log and "HIDDEN_ERROR" not in log:
            ok, why = compare(case, out_path)
        else:
            ok, why = False, log[-160:].replace("\n", " ")
        if ok:
            passed += 1
        else:
            failed += 1
            failures.append({"case": case["label"], "why": why})
    return {"icarus_cases": len(subset), "icarus_passed": passed,
            "icarus_failed": failed, "icarus_failures": failures}


def accepted_candidates() -> list[Path]:
    candidates = []
    for prefix in ("msweep2-", "msweep3-", "msweep4-"):
        for run in sorted(RUNS.glob(f"{prefix}*")):
            summary = run / "artifacts" / "sweep_run_summary.json"
            candidate = run / "best" / "peweaver_shared_fft.v"
            if not summary.is_file() or not candidate.is_file():
                continue
            try:
                if json.loads(summary.read_text()).get("accepted"):
                    candidates.append(candidate)
            except json.JSONDecodeError:
                continue
    return candidates


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--only", default="")
    args = parser.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    candidates = accepted_candidates()
    if args.only:
        candidates = [c for c in candidates if args.only in str(c)]
    if args.limit:
        candidates = candidates[:args.limit]
    print(f"rejudge: {len(candidates)} accepted candidates", flush=True)
    results = []
    for candidate in candidates:
        run_name = candidate.parents[1].name
        work = OUT_DIR / run_name
        started = time.time()
        result = rejudge(candidate, work)
        if "compile_error" not in result:
            result.update(icarus_rejudge(candidate, work, build_cases()))
        result["run"] = run_name
        result["seconds"] = round(time.time() - started, 1)
        results.append(result)
        ok = (result["failed"] == 0 and "compile_error" not in result
              and "icarus_compile_error" not in result
              and result.get("icarus_failed", 0) == 0)
        status = "OK" if ok else f"FAIL({result.get('compile_error', 'checks')})"
        print(f"[{status}] {run_name} v:{result['passed']}/{result['cases']} "
              f"icarus:{result.get('icarus_passed', 0)}/"
              f"{result.get('icarus_cases', 0)} in {result['seconds']}s",
              flush=True)
        (OUT_DIR / "rejudge_results.json").write_text(
            json.dumps(results, indent=1))
    print(json.dumps({"candidates": len(results),
                      "all_pass": all(r["failed"] == 0
                                      and "compile_error" not in r
                                      and "icarus_compile_error" not in r
                                      and r.get("icarus_failed", 0) == 0
                                      for r in results)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
