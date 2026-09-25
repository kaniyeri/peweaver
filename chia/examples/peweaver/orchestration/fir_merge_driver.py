#!/usr/bin/env python3
"""FIR two-context merge driver: third-domain ChiaMerge demonstration.

Domain (astra-review suggested shape): two fixed-coefficient 8-tap FIR
filters with DIFFERENT pinned coefficients and mutually exclusive
activation. The sharing question is sharper than the MAC: arithmetic may
be shared (8 multipliers, not 16), but each context's history (delay line
+ output register) must remain independent across context switches.

Gate ladder (6): lint -> randomized oracle (1500 cycles, ctx changes only
while en=0, resets) -> directed corners (per-context impulse responses =
exact coefficient sequences, context alternation, reset) -> structure
(exactly 8 multipliers) -> area (below the two-reference synthesis sum)
-> formal-lite hold check is NOT included (stateful histories are covered
by the oracle's switch-heavy stimulus; formal stays a MAC-scoped tool).

Selftest controls: the naive 16-multiplier mux (must FAIL structure) and
a shared-delay-line cheater (must FAIL functional — histories corrupt).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import shutil
import sys
from pathlib import Path

from chia_merge import ChiaMerge, GateOutcome
from evaluator_nodes import (call_node, dispatch, lint_node, sim_node,
                             yosys_node, RetryableError)

PE = Path(__file__).resolve().parents[1]
DEPLOYED = Path("/work/peweaver/source/chia/examples/peweaver")
RUNS_BASE = Path("/work/peweaver/runs")
OSS = "/work/peweaver/toolchains/oss-cad-suite/bin"
CANDIDATE = "fir_shared.v"
BENCH = PE / "merge_benchmarks" / "fir_reference"

T = 8
CA = [16384, -8192, 4096, 2048, 1024, 512, 256, 128]
CB = [12288, -14336, 5325, 2662, 1331, 665, 333, 166]

INPUTS = {
    "fir_a.v": BENCH / "fir_a.v",
    "fir_b.v": BENCH / "fir_b.v",
}

CONTRACT = """INTERFACE
- One top module named fir_shared, parameter WIDTH=16, exactly these
  ports: input clock, reset (synchronous, active-high), ctx (0 = filter
  A, 1 = filter B), en; input signed x[15:0]; output signed y_a[39:0] and
  output signed y_b[39:0]. No other external signals.

BEHAVIORAL CONTRACT
- Two independent filter histories (A and B), each an 8-tap
  fixed-coefficient FIR with its reference's pinned coefficients:
  on an enabled edge, the ACTIVE context's delay line shifts in x
  (z[0] <= x, z[i] <= z[i-1]) and its output register updates to the raw
  40-bit wrapping sum of its 8 signed products sum C[i]*z[i]; the
  INACTIVE context's delay line and output register hold untouched.
- On a clock edge with reset=1: both delay lines cleared, both output
  registers cleared.
- On a clock edge with en=0: everything holds.
- ctx may change only while en=0. Each history must survive context
  switches exactly (two independent filters running on their own sample
  clocks).

SHARING OBJECTIVE
- The references' multipliers have CONSTANT coefficients, so duplicating
  them is expected; the shareable resources are the accumulation adder
  tree, accumulation registers, and control. A correct shared design
  therefore typically keeps the 16 constant-coefficient products but
  shares the 40-bit accumulation tree between contexts.
- Structural gate: no more than 16 multiplier cells (the two references
  combined).
- Area gate: synthesized cell count at least 10% below the two-reference
  sum. Per-context state (delay lines, output registers) must remain
  separate (the functional gate's switch-heavy stimulus enforces this).

FORBIDDEN: $readmem*, $fopen/system tasks, initial/final blocks, delays,
DPI/PLI, testbench constructs."""


def _s16(v: int) -> int:
    return v - 65536 if v >= 32768 else v


def _oracle_stream(stim) -> list:
    """Cycle-aligned (y_a, y_b) pairs for (ctx, en, x, rst) tuples."""
    za = [0] * T
    zb = [0] * T
    ya = 0
    yb = 0
    out = []
    M = 1 << 40
    for ctx, en, x, rst in stim:
        xs = _s16(x)
        if rst:
            za = [0] * T
            zb = [0] * T
            ya = 0
            yb = 0
        elif en:
            if ctx == 0:
                ya = sum(CA[i] * _s16(za[i]) for i in range(T)) % M
                za = [xs] + za[:T - 1]
            else:
                yb = sum(CB[i] * _s16(zb[i]) for i in range(T)) % M
                zb = [xs] + zb[:T - 1]
        out.append((ya, yb))
    return out


def _x_of(k: int) -> int:
    """The TB derives x from the cycle index (xs[15:0] of
    k*2654435761 mod 2^32); the oracle MUST use the same derivation."""
    return (k * 2654435761) & 0xFFFF


def _random_stim(cycles: int, seed: int) -> list:
    rng = random.Random(seed)
    stim = []
    ctx = 0
    pending = False
    for k in range(cycles):
        if rng.random() < 0.02:
            pending = True
        en = 0 if rng.random() < 0.08 else 1
        rst = 1 if k in (0, 1, 501, 502, 1003, 1004) else 0
        if pending and en == 0 and not rst:
            ctx ^= 1
            pending = False
        stim.append((ctx, en, _x_of(k), rst))
    stim.append((0, 0, 0, 1))
    stim.append((0, 1, 0x7FFF, 0))
    return stim


def _directed_stim() -> list:
    """Impulse response per context (must emit the exact coefficient
    sequence), context alternation with histories preserved, reset."""
    stim = [(0, 0, 0, 1), (0, 0, 0, 0)]  # reset, idle
    # impulse into context A: x=1 for one enabled edge, then zeros
    stim.append((0, 1, 1, 0))
    stim += [(0, 1, 0, 0)] * (T + 2)
    # switch (legal: en=0 gap), impulse into context B
    stim.append((1, 0, 0, 0))
    stim.append((1, 1, 1, 0))
    stim += [(1, 1, 0, 0)] * (T + 2)
    # alternate: two samples into A (history must have preserved)
    stim.append((0, 0, 0, 0))
    stim += [(0, 1, 100, 0), (0, 1, 200, 0)]
    stim.append((1, 0, 0, 0))
    # one sample into B (its impulse history continues)
    stim += [(1, 1, 50, 0)]
    stim.append((0, 0, 0, 0))
    # wrap stress: extreme samples both contexts
    stim += [(0, 1, 0x7FFF, 0), (1, 1, 0x8000, 0)]
    stim.append((0, 0, 0, 1))  # final reset
    stim.append((0, 1, 0x7FFF, 0))
    return stim


def _stim_files(stim, work: Path, tag: str):
    work.mkdir(parents=True, exist_ok=True)
    stim_path = work / f"stim_{tag}.txt"
    # $readmemh 3 bytes per line: ctl (bit0 ctx, bit1 en, bit2 rst), x_hi,
    # x_lo — x travels with the stimulus so directed values reach the DUT
    rows = []
    for ctx, en, x, rst in stim:
        ctl = (ctx & 1) | ((en & 1) << 1) | ((rst & 1) << 2)
        rows.append(f"{ctl:02x} {(x >> 8) & 0xFF:02x} {x & 0xFF:02x}")
    stim_path.write_text("\n".join(rows) + "\n")
    cap_path = work / f"cap_{tag}.txt"
    return stim_path, cap_path


def _judge(candidate: Path, stim, work: Path, tag: str) -> dict:
    verilator = shutil.which("verilator") or __import__("os").environ.get(
        "PEWEAVER_VERILATOR")
    if not verilator:
        return {"passed": False, "note": "verilator not found", "retry": True}
    tb = BENCH / "fir_holdout_tb.sv"
    stim_path, cap_path = _stim_files(stim, work, tag)
    build = work / f"obj_{tag}"
    try:
        build_r = call_node(
            sim_node, [verilator, "--binary", "--timing", "--x-assign", "0",
                       "--x-initial", "0", "-Wno-fatal", "--top-module",
                       "fir_holdout_tb", "--Mdir", str(build),
                       str(candidate), str(tb)], str(work))
        run_r = call_node(
            sim_node, [str(build / "Vfir_holdout_tb"), f"+STIM={stim_path}",
                       f"+OUT={cap_path}", f"+CYCLES={len(stim)}"],
            str(work))
    except RetryableError as exc:
        return {"passed": False, "note": str(exc), "retry": True}
    if not build_r["passed"]:
        return {"passed": False,
                "note": "compile failed: " + (build_r["note"])[-300:]}
    log = run_r["note"]
    if "FIR_DONE" not in log:
        return {"passed": False, "note": log[-300:]}
    words = cap_path.read_text().split()
    if len(words) != 2 * len(stim):
        return {"passed": False,
                "note": f"captured {len(words)} words, expected {2*len(stim)}"}
    expected = _oracle_stream(stim)
    mism = 0
    first = ""
    for i, (ya_e, yb_e) in enumerate(expected):
        ya_g = int(words[2 * i], 16)
        yb_g = int(words[2 * i + 1], 16)
        # 40-bit two's complement compare on BOTH sides (the oracle
        # returns mod-2^40 wrapped values)
        ya_g = ya_g - (1 << 40) if ya_g >= (1 << 39) else ya_g
        yb_g = yb_g - (1 << 40) if yb_g >= (1 << 39) else yb_g
        ya_e = ya_e - (1 << 40) if ya_e >= (1 << 39) else ya_e
        yb_e = yb_e - (1 << 40) if yb_e >= (1 << 39) else yb_e
        if ya_g != ya_e or yb_g != yb_e:
            mism += 1
            if not first:
                first = (f"cyc{i} ya {ya_g:x}/{ya_e:x} "
                         f"yb {yb_g:x}/{yb_e:x}")
    if mism:
        return {"passed": False,
                "note": f"{mism}/{len(stim)} mismatches; first: {first}"}
    return {"passed": True, "note": f"bit-exact over {len(stim)} cycles"}


def make_gate_ladder(run_root: Path):
    source = run_root / "source"
    bench = source / "merge_benchmarks" / "fir_reference"
    holder: dict = {}

    def g_lint(sandbox: Path) -> GateOutcome:
        cand = sandbox / CANDIDATE
        if not cand.is_file():
            return GateOutcome("lint", False, note=f"{CANDIDATE} missing")
        return dispatch(lint_node, cand.read_text(), "fir_shared",
                        ["clock", "reset", "ctx", "en", "x", "y_a", "y_b"],
                        name="lint")

    def g_functional(sandbox: Path) -> GateOutcome:
        cand = sandbox / CANDIDATE
        if not cand.is_file():
            return GateOutcome("functional", False, note="candidate missing")
        r = _judge(cand, _random_stim(1500, 0x0F1F2E3D),
                   run_root / "judge_work", "rand")
        return GateOutcome("functional", r["passed"], note=r["note"],
                           retry=r.get("retry", False))

    def g_corners(sandbox: Path) -> GateOutcome:
        cand = sandbox / CANDIDATE
        if not cand.is_file():
            return GateOutcome("corners", False, note="candidate missing")
        r = _judge(cand, _directed_stim(), run_root / "judge_work", "dir")
        return GateOutcome("corners", r["passed"], note=r["note"],
                           retry=r.get("retry", False))

    def _mult_count(text: str, top: str):
        work = run_root / "yosys_work"
        work.mkdir(parents=True, exist_ok=True)
        vfile = work / f"{top}.v"
        vfile.write_text(text)
        try:
            r = call_node(yosys_node,
                          f"read_verilog -sv {vfile}; hierarchy -top {top}; "
                          f"proc; opt -full; stat", oss_bin=OSS, timeout=300)
        except RetryableError:
            return None, 0, "yosys unavailable"
        rows = re.findall(r"^\s*(\d+)\s+\$(\w*mul\w*)\s*$", r["note"], re.M)
        if not r["passed"]:
            return False, 0, f"yosys could not elaborate {top}"
        return True, sum(int(n) for n, _ in rows), "ok"

    def g_structure(sandbox: Path) -> GateOutcome:
        cand = sandbox / CANDIDATE
        if not cand.is_file():
            return GateOutcome("structure", False, note="candidate missing")
        ok, n, note = _mult_count(cand.read_text(), "fir_shared")
        if ok is None:
            return GateOutcome("structure", False, note=note, retry=True)
        if not ok:
            return GateOutcome("structure", False, note=note)
        if n > 2 * T:
            return GateOutcome("structure", False,
                               note=f"expected at most {2 * T} multiplier "
                                    f"cells (references combined), found {n}")
        return GateOutcome("structure", True,
                           note=f"{n} multiplier cells <= {2 * T} combined "
                                f"reference count")

    def g_area(sandbox: Path) -> GateOutcome:
        cand = sandbox / CANDIDATE
        if not cand.is_file():
            return GateOutcome("area", False, note="candidate missing")
        cand_key = hashlib.sha256(cand.read_bytes()).hexdigest()
        if cand_key not in holder:
            work = run_root / "yosys_work"
            for name, text, top in (
                    ("cand", cand.read_text(), "fir_shared"),
                    ("refa", (bench / "fir_a.v").read_text(), "fir_a"),
                    ("refb", (bench / "fir_b.v").read_text(), "fir_b")):
                vfile = work / f"area_{name}.v"
                vfile.write_text(text)
                try:
                    r = call_node(yosys_node,
                                  f"read_verilog -sv {vfile}; "
                                  f"synth -top {top} -flatten; "
                                  f"stat", oss_bin=OSS, timeout=900)
                except RetryableError as exc:
                    return GateOutcome("area", False, note=str(exc),
                                       retry=True)
                m = re.search(r"^\s*(\d+)\s+cells\s*$", r["note"], re.M)
                if not r["passed"] or not m:
                    semantic = name == "cand"
                    return GateOutcome("area", False,
                                       note=f"yosys synth failed for {name}",
                                       retry=not semantic)
                holder[name] = int(m.group(1))
            holder["baseline"] = holder["refa"] + holder["refb"]
        floor = 0.90 * holder["baseline"]
        if not holder["cand"] < floor:
            return GateOutcome("area", False,
                               note=f"candidate cell count {holder['cand']} "
                                    f"not at least 10% below two-reference "
                                    f"sum {holder['baseline']} (floor "
                                    f"{floor:.0f})")
        red = 100 * (1 - holder["cand"] / holder["baseline"])
        return GateOutcome("area", True,
                           note=f"generic Yosys cell count {holder['cand']} = "
                                f"{red:.1f}% below the two-reference sum "
                                f"{holder['baseline']} (unweighted generic "
                                f"cell count, not mapped area)",
                           detail={"cand_cell_count": holder["cand"],
                                   "baseline_cell_count": holder["baseline"]})

    def g_hidden2(sandbox: Path) -> GateOutcome:
        """Second deterministic stimulus (different seed); same gates'
        judge — belt-and-braces inside the ladder."""
        cand = sandbox / CANDIDATE
        if not cand.is_file():
            return GateOutcome("hidden2", False, note="candidate missing")
        r = _judge(cand, _random_stim(1200, 0x5EEDF00D),
                   run_root / "judge_work", "h2")
        return GateOutcome("hidden2", r["passed"], note=r["note"],
                           retry=r.get("retry", False))

    return [g_lint, g_functional, g_corners, g_structure, g_area, g_hidden2]


SHARED_OK = (
    "module fir_shared #(parameter WIDTH = 16) (\n"
    "    input  wire clock, input wire reset, input wire ctx,\n"
    "    input wire en, input wire signed [15:0] x,\n"
    "    output reg signed [39:0] y_a, output reg signed [39:0] y_b);\n"
    "    localparam signed [15:0] CA0 = 16384;\n"
    "    localparam signed [15:0] CA1 = -8192;\n"
    "    localparam signed [15:0] CA2 = 4096;\n"
    "    localparam signed [15:0] CA3 = 2048;\n"
    "    localparam signed [15:0] CA4 = 1024;\n"
    "    localparam signed [15:0] CA5 = 512;\n"
    "    localparam signed [15:0] CA6 = 256;\n"
    "    localparam signed [15:0] CA7 = 128;\n"
    "    localparam signed [15:0] CB0 = 12288;\n"
    "    localparam signed [15:0] CB1 = -14336;\n"
    "    localparam signed [15:0] CB2 = 5325;\n"
    "    localparam signed [15:0] CB3 = 2662;\n"
    "    localparam signed [15:0] CB4 = 1331;\n"
    "    localparam signed [15:0] CB5 = 665;\n"
    "    localparam signed [15:0] CB6 = 333;\n"
    "    localparam signed [15:0] CB7 = 166;\n"
    "    reg signed [15:0] za [0:7];\n"
    "    reg signed [15:0] zb [0:7];\n"
    "    wire signed [31:0] pa0 = CA0 * za[0];\n"
    "    wire signed [31:0] pb0 = CB0 * zb[0];\n"
    "    wire signed [31:0] pa1 = CA1 * za[1];\n"
    "    wire signed [31:0] pb1 = CB1 * zb[1];\n"
    "    wire signed [31:0] pa2 = CA2 * za[2];\n"
    "    wire signed [31:0] pb2 = CB2 * zb[2];\n"
    "    wire signed [31:0] pa3 = CA3 * za[3];\n"
    "    wire signed [31:0] pb3 = CB3 * zb[3];\n"
    "    wire signed [31:0] pa4 = CA4 * za[4];\n"
    "    wire signed [31:0] pb4 = CB4 * zb[4];\n"
    "    wire signed [31:0] pa5 = CA5 * za[5];\n"
    "    wire signed [31:0] pb5 = CB5 * zb[5];\n"
    "    wire signed [31:0] pa6 = CA6 * za[6];\n"
    "    wire signed [31:0] pb6 = CB6 * zb[6];\n"
    "    wire signed [31:0] pa7 = CA7 * za[7];\n"
    "    wire signed [31:0] pb7 = CB7 * zb[7];\n"
    "    // SHARED accumulation tree: ctx-muxed sign-extended inputs\n"
    "    wire signed [39:0] s0 = ctx ? {{8{pb0[31]}}, pb0} : {{8{pa0[31]}}, pa0};\n"
    "    wire signed [39:0] s1 = ctx ? {{8{pb1[31]}}, pb1} : {{8{pa1[31]}}, pa1};\n"
    "    wire signed [39:0] s2 = ctx ? {{8{pb2[31]}}, pb2} : {{8{pa2[31]}}, pa2};\n"
    "    wire signed [39:0] s3 = ctx ? {{8{pb3[31]}}, pb3} : {{8{pa3[31]}}, pa3};\n"
    "    wire signed [39:0] s4 = ctx ? {{8{pb4[31]}}, pb4} : {{8{pa4[31]}}, pa4};\n"
    "    wire signed [39:0] s5 = ctx ? {{8{pb5[31]}}, pb5} : {{8{pa5[31]}}, pa5};\n"
    "    wire signed [39:0] s6 = ctx ? {{8{pb6[31]}}, pb6} : {{8{pa6[31]}}, pa6};\n"
    "    wire signed [39:0] s7 = ctx ? {{8{pb7[31]}}, pb7} : {{8{pa7[31]}}, pa7};\n"
    "    wire signed [39:0] acc = s0 + s1 + s2 + s3 + s4 + s5 + s6 + s7;\n"
    "    integer i;\n"
    "    always @(posedge clock) begin\n"
    "        if (reset) begin\n"
    "            for (i = 0; i < 8; i = i + 1) begin\n"
    "                za[i] <= 16'sd0; zb[i] <= 16'sd0; end\n"
    "            y_a <= 40'sd0; y_b <= 40'sd0;\n"
    "        end else if (en) begin\n"
    "            if (!ctx) begin\n"
    "                for (i = 7; i > 0; i = i - 1) za[i] <= za[i-1];\n"
    "                za[0] <= x;\n"
    "                y_a <= acc;\n"
    "            end else begin\n"
    "                for (i = 7; i > 0; i = i - 1) zb[i] <= zb[i-1];\n"
    "                zb[0] <= x;\n"
    "                y_b <= acc;\n"
    "            end\n"
    "        end\n"
    "    end\n"
    "endmodule\n"
)
NAIVE_16 = (
    "module fir_a(input wire clock, input wire reset, input wire en,\n"
    "             input wire signed [15:0] x,\n"
    "             output reg signed [39:0] y);\n"
    "    localparam signed [15:0] C0 = 16384;\n"
    "    localparam signed [15:0] C1 = -8192;\n"
    "    localparam signed [15:0] C2 = 4096;\n"
    "    localparam signed [15:0] C3 = 2048;\n"
    "    localparam signed [15:0] C4 = 1024;\n"
    "    localparam signed [15:0] C5 = 512;\n"
    "    localparam signed [15:0] C6 = 256;\n"
    "    localparam signed [15:0] C7 = 128;\n"
    "    reg signed [15:0] z [0:7];\n"
    "    wire signed [39:0] acc = C0*z[0] + C1*z[1] + C2*z[2] + C3*z[3] + C4*z[4] + C5*z[5] + C6*z[6] + C7*z[7];\n"
    "    integer i;\n"
    "    always @(posedge clock) begin\n"
    "        if (reset) begin\n"
    "            for (i = 0; i < 8; i = i + 1) z[i] <= 16'sd0;\n"
    "            y <= 40'sd0;\n"
    "        end else if (en) begin\n"
    "            for (i = 7; i > 0; i = i - 1) z[i] <= z[i-1];\n"
    "            z[0] <= x;\n"
    "            y <= acc;\n"
    "        end\n"
    "    end\n"
    "endmodule\n"
    "module fir_b(input wire clock, input wire reset, input wire en,\n"
    "             input wire signed [15:0] x,\n"
    "             output reg signed [39:0] y);\n"
    "    localparam signed [15:0] C0 = 12288;\n"
    "    localparam signed [15:0] C1 = -14336;\n"
    "    localparam signed [15:0] C2 = 5325;\n"
    "    localparam signed [15:0] C3 = 2662;\n"
    "    localparam signed [15:0] C4 = 1331;\n"
    "    localparam signed [15:0] C5 = 665;\n"
    "    localparam signed [15:0] C6 = 333;\n"
    "    localparam signed [15:0] C7 = 166;\n"
    "    reg signed [15:0] z [0:7];\n"
    "    wire signed [39:0] acc = C0*z[0] + C1*z[1] + C2*z[2] + C3*z[3] + C4*z[4] + C5*z[5] + C6*z[6] + C7*z[7];\n"
    "    integer i;\n"
    "    always @(posedge clock) begin\n"
    "        if (reset) begin\n"
    "            for (i = 0; i < 8; i = i + 1) z[i] <= 16'sd0;\n"
    "            y <= 40'sd0;\n"
    "        end else if (en) begin\n"
    "            for (i = 7; i > 0; i = i - 1) z[i] <= z[i-1];\n"
    "            z[0] <= x;\n"
    "            y <= acc;\n"
    "        end\n"
    "    end\n"
    "endmodule\n"
    "module fir_shared #(parameter WIDTH = 16) (\n"
    "    input wire clock, input wire reset, input wire ctx, input wire en,\n"
    "    input wire signed [15:0] x,\n"
    "    output wire signed [39:0] y_a, output wire signed [39:0] y_b);\n"
    "    wire signed [39:0] ya, yb;\n"
    "    fir_a ua(.clock(clock), .reset(reset), .en(en && !ctx), .x(x), .y(ya));\n"
    "    fir_b ub(.clock(clock), .reset(reset), .en(en && ctx), .x(x), .y(yb));\n"
    "    assign y_a = ya;\n"
    "    assign y_b = yb;\n"
    "endmodule\n")

CHEATER = SHARED_OK.replace(
    "                for (i = 7; i > 0; i = i - 1) zb[i] <= zb[i-1];\n",
    "                for (i = 7; i > 0; i = i - 1) zb[i] <= za[i-1];\n")


def selftest(run_root: Path) -> int:
    gates = make_gate_ladder(run_root)
    st = run_root.parent / f"{run_root.name}-selftest"
    st.mkdir(parents=True, exist_ok=True)
    report = {}
    for name, text in (("shared", SHARED_OK),
                       ("naive_16_mult", NAIVE_16),
                       ("shared_delay_cheater", CHEATER)):
        d = st / name
        d.mkdir(exist_ok=True)
        (d / CANDIDATE).write_text(text)
        outcomes = [g(d) for g in gates]
        report[name] = [{"gate": o.name, "passed": o.passed,
                         "retry": o.retry, "note": o.note[:90]}
                        for o in outcomes]
        report[name + "_all_pass"] = all(o.passed for o in outcomes)
    print(json.dumps(report, indent=1))
    valid = (report["shared_all_pass"]
             and not report["naive_16_mult_all_pass"]
             and not report["shared_delay_cheater_all_pass"])
    print(json.dumps({"selftest_valid": valid}))
    return 0 if valid else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--turns", type=int, default=16)
    ap.add_argument("--planner-model", default="openrouter/openai/gpt-5.6-sol")
    ap.add_argument("--worker-model", default="gemini/gemini-3.8-flash")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    run_root = RUNS_BASE / args.run_id
    source = run_root / "source"
    if not source.is_dir():
        shutil.copytree(DEPLOYED, source, symlinks=True)
    missing = [str(p) for p in INPUTS.values() if not p.is_file()]
    if missing:
        print(json.dumps({"error": "missing inputs", "missing": missing}))
        return 2

    gates = make_gate_ladder(run_root)
    if args.selftest:
        return selftest(run_root)

    state = ChiaMerge(
        run_id=args.run_id, run_base=RUNS_BASE, inputs=INPUTS,
        contract=CONTRACT, gates=gates, accept_level=len(gates),
        adviser_model=args.planner_model,
        implementer_model=args.worker_model,
        candidate_filename=CANDIDATE, turns=args.turns, resume=args.resume)
    print(json.dumps({"run_id": args.run_id, "accepted": state.accepted,
                      "best_level": state.best_level,
                      "turns": [h.get("status") for h in state.history]}))
    return 0 if state.accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
