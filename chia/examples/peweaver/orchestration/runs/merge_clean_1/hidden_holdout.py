#!/usr/bin/env python3
"""Hidden randomized holdout suite for the shared FFT candidate.

Controller-owned, model-free. Generates randomized and corner-case frames,
computes golden outputs with the INDEPENDENT oracles (which never consult
golden files), drives the candidate through a dedicated testbench that
asserts EXACT first-valid latency (71/137) and pulse width, and compares
every output bit-exact. Also validates its own sensitivity by re-running
the suite against deliberately corrupted candidates, which must fail.

Fail-closed: a timeout, missing marker, or comparison error is a failure.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fft64_oracle  # noqa: E402
import fft128_oracle  # noqa: E402

PWEAVER = Path(__file__).resolve().parents[1]
PHYSICAL = PWEAVER / "physical"
WRAPPER = PHYSICAL / "rtl" / "peweaver_ppa_shared_fft.v"
TB = PHYSICAL / "activity" / "hidden_holdout_tb.sv"

CORNERS = ("zeros", "plus_full", "minus_full", "alternate", "impulse", "ramp")


def _corner_frame(n: int, kind: str, rng) -> list[tuple[int, int]]:
    if kind == "zeros":
        return [(0, 0)] * n
    if kind == "plus_full":
        return [(0x7FFF, 0x7FFF)] * n
    if kind == "minus_full":
        return [(0x8000, 0x8000)] * n
    if kind == "alternate":
        return [((0x7FFF if k % 2 == 0 else 0x8000),
                 (0x8000 if k % 2 == 0 else 0x7FFF)) for k in range(n)]
    if kind == "impulse":
        frame = [(0, 0)] * n
        frame[0] = (0x7FFF, 0)
        return frame
    if kind == "ramp":
        return [(rng.randrange(65536), rng.randrange(65536)) for _ in range(n)]
    raise ValueError(kind)


def _random_frame(n: int, rng) -> list[tuple[int, int]]:
    return [(rng.randrange(65536), rng.randrange(65536)) for _ in range(n)]


def _write_vec(path: Path, frame: list[tuple[int, int]]) -> None:
    path.write_text("".join(f"{re:04x} {im:04x}\n" for re, im in frame))


def _oracle_frame(mode: int, samples: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if mode == 64:
        return fft64_oracle.run_frame(samples)
    return fft128_oracle.run_frame(samples)


def build_cases(n_frames_random: int = 6) -> list[dict]:
    """Deterministic case list; every value derives from the fixed seed."""
    rng = __import__("random").Random(0xC1A0C1A0)
    cases: list[dict] = []
    for mode in (64, 128):
        lat = 71 if mode == 64 else 137
        for kind in CORNERS:
            frame = _corner_frame(mode, kind, rng)
            cases.append({"case": "single", "mode": mode, "label": f"{kind}_{mode}",
                          "frames": [frame], "lat": lat})
        for i in range(n_frames_random):
            frame = _random_frame(mode, rng)
            cases.append({"case": "single", "mode": mode,
                          "label": f"random{i}_{mode}", "frames": [frame],
                          "lat": lat})
        for i in range(2):
            frames = [_random_frame(mode, rng) for _ in range(3)]
            cases.append({"case": "burst", "mode": mode,
                          "label": f"burst{i}_{mode}", "frames": frames,
                          "lat": lat})
        for i in range(2):
            frame = _random_frame(mode, rng)
            cases.append({"case": "abort_then_frame", "mode": mode,
                          "label": f"abort{i}_{mode}", "frames": [frame],
                          "lat": lat})
        frame = _random_frame(mode, rng)
        cases.append({"case": "midreset_then_frame", "mode": mode,
                      "label": f"midreset_{mode}", "frames": [frame], "lat": lat})
    for first, second in ((64, 128), (128, 64)):
        cases.append({
            "case": "switch_then_frame", "mode": first,
            "label": f"switch_{first}_to_{second}",
            "frames": [_random_frame(first, rng), _random_frame(second, rng)],
            "lat": 71 if first == 64 else 137,
            "second_lat": 71 if second == 64 else 137,
            "second_mode": second})
    return cases


def _run_sim(binary: Path, cwd: Path, vec_dir: Path, case: dict,
             out_path: Path, lat_override: int | None = None) -> tuple[bool, str]:
    mode = case["mode"]
    expect = lat_override if lat_override is not None else case["lat"]
    names = []
    for i, frame in enumerate(case["frames"]):
        name = f"{case['label']}_{i}.txt"
        _write_vec(vec_dir / name, frame)
        names.append(name)
    argv = [str(binary), f"+CASE={case['case']}", f"+N={mode}",
            f"+MODE={1 if mode == 128 else 0}", f"+EXPECT_LAT={expect}",
            f"+DIR={vec_dir}", f"+OUT={out_path}",
            f"+F0={names[0]}"]
    if len(names) > 1:
        argv.append(f"+F1={names[1]}")
    if len(names) > 2:
        argv.append(f"+F2={names[2]}")
    try:
        proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                              timeout=120)
    except subprocess.TimeoutExpired:
        return False, "sim timeout (120s)"
    log = (proc.stdout or "") + (proc.stderr or "")
    ok = "HIDDEN_DONE" in log and "HIDDEN_ERROR" not in log
    return ok, log


def _compare(case: dict, out_path: Path) -> tuple[bool, str]:
    captured = [line.split() for line in
                out_path.read_text().splitlines() if line.strip()]
    expected: list[tuple[int, int]] = []
    for frame in case["frames"]:
        expected.extend(_oracle_frame(case["mode"] if case["case"] != "switch_then_frame"
                                      else (case["mode"] if frame is case["frames"][0]
                                            else case["second_mode"]), frame))
    if len(captured) != len(expected):
        return False, f"captured {len(captured)} outputs, expected {len(expected)}"
    mismatches = 0
    for idx, (line, (re_e, im_e)) in enumerate(zip(captured, expected)):
        if len(line) != 2:
            return False, f"malformed capture line {idx}"
        re_g, im_g = int(line[0], 16), int(line[1], 16)
        if re_g != re_e or im_g != im_e:
            mismatches += 1
            if mismatches <= 4:
                print(f"  mismatch at emitted sample {idx}: "
                      f"got ({re_g:04x},{im_g:04x}) expected ({re_e:04x},{im_e:04x})")
    if mismatches:
        return False, f"{mismatches}/{len(expected)} mismatches"
    return True, "bit-exact"


def apply_mutation(candidate_text: str, mutation: str) -> str:
    if mutation == "twiddle_re5":
        m = re.search(r"assign wn_re\[\s*5\]\s*=\s*16'h([0-9A-Fa-f]{4});", candidate_text)
        if not m:
            raise RuntimeError("twiddle_re5 target not found")
        v = (int(m.group(1), 16) + 1) & 0xFFFF
        return candidate_text[:m.start(1)] + f"{v:04X}" + candidate_text[m.end(1):]
    if mutation == "twiddle_im5":
        m = re.search(r"assign wn_im\[\s*5\]\s*=\s*16'h([0-9A-Fa-f]{4});", candidate_text)
        if not m:
            raise RuntimeError("twiddle_im5 target not found")
        v = (int(m.group(1), 16) - 1) & 0xFFFF
        return candidate_text[:m.start(1)] + f"{v:04X}" + candidate_text[m.end(1):]
    if mutation == "scale_shift":
        if "arbr >>> (WIDTH-1)" not in candidate_text:
            raise RuntimeError("scale_shift target not found")
        return candidate_text.replace("arbr >>> (WIDTH-1)",
                                      "arbr >>> (WIDTH-2)", 1)
    if mutation == "counter_wrap":
        m = re.search(r"\(di_count == max_count\)", candidate_text)
        if not m:
            raise RuntimeError("counter_wrap target not found")
        return (candidate_text[:m.start()] + "(di_count == (max_count - 1))"
                + candidate_text[m.end():])
    raise ValueError(mutation)


def run_suite(candidate: Path, work: Path, *, lat_override: int | None = None,
              quick: bool = False) -> dict:
    work.mkdir(parents=True, exist_ok=True)
    vec_dir = work / "vectors"
    vec_dir.mkdir(exist_ok=True)
    verilator = shutil.which("verilator") or __import__("os").environ.get("PEWEAVER_VERILATOR")
    if not verilator:
        return {"passed": False, "status": "tool_error", "error": "verilator not found"}
    build = work / "obj"
    proc = subprocess.run(
        [verilator, "--binary", "--timing", "--x-assign", "0", "--x-initial", "0",
         "-Wno-fatal", "--top-module", "hidden_holdout_tb", "--Mdir", str(build),
         str(WRAPPER), str(candidate), str(TB)],
        cwd=PHYSICAL, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        return {"passed": False, "status": "compile_failed",
                "log": ((proc.stdout or "") + (proc.stderr or ""))[-4000:]}
    binary = build / "Vhidden_holdout_tb"
    cases = build_cases()
    if quick:
        cases = [c for c in cases if c["label"].startswith(
            ("zeros_", "random0_64", "random0_128", "burst0_"))]
    results = []
    for case in cases:
        out_path = work / f"cap_{case['label']}.txt"
        ok, log = _run_sim(binary, PHYSICAL, vec_dir, case, out_path,
                           lat_override=lat_override)
        if not ok:
            results.append({"label": case["label"], "passed": False,
                            "reason": log[-300:]})
            print(f"  [FAIL] {case['label']}: {log[-200:]}")
            continue
        ok_c, why = _compare(case, out_path)
        entry = {"label": case["label"], "passed": ok_c, "reason": why}
        if case["case"] == "abort_then_frame":
            m = re.search(r"HIDDEN_ABORT_PULSE (\d+)", log)
            entry["abort_garbage_output_cycles"] = int(m.group(1)) if m else -1
        results.append(entry)
        print(f"  [{'PASS' if ok_c else 'FAIL'}] {case['label']}: {why}"
              + (f" (abort pulse {entry['abort_garbage_output_cycles']} cycles)"
                 if "abort_garbage_output_cycles" in entry else ""))
    failed = [r for r in results if not r["passed"]]
    return {"passed": not failed, "cases": len(results),
            "failed": failed}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--sensitivity", action="store_true",
                        help="run the mutation sensitivity checks (each MUST fail)")
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()

    started = time.monotonic()
    suite = run_suite(args.candidate, args.work / "pristine", quick=args.quick)
    report: dict = {"candidate": str(args.candidate), "suite": suite}

    if args.sensitivity:
        mutations = {}
        text = args.candidate.read_text()
        for mut in ("twiddle_re5", "twiddle_im5", "scale_shift", "counter_wrap"):
            mdir = args.work / f"mut_{mut}"
            try:
                mutated = apply_mutation(text, mut)
            except RuntimeError as exc:
                mutations[mut] = {"applied": False, "error": str(exc)}
                continue
            cpath = mdir / "candidate.v"
            mdir.mkdir(parents=True, exist_ok=True)
            cpath.write_text(mutated)
            res = run_suite(cpath, mdir / "work", quick=True)
            mutations[mut] = {"applied": True, "suite_failed_as_expected":
                              not res["passed"],
                              "failed_cases": [f["label"] for f in res.get("failed", [])]}
            print(f"  mutation {mut}: failed_as_expected={not res['passed']}")
        report["sensitivity"] = mutations
        clean = suite["passed"] and all(
            m.get("suite_failed_as_expected") for m in mutations.values()
            if m.get("applied"))
        report["verdict"] = ("reproducible-pass-and-sensitive" if clean
                             else "NOT CREDIBLE")

    report["elapsed_seconds"] = round(time.monotonic() - started, 1)
    if args.json:
        print(json.dumps(report, indent=1))
    verdict = report.get("verdict", "PASS" if suite["passed"] else "FAIL")
    print(f"VERDICT: {verdict}")
    return 0 if verdict in ("PASS", "reproducible-pass-and-sensitive") else 1


if __name__ == "__main__":
    raise SystemExit(main())
