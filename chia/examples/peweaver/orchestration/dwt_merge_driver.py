#!/usr/bin/env python3
"""DWT two-context merge driver: fourth-domain ChiaMerge demonstration.

Benchmark (frozen spec: campaigns/dwt_campaign/TIGHTENED_CAMPAIGN_SPEC.md):
two mutually exclusive, independently stateful streaming Q15 db2 DWT contexts
with 2:1 decimation. Context A is one decomposition level; context B is two
levels with a frozen level-2 schedule. The sharing question is whether one
db2 analysis bank can serve Context A level 1, Context B level 1, and Context B
level 2 while reproducing every exact cycle of the references.

Gate ladder (6, ordered, fail closed):
  1 lint/integrity -> 2 public randomized RTL oracle (1502 cycles, seed
  0xD17A5EED) -> 3 directed corners -> 4 normalized structure (<= 8
  multiplication operators after flattened proc/opt) -> 5 unweighted generic
  Yosys cell count strictly below 60% of the independently synthesized
  two-reference sum -> 6 controller-only synthesized-netlist holdout
  (1202 cycles, seed 0x7D17BEEF; generic Icarus + Yosys simcells).

Selftest controls: the model-free folded design must pass all six gates; the
naive two-reference wrapper must fail structure and generic-cell gates; the
shared-history cheater must fail functional gates. Ten mutations of the folded
control must each be caught by an intended gate.

No physical claim is made by this driver. Generic cell count is never area.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

from chia_merge import ChiaMerge, GateOutcome
from evaluator_nodes import (RetryableError, call_node, dispatch, lint_node,
                             sim_node, yosys_node)

import dwt_oracle as O

PE = Path(__file__).resolve().parents[1]
DEPLOYED = Path(os.environ.get(
    "PEWEAVER_DEPLOYED", "/work/peweaver/source/chia/examples/peweaver"))
RUNS_BASE = Path(os.environ.get("PEWEAVER_RUNS_BASE", "/work/peweaver/runs"))
OSS = os.environ.get("PEWEAVER_OSS_BIN", "/work/peweaver/toolchains/oss-cad-suite/bin")
CANDIDATE = "dwt_shared.v"
BENCH = PE / "merge_benchmarks" / "dwt_reference"

STRUCT_CAP = 8
AREA_RATIO = 0.60
TB = BENCH / "dwt_holdout_tb.sv"

PORTS = ["clock", "reset", "ctx", "en", "x",
         "a_l1_lo", "a_l1_hi", "a_l1_valid",
         "b_l1_lo", "b_l1_hi", "b_l1_valid",
         "b_l2_lo", "b_l2_hi", "b_l2_valid"]

INPUTS = {
    "dwt_a.v": BENCH / "dwt_a.v",
    "dwt_b.v": BENCH / "dwt_b.v",
}

CONTRACT = """INTERFACE
- One top module named dwt_shared, exactly these ports:
  input clock, reset (synchronous, active-high), ctx, en;
  input signed x[15:0];
  output signed a_l1_lo[39:0], a_l1_hi[39:0], output a_l1_valid;
  output signed b_l1_lo[39:0], b_l1_hi[39:0], output b_l1_valid;
  output signed b_l2_lo[39:0], b_l2_hi[39:0], output b_l2_valid.
- No other external signals. Valid outputs are single-cycle strobes; data
  outputs hold when not producing. reset=1 clears all state of both contexts.

CONTEXTS (mutually exclusive, independent state)
- ctx=0: Context A, ONE db2 decomposition level.
- ctx=1: Context B, TWO db2 decomposition levels.
- Only the active context accepts x on an enabled edge; the inactive context
  holds all history, phase, pending work, and data outputs.
- ctx may change only on an edge with reset=1 or en=0.

ARITHMETIC (identical for both contexts)
- Accepted samples are indexed from zero per context; samples with negative
  index are zero. The level-1 window is latest-first [x[n], x[n-1], x[n-2],
  x[n-3]]. Products are exact signed 16x16; the 40-bit result is the
  mathematical signed sum reduced modulo 2^40 (no rounding, no saturation).
- Pinned signed Q15 coefficients (literal constants; do not rescale):
  LOW  H = [ 15826,  27411,   7345,  -4240]
  HIGH G = [ -4240,  -7345,  27411, -15826]
- Level-1 output updates on accepted-sample index n odd, with l1_valid=1.
- Level-2 input is q(v) = signed16(v[30:15]) of the freshly computed B
  level-1 low result; it is pushed into B's latest-first level-2 window on
  every B level-1 pair. A level-2 job is created on B pair indices 1, 3, 5,
  ... and is consumed on the next B enabled sample with no level-1 output due
  (level-1 output updates are on odd accepted-sample indices). On that edge,
  l2_valid=1 and the level-2 result updates from the level-2 window as of
  that edge.
- Pending level-2 work and both contexts' phases survive en=0 and suspension.

SHARING OBJECTIVE
- The two references each instantiate a db2 analysis bank per level
  (one bank for A, two banks for B). A correct shared design may time-share
  arithmetic across A level 1, B level 1, and B level 2 while preserving every
  exact cycle of the contract above.
- Structural gate: at most 8 normalized multiplication operators after the
  frozen normalization pass.
- Generic-cell gate: strictly below 60% of the independently synthesized
  two-reference generic Yosys cell count (unweighted generic cell count, NOT
  mapped area).

FORBIDDEN: $readmem*, $system, $fopen and file I/O, initial/final blocks,
delays, force/release, DPI/PLI, testbench or hierarchical references outside
the candidate file."""


def _verilator() -> str | None:
    return shutil.which("verilator") or os.environ.get("PEWEAVER_VERILATOR")


def _iverilog() -> str | None:
    return shutil.which("iverilog") or os.environ.get("PEWEAVER_IVERILOG")


def _vvp() -> str | None:
    return shutil.which("vvp") or os.environ.get("PEWEAVER_VVP")


def _simcells() -> Path:
    explicit = os.environ.get("PEWEAVER_SIMCELLS")
    if explicit:
        return Path(explicit)
    yosys = os.environ.get("PEWEAVER_YOSYS")
    if yosys:
        return Path(yosys).resolve().parents[1] / "share" / "yosys" / "simcells.v"
    return Path(OSS).resolve().parents[0] / "share" / "yosys" / "simcells.v"


def _rtl_judge(candidate: Path, stim, work: Path, tag: str) -> dict:
    verilator = _verilator()
    if not verilator:
        return {"passed": False, "note": "verilator not found", "retry": True}
    stim_path, cap_path = O.stim_files(stim, work, tag)
    build = work / f"obj_{tag}"
    try:
        build_r = call_node(
            sim_node,
            [verilator, "--binary", "--timing", "--x-assign", "0",
             "--x-initial", "0", "-Wno-fatal", "--top-module",
             "dwt_holdout_tb", "--Mdir", str(build),
             str(candidate), str(TB)], str(work))
        run_r = call_node(
            sim_node,
            [str(build / "Vdwt_holdout_tb"), f"+STIM={stim_path}",
             f"+OUT={cap_path}", f"+CYCLES={len(stim)}"],
            str(work))
    except RetryableError as exc:
        return {"passed": False, "note": str(exc), "retry": True}
    if not build_r["passed"]:
        return {"passed": False,
                "note": "compile failed: " + (build_r["note"])[-300:]}
    log = run_r["note"]
    if "DWT_DONE" not in log:
        return {"passed": False, "note": log[-300:]}
    words = O.parse_capture(cap_path.read_text())
    if len(words) != len(stim):
        return {"passed": False,
                "note": f"captured {len(words)} cycles, expected {len(stim)}"}
    mism, first = O.compare(words, O.oracle_stream(stim))
    if mism:
        return {"passed": False,
                "note": f"{mism}/{len(stim)} mismatches; first: {first}"}
    return {"passed": True, "note": f"bit-exact over {len(stim)} cycles"}


def _netlist_judge(candidate_text: str, stim, work: Path, tag: str,
                   verbose: bool) -> dict:
    """Synthesize the candidate and run the holdout on the generic netlist."""
    iverilog = _iverilog()
    vvp = _vvp()
    simcells = _simcells()
    if not iverilog or not vvp:
        return {"passed": False, "note": "iverilog/vvp not found", "retry": True}
    if not simcells.is_file():
        return {"passed": False, "note": f"simcells missing: {simcells}",
                "retry": True}
    work.mkdir(parents=True, exist_ok=True)
    cand_path = work / f"holdout_cand_{tag}.v"
    cand_path.write_text(candidate_text)
    netlist = work / f"holdout_net_{tag}.v"
    try:
        syn_r = call_node(
            yosys_node,
            f"read_verilog -sv {cand_path}; synth -top dwt_shared -flatten; "
            f"write_verilog -noattr {netlist}", oss_bin=OSS, timeout=900)
        if not syn_r["passed"] or not netlist.is_file():
            return {"passed": False, "note": "netlist synthesis failed",
                    "retry": True}
        stim_path, cap_path = O.stim_files(stim, work, tag)
        sim = work / f"holdout_sim_{tag}"
        comp_r = call_node(
            sim_node,
            [iverilog, "-g2012", "-o", str(sim), str(netlist), str(TB),
             str(simcells)], str(work))
        if not comp_r["passed"]:
            return {"passed": False, "note": "netlist compile failed",
                    "retry": True}
        run_r = call_node(
            sim_node,
            [vvp, str(sim), f"+STIM={stim_path}", f"+OUT={cap_path}",
             f"+CYCLES={len(stim)}"], str(work))
    except RetryableError as exc:
        return {"passed": False, "note": str(exc), "retry": True}
    log = run_r["note"]
    if "DWT_DONE" not in log:
        return {"passed": False,
                "note": "controller-only synthesized-netlist holdout failed"}
    words = O.parse_capture(cap_path.read_text())
    mism, first = O.compare(words, O.oracle_stream(stim))
    if mism:
        note = ("controller-only synthesized-netlist holdout failed"
                if not verbose else
                f"{mism}/{len(stim)} mismatches; first: {first}")
        return {"passed": False, "note": note}
    return {"passed": True,
            "note": f"post-synthesis bit-exact over {len(stim)} cycles"}


def _stat_json(script: str, timeout: int = 900):
    """Run a Yosys script ending in `stat -json` and return its modules dict.

    Yosys emits escaped identifiers (for example ``\\dwt_shared``); keys are
    normalized by stripping the leading backslash. Parsing uses raw_decode
    because post-JSON log lines follow the object.
    """
    try:
        r = call_node(yosys_node, script, oss_bin=OSS, timeout=timeout)
    except RetryableError:
        return None
    if not r["passed"]:
        return None
    lines = r["note"].splitlines()
    starts = [i for i, line in enumerate(lines) if line.strip() == "{"]
    decoder = json.JSONDecoder()
    for s in sorted(starts, reverse=True):
        try:
            obj, _ = decoder.raw_decode("\n".join(lines[s:]))
        except Exception:
            continue
        mods = obj.get("modules")
        if isinstance(mods, dict):
            return {k.lstrip("\\"): v for k, v in mods.items()}
    return None


def _cells_and_muls(work: Path, text: str, top: str, tag: str):
    work.mkdir(parents=True, exist_ok=True)
    vfile = work / f"{tag}.v"
    vfile.write_text(text)
    area = _stat_json(
        f"read_verilog -sv {vfile}; synth -top {top} -flatten; stat -json")
    norm = _stat_json(
        f"read_verilog -sv {vfile}; hierarchy -check -top {top}; proc; "
        f"flatten; opt_expr; opt_clean; stat -json")
    if area is None or norm is None:
        return None
    if top in area and area[top].get("num_cells") is not None:
        cells = area[top]["num_cells"]
    else:
        cells = sum(m.get("num_cells", 0) for m in area.values())
    muls = 0
    if top in norm:
        for name, count in (norm[top].get("num_cells_by_type") or {}).items():
            if "mul" in name or "macc" in name:
                muls += count
    return {"cells": cells, "muls": muls}


def make_gate_ladder(run_root: Path):
    bench = run_root / "source" / "merge_benchmarks" / "dwt_reference"
    holder: dict = {}

    def _cand(sandbox: Path) -> Path | None:
        cand = sandbox / CANDIDATE
        return cand if cand.is_file() else None

    def g_lint(sandbox: Path) -> GateOutcome:
        cand = _cand(sandbox)
        if not cand:
            return GateOutcome("lint", False, note=f"{CANDIDATE} missing")
        return dispatch(lint_node, cand.read_text(), "dwt_shared", PORTS,
                        name="lint")

    def g_functional(sandbox: Path) -> GateOutcome:
        cand = _cand(sandbox)
        if not cand:
            return GateOutcome("functional", False, note="candidate missing")
        r = _rtl_judge(cand, O.random_stim(1502, O.PUBLIC_SEED),
                       run_root / "judge_work", "rand")
        return GateOutcome("functional", r["passed"], note=r["note"],
                           retry=r.get("retry", False))

    def g_corners(sandbox: Path) -> GateOutcome:
        cand = _cand(sandbox)
        if not cand:
            return GateOutcome("corners", False, note="candidate missing")
        r = _rtl_judge(cand, O.directed_stim(), run_root / "judge_work", "dir")
        return GateOutcome("corners", r["passed"], note=r["note"],
                           retry=r.get("retry", False))

    def g_structure(sandbox: Path) -> GateOutcome:
        cand = _cand(sandbox)
        if not cand:
            return GateOutcome("structure", False, note="candidate missing")
        key = hashlib.sha256(cand.read_bytes()).hexdigest()
        if key not in holder:
            r = _cells_and_muls(run_root / "yosys_work", cand.read_text(),
                                "dwt_shared", f"norm_{key[:12]}")
            if r is None:
                return GateOutcome("structure", False,
                                   note="yosys normalization failed",
                                   retry=True)
            holder[key] = r
        n = holder[key]["muls"]
        if n > STRUCT_CAP:
            return GateOutcome("structure", False,
                               note=f"{n} normalized multiplication "
                                    f"operators > {STRUCT_CAP}")
        return GateOutcome("structure", True,
                           note=f"{n} normalized multiplication operators "
                                f"<= {STRUCT_CAP}",
                           detail={"normalized_muls": n})

    def g_area(sandbox: Path) -> GateOutcome:
        cand = _cand(sandbox)
        if not cand:
            return GateOutcome("area", False, note="candidate missing")
        cand_key = hashlib.sha256(cand.read_bytes()).hexdigest()
        if cand_key not in holder:
            holder[cand_key] = _cells_and_muls(
                run_root / "yosys_work", cand.read_text(), "dwt_shared",
                f"area_{cand_key[:12]}")
        if holder[cand_key] is None:
            return GateOutcome("area", False, note="yosys synth failed for "
                                                   "candidate", retry=True)
        if "baseline" not in holder:
            refs = {}
            for name, fname in (("refa", "dwt_a.v"), ("refb", "dwt_b.v")):
                ref = bench / fname
                if not ref.is_file():
                    ref = BENCH / fname
                text = ref.read_text()
                r = _cells_and_muls(run_root / "yosys_work", text,
                                    fname.split(".")[0], f"baseline_{name}")
                if r is None:
                    return GateOutcome("area", False,
                                       note=f"yosys synth failed for {name}",
                                       retry=True)
                refs[name] = r["cells"]
            holder["baseline"] = refs["refa"] + refs["refb"]
            holder["refa"] = refs["refa"]
            holder["refb"] = refs["refb"]
        baseline = holder["baseline"]
        cand_cells = holder[cand_key]["cells"]
        floor = AREA_RATIO * baseline
        if not cand_cells < floor:
            return GateOutcome("area", False,
                               note=f"candidate generic cell count "
                                    f"{cand_cells} not below {AREA_RATIO:.0%} "
                                    f"of the two-reference sum {baseline} "
                                    f"(threshold {floor:.0f})")
        red = 100 * (1 - cand_cells / baseline)
        return GateOutcome(
            "area", True,
            note=f"generic Yosys cell count {cand_cells} = {red:.1f}% below "
                 f"the two-reference sum {baseline} (unweighted generic cell "
                 f"count, not mapped area)",
            detail={"cand_cell_count": cand_cells,
                    "baseline_cell_count": baseline,
                    "reduction_pct": round(red, 2)})

    def g_holdout(sandbox: Path) -> GateOutcome:
        cand = _cand(sandbox)
        if not cand:
            return GateOutcome("holdout", False, note="candidate missing")
        r = _netlist_judge(cand.read_text(),
                           O.random_stim(1202, O.HIDDEN_SEED),
                           run_root / "holdout_work", "hidden", verbose=False)
        return GateOutcome("holdout", r["passed"], note=r["note"],
                           retry=r.get("retry", False))

    return [g_lint, g_functional, g_corners, g_structure, g_area, g_holdout]


SHARED_FOLD = """// Model-free folded control: ONE db2 bank time-shared across the three jobs.
module dwt_shared (
    input  wire               clock,
    input  wire               reset,
    input  wire               ctx,
    input  wire               en,
    input  wire signed [15:0] x,
    output reg  signed [39:0] a_l1_lo,
    output reg  signed [39:0] a_l1_hi,
    output reg                a_l1_valid,
    output reg  signed [39:0] b_l1_lo,
    output reg  signed [39:0] b_l1_hi,
    output reg                b_l1_valid,
    output reg  signed [39:0] b_l2_lo,
    output reg  signed [39:0] b_l2_hi,
    output reg                b_l2_valid
);
    localparam signed [15:0] H0 = 15826;
    localparam signed [15:0] H1 = 27411;
    localparam signed [15:0] H2 = 7345;
    localparam signed [15:0] H3 = -4240;
    localparam signed [15:0] G0 = -4240;
    localparam signed [15:0] G1 = -7345;
    localparam signed [15:0] G2 = 27411;
    localparam signed [15:0] G3 = -15826;

    reg signed [15:0] wa0, wa1, wa2, wa3;
    reg signed [15:0] wb0, wb1, wb2, wb3;
    reg signed [15:0] wl0, wl1, wl2, wl3;
    reg pa, pb, mpar, pending;

    wire l2sel = ctx && !pb && pending;
    wire signed [15:0] s0 = l2sel ? wl0 : x;
    wire signed [15:0] s1 = l2sel ? wl1 : (ctx ? wb0 : wa0);
    wire signed [15:0] s2 = l2sel ? wl2 : (ctx ? wb1 : wa1);
    wire signed [15:0] s3 = l2sel ? wl3 : (ctx ? wb2 : wa2);
    wire signed [39:0] bank_lo = H0 * s0 + H1 * s1 + H2 * s2 + H3 * s3;
    wire signed [39:0] bank_hi = G0 * s0 + G1 * s1 + G2 * s2 + G3 * s3;
    wire signed [15:0] qn0 = bank_lo[30:15];

    always @(posedge clock) begin
        if (reset) begin
            wa0<=16'sd0; wa1<=16'sd0; wa2<=16'sd0; wa3<=16'sd0;
            wb0<=16'sd0; wb1<=16'sd0; wb2<=16'sd0; wb3<=16'sd0;
            wl0<=16'sd0; wl1<=16'sd0; wl2<=16'sd0; wl3<=16'sd0;
            a_l1_lo<=40'sd0; a_l1_hi<=40'sd0; a_l1_valid<=1'b0;
            b_l1_lo<=40'sd0; b_l1_hi<=40'sd0; b_l1_valid<=1'b0;
            b_l2_lo<=40'sd0; b_l2_hi<=40'sd0; b_l2_valid<=1'b0;
            pa<=1'b0; pb<=1'b0; mpar<=1'b0; pending<=1'b0;
        end else if (en) begin
            a_l1_valid <= 1'b0;
            b_l1_valid <= 1'b0;
            b_l2_valid <= 1'b0;
            if (!ctx) begin
                wa0 <= x; wa1 <= wa0; wa2 <= wa1; wa3 <= wa2;
                if (pa) begin
                    a_l1_lo <= bank_lo; a_l1_hi <= bank_hi;
                    a_l1_valid <= 1'b1;
                end
                pa <= ~pa;
            end else begin
                wb0 <= x; wb1 <= wb0; wb2 <= wb1; wb3 <= wb2;
                if (pb) begin
                    b_l1_lo <= bank_lo; b_l1_hi <= bank_hi;
                    b_l1_valid <= 1'b1;
                    wl3 <= wl2; wl2 <= wl1; wl1 <= wl0; wl0 <= qn0;
                    if (mpar) pending <= 1'b1;
                    mpar <= ~mpar;
                end else if (pending) begin
                    b_l2_lo <= bank_lo; b_l2_hi <= bank_hi;
                    b_l2_valid <= 1'b1;
                    pending <= 1'b0;
                end
                pb <= ~pb;
            end
        end else begin
            a_l1_valid <= 1'b0;
            b_l1_valid <= 1'b0;
            b_l2_valid <= 1'b0;
        end
    end
endmodule
"""

def _naive_control() -> str:
    ref_a = (BENCH / "dwt_a.v").read_text()
    ref_b = (BENCH / "dwt_b.v").read_text()
    wrapper = """// Negative control wrapper: both references instantiated in one file.
module dwt_shared (
    input  wire               clock,
    input  wire               reset,
    input  wire               ctx,
    input  wire               en,
    input  wire signed [15:0] x,
    output wire signed [39:0] a_l1_lo,
    output wire signed [39:0] a_l1_hi,
    output wire               a_l1_valid,
    output wire signed [39:0] b_l1_lo,
    output wire signed [39:0] b_l1_hi,
    output wire               b_l1_valid,
    output wire signed [39:0] b_l2_lo,
    output wire signed [39:0] b_l2_hi,
    output wire               b_l2_valid
);
    dwt_a ua (.clock(clock), .reset(reset), .en(en && !ctx), .x(x),
              .l1_lo(a_l1_lo), .l1_hi(a_l1_hi), .l1_valid(a_l1_valid));
    dwt_b ub (.clock(clock), .reset(reset), .en(en && ctx), .x(x),
              .l1_lo(b_l1_lo), .l1_hi(b_l1_hi), .l1_valid(b_l1_valid),
              .l2_lo(b_l2_lo), .l2_hi(b_l2_hi), .l2_valid(b_l2_valid));
endmodule
"""
    return ref_a + "\n" + ref_b + "\n" + wrapper


NAIVE_MUX = _naive_control()

CHEATER = """// Shared-history cheater control: one L1 window for both contexts.
module dwt_shared (
    input  wire               clock,
    input  wire               reset,
    input  wire               ctx,
    input  wire               en,
    input  wire signed [15:0] x,
    output reg  signed [39:0] a_l1_lo,
    output reg  signed [39:0] a_l1_hi,
    output reg                a_l1_valid,
    output reg  signed [39:0] b_l1_lo,
    output reg  signed [39:0] b_l1_hi,
    output reg                b_l1_valid,
    output reg  signed [39:0] b_l2_lo,
    output reg  signed [39:0] b_l2_hi,
    output reg                b_l2_valid
);
    localparam signed [15:0] H0 = 15826;
    localparam signed [15:0] H1 = 27411;
    localparam signed [15:0] H2 = 7345;
    localparam signed [15:0] H3 = -4240;
    localparam signed [15:0] G0 = -4240;
    localparam signed [15:0] G1 = -7345;
    localparam signed [15:0] G2 = 27411;
    localparam signed [15:0] G3 = -15826;

    reg signed [15:0] w0, w1, w2, w3;
    reg signed [15:0] wl0, wl1, wl2, wl3;
    reg pa, pb, mpar, pending;

    wire l2sel = ctx && !pb && pending;
    wire signed [15:0] s0 = l2sel ? wl0 : x;
    wire signed [15:0] s1 = l2sel ? wl1 : w0;
    wire signed [15:0] s2 = l2sel ? wl2 : w1;
    wire signed [15:0] s3 = l2sel ? wl3 : w2;
    wire signed [39:0] bank_lo = H0 * s0 + H1 * s1 + H2 * s2 + H3 * s3;
    wire signed [39:0] bank_hi = G0 * s0 + G1 * s1 + G2 * s2 + G3 * s3;
    wire signed [15:0] qn0 = bank_lo[30:15];

    always @(posedge clock) begin
        if (reset) begin
            w0<=0; w1<=0; w2<=0; w3<=0;
            wl0<=0; wl1<=0; wl2<=0; wl3<=0;
            a_l1_lo<=0; a_l1_hi<=0; a_l1_valid<=0;
            b_l1_lo<=0; b_l1_hi<=0; b_l1_valid<=0;
            b_l2_lo<=0; b_l2_hi<=0; b_l2_valid<=0;
            pa<=1'b0; pb<=1'b0; mpar<=1'b0; pending<=1'b0;
        end else if (en) begin
            a_l1_valid <= 1'b0;
            b_l1_valid <= 1'b0;
            b_l2_valid <= 1'b0;
            w0 <= x; w1 <= w0; w2 <= w1; w3 <= w2;
            if (!ctx) begin
                if (pa) begin
                    a_l1_lo <= bank_lo; a_l1_hi <= bank_hi; a_l1_valid <= 1'b1;
                end
                pa <= ~pa;
            end else begin
                if (pb) begin
                    b_l1_lo <= bank_lo; b_l1_hi <= bank_hi; b_l1_valid <= 1'b1;
                    wl3 <= wl2; wl2 <= wl1; wl1 <= wl0; wl0 <= qn0;
                    if (mpar) pending <= 1'b1;
                    mpar <= ~mpar;
                end else if (pending) begin
                    b_l2_lo <= bank_lo; b_l2_hi <= bank_hi; b_l2_valid <= 1'b1;
                    pending <= 1'b0;
                end
                pb <= ~pb;
            end
        end else begin
            a_l1_valid <= 1'b0;
            b_l1_valid <= 1'b0;
            b_l2_valid <= 1'b0;
        end
    end
endmodule
"""


def _mutations():
    """Ten deliberate corruptions of SHARED_FOLD with intended gates."""
    muts = []

    def add(name, text, gate, reason):
        muts.append({"name": name, "text": text, "gate": gate,
                     "reason": reason})

    add("coeff_sign",
        SHARED_FOLD.replace("localparam signed [15:0] H0 = 15826;",
                            "localparam signed [15:0] H0 = -15826;"),
        "functional+", "one low-band coefficient sign flipped")
    add("coeff_swap",
        SHARED_FOLD.replace("localparam signed [15:0] H1 = 27411;",
                            "localparam signed [15:0] H1 = 7345;")
                   .replace("localparam signed [15:0] H2 = 7345;",
                            "localparam signed [15:0] H2 = 27411;"),
        "functional+", "two coefficient positions swapped")
    add("parity_flip",
        SHARED_FOLD.replace("                if (pa) begin",
                            "                if (!pa) begin"),
        "functional+", "Context A output emitted on the opposite parity")
    add("trunc_slice",
        SHARED_FOLD.replace("wire signed [15:0] qn0 = bank_lo[30:15];",
                            "wire signed [15:0] qn0 = bank_lo[31:16];"),
        "corners", "level-2 truncation slice shifted by one bit")
    add("pending_on_disable",
        SHARED_FOLD.replace(
            "        end else begin\n            a_l1_valid <= 1'b0;\n"
            "            b_l1_valid <= 1'b0;\n"
            "            b_l2_valid <= 1'b0;\n        end",
            "        end else begin\n            a_l1_valid <= 1'b0;\n"
            "            b_l1_valid <= 1'b0;\n"
            "            b_l2_valid <= 1'b0;\n            pending <= 1'b0;\n"
            "        end"),
        "corners+", "pending level-2 job dropped while en=0")
    add("pending_on_switch",
        SHARED_FOLD.replace(
            "            if (!ctx) begin\n                wa0 <= x;",
            "            if (!ctx) begin\n                pending <= 1'b0;\n"
            "                wa0 <= x;"),
        "corners+", "pending level-2 job dropped on a Context-A edge")
    add("reset_one_context",
        SHARED_FOLD.replace("        if (reset) begin",
                            "        if (reset && !ctx) begin"),
        "functional+", "reset cleared only the selected context")
    add("phase_on_disable",
        SHARED_FOLD.replace(
            "        end else begin\n            a_l1_valid <= 1'b0;",
            "        end else begin\n            pa <= ~pa; pb <= ~pb;\n"
            "            a_l1_valid <= 1'b0;"),
        "functional+", "decimation phase advanced while en=0")
    add("shared_history",
        None, "corners+", "Context A and B level-1 history shared")
    add("valid_hold",
        SHARED_FOLD.replace(
            "            a_l1_valid <= 1'b0;\n            b_l1_valid <= 1'b0;\n"
            "            b_l2_valid <= 1'b0;\n            if (!ctx) begin",
            "            if (!ctx) begin"),
        "functional+", "valid strobes held instead of pulsing")

    fixed = []
    for m in muts:
        if m["name"] == "shared_history":
            m["text"] = CHEATER
        fixed.append(m)
    return fixed


def _write_controls(work: Path):
    work.mkdir(parents=True, exist_ok=True)
    for name, text in (("fold", SHARED_FOLD), ("naive", NAIVE_MUX),
                       ("cheater", CHEATER)):
        d = work / name
        d.mkdir(exist_ok=True)
        (d / CANDIDATE).write_text(text)


def selftest(run_root: Path) -> int:
    gates = make_gate_ladder(run_root)
    st = run_root.parent / f"{run_root.name}-selftest"
    st.mkdir(parents=True, exist_ok=True)
    _write_controls(st / "controls")
    report = {}
    for name in ("fold", "naive", "cheater"):
        d = st / "controls" / name
        outcomes = [g(d) for g in gates]
        report[name] = [{"gate": o.name, "passed": o.passed, "retry": o.retry,
                         "note": o.note[:120], "detail": o.detail}
                        for o in outcomes]
        report[name + "_all_pass"] = all(o.passed for o in outcomes)
    mut_report = []
    mut_work = st / "mutations"
    for mut in _mutations():
        if mut["text"] == SHARED_FOLD:
            raise SystemExit(f"mutation {mut['name']} did not change the "
                             f"base RTL")
        d = mut_work / mut["name"]
        d.mkdir(parents=True, exist_ok=True)
        (d / CANDIDATE).write_text(mut["text"])
        gate = mut["gate"]
        names = []
        if gate.startswith("functional"):
            r = _rtl_judge(d / CANDIDATE, O.random_stim(1502, O.PUBLIC_SEED),
                           run_root / "judge_work", f"mut_{mut['name']}")
            names.append(("functional", r["passed"], r["note"]))
        if gate.startswith("corners") or gate.startswith("functional+"):
            r = _rtl_judge(d / CANDIDATE, O.directed_stim(),
                           run_root / "judge_work", f"mutd_{mut['name']}")
            names.append(("corners", r["passed"], r["note"]))
        detected = any(not passed for _, passed, _ in names)
        mut_report.append({"name": mut["name"], "reason": mut["reason"],
                           "intended_gate": mut["gate"],
                           "results": [{"gate": g, "passed": p, "note": n[:120]}
                                       for g, p, n in names],
                           "detected": detected})
    ok_muts = all(m["detected"] for m in mut_report)
    naive = {r["gate"]: r["passed"] for r in report["naive"]}
    cheater = {r["gate"]: r["passed"] for r in report["cheater"]}
    expectations = {
        "fold_all_pass": report["fold_all_pass"],
        "naive_functional_ok": bool(naive.get("functional")),
        "naive_corners_ok": bool(naive.get("corners")),
        "naive_structure_rejected": not naive.get("structure", True),
        "naive_area_rejected": not naive.get("area", True),
        "cheater_functional_rejected": not cheater.get("functional", True),
        "cheater_corners_rejected": not cheater.get("corners", True),
        "mutations_all_detected": ok_muts,
    }
    valid = all(expectations.values())
    print(json.dumps({"controls": report, "mutations": mut_report,
                      "expectations": expectations,
                      "mutations_all_detected": ok_muts,
                      "selftest_valid": valid}, indent=1))
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
        if not DEPLOYED.is_dir():
            print(json.dumps({"error": "deployed source missing",
                              "deployed": str(DEPLOYED)}))
            return 2
        shutil.copytree(DEPLOYED, source, symlinks=True)
    missing = [str(p) for p in INPUTS.values() if not p.is_file()]
    if not TB.is_file():
        missing.append(str(TB))
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
