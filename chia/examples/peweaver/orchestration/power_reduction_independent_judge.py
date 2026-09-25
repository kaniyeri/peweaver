#!/usr/bin/env python3
"""Independent controller-owned judge for the preliminary power fixtures.

This judge intentionally does not import ``power_reduction_domains.py`` or
the merge-driver oracles.  It owns fresh stimuli, reference models, and
testbenches, then checks both frozen mapped netlists independently.

The judge is evidence qualification only.  It does not make a PEWeaver merge
or physical signoff claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import subprocess
from pathlib import Path


MOD40 = 1 << 40
MASK40 = MOD40 - 1
COEF_H = (15826, 27411, 7345, -4240)
COEF_G = (-4240, -7345, 27411, -15826)
FIR_A = (16384, -8192, 4096, 2048, 1024, 512, 256, 128)
FIR_B = (12288, -14336, 5325, 2662, 1331, 665, 333, 166)


def s8(value: int) -> int:
    return value - 256 if value & 0x80 else value


def s16(value: int) -> int:
    if -32768 <= value <= 32767:
        return value
    value &= 0xFFFF
    return value - 65536 if value & 0x8000 else value


def dot40(window: list[int], coeffs: tuple[int, ...]) -> int:
    return sum(coeffs[i] * s16(window[i]) for i in range(len(coeffs))) & MASK40


def mac_model(stim: list[tuple[int, int, int, int, int]]) -> list[int]:
    acc = 0
    out = 0
    expected = []
    for mode, en, a, b, reset in stim:
        if reset:
            acc = 0
            out = 0
        elif en:
            product = s8(a) * s8(b)
            if mode == 0:
                acc = (acc + product) & 0xFFFF
                out = acc
            else:
                out = product & 0xFFFF
        expected.append(out)
    return expected


def fir_model(stim: list[tuple[int, int, int, int]]) -> list[tuple[int, int]]:
    za = [0] * 8
    zb = [0] * 8
    ya = yb = 0
    expected = []
    for ctx, en, x, reset in stim:
        if reset:
            za = [0] * 8
            zb = [0] * 8
            ya = yb = 0
        elif en:
            if ctx == 0:
                ya = sum(FIR_A[i] * s16(za[i]) for i in range(8)) & MASK40
                za = [s16(x)] + za[:7]
            else:
                yb = sum(FIR_B[i] * s16(zb[i]) for i in range(8)) & MASK40
                zb = [s16(x)] + zb[:7]
        expected.append((ya, yb))
    return expected


def q16(value: int) -> int:
    field = (value & MASK40) >> 15 & 0xFFFF
    return s16(field)


def dwt_model(stim: list[tuple[int, int, int, int]]) -> list[tuple[int, ...]]:
    wa = [0, 0, 0, 0]
    wb = [0, 0, 0, 0]
    wl = [0, 0, 0, 0]
    pa = pb = mpar = 0
    pending = False
    a_lo = a_hi = b_lo = b_hi = l2_lo = l2_hi = 0
    expected = []
    for ctx, en, x, reset in stim:
        va = vb = vl = 0
        if reset:
            wa = [0, 0, 0, 0]
            wb = [0, 0, 0, 0]
            wl = [0, 0, 0, 0]
            pa = pb = mpar = 0
            pending = False
            a_lo = a_hi = b_lo = b_hi = l2_lo = l2_hi = 0
        elif en:
            sample = s16(x)
            if ctx == 0:
                wa = [sample, wa[0], wa[1], wa[2]]
                if pa:
                    a_lo = dot40(wa, COEF_H)
                    a_hi = dot40(wa, COEF_G)
                    va = 1
                pa ^= 1
            else:
                wb = [sample, wb[0], wb[1], wb[2]]
                if pb:
                    b_lo = dot40(wb, COEF_H)
                    b_hi = dot40(wb, COEF_G)
                    vb = 1
                    wl = [q16(b_lo), wl[0], wl[1], wl[2]]
                    if mpar:
                        pending = True
                    mpar ^= 1
                elif pending:
                    l2_lo = dot40(wl, COEF_H)
                    l2_hi = dot40(wl, COEF_G)
                    vl = 1
                    pending = False
                pb ^= 1
        expected.append((a_lo, a_hi, va, b_lo, b_hi, vb,
                         l2_lo, l2_hi, vl))
    return expected


def random_stim(domain: str, cycles: int, seed: int):
    rng = random.Random(seed)
    state = 0
    pending = False
    stim = []
    reset_cycles = {0, 1, cycles // 2, cycles // 2 + 1, cycles - 3}
    for cycle in range(cycles):
        reset = int(cycle in reset_cycles)
        en = int(rng.random() >= 0.20)
        if rng.random() < 0.08:
            pending = True
        if pending and not en and not reset:
            state ^= 1
            pending = False
        if domain == "mac":
            stim.append((state, en, rng.randrange(256), rng.randrange(256), reset))
        else:
            stim.append((state, en, rng.randrange(1 << 16), reset))
    return stim


def directed_stim(domain: str):
    if domain == "mac":
        stim = [(0, 0, 0, 0, 1), (0, 0, 0, 0, 0)]
        for a, b in ((0x80, 0x01), (0x80, 0x80), (0x7F, 0x80),
                     (0xFF, 0xFF), (0x7F, 0x7F)):
            stim.append((0, 1, a, b, 0))
        stim.append((1, 0, 0, 0, 0))
        for a, b in ((0x7F, 0x02), (0x80, 0x80), (0x01, 0x7F)):
            stim.append((1, 1, a, b, 0))
        stim.extend((0, 1, 0x40, 0x40, 0) for _ in range(20))
        stim.append((0, 0, 0, 0, 1))
        stim.append((0, 1, 0x7F, 0x02, 0))
        return stim
    if domain == "fir":
        stim = [(0, 0, 0, 1), (0, 0, 0, 0)]
        stim.append((0, 1, 1, 0))
        stim.extend((0, 1, 0, 0) for _ in range(10))
        stim.append((1, 0, 0, 0))
        stim.append((1, 1, 1, 0))
        stim.extend((1, 1, 0, 0) for _ in range(10))
        stim.extend((0, 1, 0x7FFF, 0) for _ in range(4))
        stim.extend((1, 1, 0x8000, 0) for _ in range(4))
        stim.append((0, 0, 0, 1))
        return stim
    stim = [(0, 0, 0, 1), (0, 0, 0, 0)]
    stim.extend((0, 1, x, 0) for x in (1, 1, 0, 0, 0, 0))
    stim.append((1, 0, 0, 0))
    stim.extend((1, 1, x, 0) for x in (1, 0, 0, 0, 0, 0, 0, 0))
    stim.extend((1, 0, 0, 0) for _ in range(3))
    stim.extend((1, 1, x, 0) for x in (0x7FFF, 0x8000, 0, 0))
    stim.append((0, 0, 0, 1))
    return stim


TB = {
    "mac": r'''`timescale 1ns/1ps
module independent_mac_tb;
  reg clock = 0, reset = 0, mode = 0, en = 0;
  reg [7:0] a = 0, b = 0;
  wire [15:0] y;
  reg [7:0] mem [0:8191];
  integer k, fd;
  always #5 clock = ~clock;
  shared_mac dut(.clock(clock), .reset(reset), .mode(mode), .en(en),
                 .a(a), .b(b), .y(y));
  initial begin
    $readmemh("stim.hex", mem);
    fd = $fopen("cap.txt", "w");
    for (k = 0; k < CYCLES; k = k + 1) begin
      mode = mem[5*k]; en = mem[5*k+1]; a = mem[5*k+2];
      b = mem[5*k+3]; reset = mem[5*k+4];
      @(posedge clock); @(negedge clock); $fwrite(fd, "%04h\n", y);
    end
    $fclose(fd); $finish;
  end
endmodule
''',
    "fir": r'''`timescale 1ns/1ps
module independent_fir_tb;
  reg clock = 0, reset = 0, ctx = 0, en = 0;
  reg signed [15:0] x = 0;
  wire signed [39:0] y_a, y_b;
  reg [7:0] mem [0:8191];
  integer k, fd;
  always #5 clock = ~clock;
  fir_shared dut(.clock(clock), .reset(reset), .ctx(ctx), .en(en), .x(x),
                 .y_a(y_a), .y_b(y_b));
  initial begin
    $readmemh("stim.hex", mem);
    fd = $fopen("cap.txt", "w");
    for (k = 0; k < CYCLES; k = k + 1) begin
      ctx = mem[5*k]; en = mem[5*k+1];
      x = {mem[5*k+2], mem[5*k+3]}; reset = mem[5*k+4];
      @(posedge clock); @(negedge clock);
      $fwrite(fd, "%010h %010h\n", y_a, y_b);
    end
    $fclose(fd); $finish;
  end
endmodule
''',
    "dwt": r'''`timescale 1ns/1ps
module independent_dwt_tb;
  reg clock = 0, reset = 0, ctx = 0, en = 0;
  reg signed [15:0] x = 0;
  wire signed [39:0] a_l1_lo, a_l1_hi, b_l1_lo, b_l1_hi, b_l2_lo, b_l2_hi;
  wire a_l1_valid, b_l1_valid, b_l2_valid;
  reg [7:0] mem [0:8191];
  integer k, fd;
  always #5 clock = ~clock;
  dwt_shared dut(.clock(clock), .reset(reset), .ctx(ctx), .en(en), .x(x),
    .a_l1_lo(a_l1_lo), .a_l1_hi(a_l1_hi), .a_l1_valid(a_l1_valid),
    .b_l1_lo(b_l1_lo), .b_l1_hi(b_l1_hi), .b_l1_valid(b_l1_valid),
    .b_l2_lo(b_l2_lo), .b_l2_hi(b_l2_hi), .b_l2_valid(b_l2_valid));
  initial begin
    $readmemh("stim.hex", mem);
    fd = $fopen("cap.txt", "w");
    for (k = 0; k < CYCLES; k = k + 1) begin
      ctx = mem[5*k]; en = mem[5*k+1];
      x = {mem[5*k+2], mem[5*k+3]}; reset = mem[5*k+4];
      @(posedge clock); @(negedge clock);
      $fwrite(fd, "%010h %010h %0d %010h %010h %0d %010h %010h %0d\n",
        a_l1_lo, a_l1_hi, a_l1_valid, b_l1_lo, b_l1_hi, b_l1_valid,
        b_l2_lo, b_l2_hi, b_l2_valid);
    end
    $fclose(fd); $finish;
  end
endmodule
''',
}


def write_stimulus(domain: str, stim: list, path: Path) -> None:
    rows = []
    for item in stim:
        if domain == "mac":
            mode, en, a, b, reset = item
            rows.extend((mode, en, a, b, reset))
        else:
            ctx, en, x, reset = item
            rows.extend((ctx, en, (x >> 8) & 0xFF, x & 0xFF, reset))
    path.write_text("\n".join(f"{value:02x}" for value in rows) + "\n")


def compile_and_run(candidate: Path, domain: str, stim: list,
                    expected: list, work: Path, oss: Path,
                    prim: Path, cells: Path) -> dict:
    work.mkdir(parents=True, exist_ok=True)
    (work / "tb.sv").write_text(TB[domain].replace("CYCLES", str(len(stim))))
    write_stimulus(domain, stim, work / "stim.hex")
    sim = work / "sim.vvp"
    env = dict(os.environ)
    env["PATH"] = str(oss) + os.pathsep + env.get("PATH", "")
    compile_cmd = ["iverilog", "-g2012", "-DFUNCTIONAL", "-DUNIT_DELAY=#1",
                   str(prim), str(cells), str(candidate), "tb.sv", "-o", str(sim)]
    try:
        compiled = subprocess.run(compile_cmd, cwd=work, env=env,
                                  capture_output=True, text=True, timeout=300)
        if compiled.returncode != 0:
            return {"passed": False, "stage": "compile",
                    "note": (compiled.stdout + compiled.stderr)[-2000:]}
        ran = subprocess.run(["vvp", str(sim)], cwd=work, env=env,
                             capture_output=True, text=True, timeout=300)
        if ran.returncode != 0:
            return {"passed": False, "stage": "simulate",
                    "note": (ran.stdout + ran.stderr)[-2000:]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"passed": False, "stage": "infrastructure", "note": str(exc)}

    lines = (work / "cap.txt").read_text().splitlines()
    try:
        if domain == "mac":
            got = [int(line, 16) for line in lines]
        elif domain == "fir":
            got = [tuple(int(x, 16) for x in line.split()) for line in lines]
        else:
            got = []
            for line in lines:
                fields = line.split()
                if len(fields) != 9:
                    raise ValueError(f"expected 9 DWT fields, got {len(fields)}")
                got.append(tuple(int(x, 16) if i not in (2, 5, 8)
                                else int(x) for i, x in enumerate(fields)))
    except (ValueError, IndexError) as exc:
        return {"passed": False, "stage": "parse", "note": str(exc)}

    if len(got) != len(expected):
        return {"passed": False, "stage": "compare",
                "note": f"captured {len(got)} cycles, expected {len(expected)}"}
    for index, (actual, want) in enumerate(zip(got, expected)):
        if actual != want:
            return {"passed": False, "stage": "compare",
                    "note": f"cycle {index}: got {actual!r}, expected {want!r}"}
    return {"passed": True, "cycles": len(expected)}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path,
                        default=Path("/work/peweaver/runs/chia_power_reduction"))
    parser.add_argument("--work", type=Path,
                        default=None)
    parser.add_argument("--cycles", type=int, default=1502)
    args = parser.parse_args()
    root = args.root.resolve()
    work_root = (args.work or root / "independent_judge").resolve()
    oss = Path(os.environ.get("PEWEAVER_OSS_BIN",
                             "/work/peweaver/toolchains/oss-cad-suite/bin"))
    prim = Path(os.environ.get("PEWEAVER_PRIM_V",
                              "/work/peweaver/toolchains/.volare/sky130A/libs.ref/sky130_fd_sc_hd/verilog/primitives.v"))
    cells = Path(os.environ.get("PEWEAVER_CELL_V",
                               "/work/peweaver/toolchains/.volare/sky130A/libs.ref/sky130_fd_sc_hd/verilog/sky130_fd_sc_hd.v"))
    if not shutil.which("iverilog", path=str(oss)):
        print(json.dumps({"passed": False, "retry": True,
                          "note": "iverilog not found"}, indent=2))
        return 2
    for path in (prim, cells):
        if not path.is_file():
            print(json.dumps({"passed": False, "retry": True,
                              "note": f"missing simulation library: {path}"}, indent=2))
            return 2

    specs = {
        "mac": ("shared_mac", root / "mac" / "mac_base_sky130.v",
                root / "mac" / "mac_opt_sky130.v", mac_model, 0xA64C0DE1),
        "fir": ("fir_shared", root / "fir" / "fir_base_sky130.v",
                root / "fir" / "fir_opt_sky130.v", fir_model, 0xF1A5EED1),
        "dwt": ("dwt_shared", root / "dwt" / "dwt_base_sky130.v",
                root / "dwt" / "dwt_opt_sky130.v", dwt_model, 0xD07C0DE1),
    }
    results = {"passed": True, "cycles": args.cycles, "domains": {},
               "inputs": {}}
    for domain, (_, baseline, optimized, model, seed) in specs.items():
        if not baseline.is_file() or not optimized.is_file():
            results["passed"] = False
            results["domains"][domain] = {"passed": False,
                                            "note": "mapped artifact missing"}
            continue
        results["inputs"][domain] = {
            "baseline": {"path": str(baseline), "sha256": sha256(baseline)},
            "optimized": {"path": str(optimized), "sha256": sha256(optimized)},
        }
        scenarios = [("random", random_stim(domain, args.cycles, seed)),
                     ("directed", directed_stim(domain))]
        domain_result = {"passed": True, "scenarios": {}}
        for scenario, stim in scenarios:
            expected = model(stim)
            scenario_result = {}
            for label, candidate in (("baseline", baseline),
                                     ("optimized", optimized)):
                outcome = compile_and_run(
                    candidate, domain, stim, expected,
                    work_root / domain / scenario / label,
                    oss, prim, cells)
                scenario_result[label] = outcome
                if not outcome.get("passed"):
                    domain_result["passed"] = False
                    results["passed"] = False
            domain_result["scenarios"][scenario] = scenario_result
        results["domains"][domain] = domain_result

    work_root.mkdir(parents=True, exist_ok=True)
    result_path = work_root / "independent_judge.json"
    result_path.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0 if results["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
