#!/usr/bin/env python3
"""MAC merge driver: second-domain demonstration of the ChiaMerge primitives.

Identical composition to the FFT driver — one ChiaMerge call over the
domain-neutral primitives — with MAC-specific inputs, contract, and gates:

    lint -> functional (randomized vectors vs pure-python oracle)
         -> structure (exactly ONE 8x8 multiplier in the candidate)
         -> area (synthesized area strictly below the two-reference sum)

The negative control is the structure+equivalence pair: a candidate that
keeps two multipliers fails the structure gate; a "shared" candidate that
breaks either lane's arithmetic fails the randomized oracle judge.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import random
import subprocess
import sys
from pathlib import Path

from chia_merge import ChiaMerge, GateOutcome
from evaluator_nodes import (call_node, dispatch, lint_node, sim_node,
                             yosys_node, RetryableError)

PE = Path(__file__).resolve().parents[1]
DEPLOYED = Path("/work/peweaver/source/chia/examples/peweaver")
RUNS_BASE = Path("/work/peweaver/runs")
CANDIDATE = "shared_mac.v"
OSS = "/work/peweaver/toolchains/oss-cad-suite/bin"

INPUTS = {
    "mac_a.v": PE / "merge_benchmarks" / "mac_reference" / "mac_a.v",
    "mac_b.v": PE / "merge_benchmarks" / "mac_reference" / "mac_b.v",
}

CONTRACT = """INTERFACE
- One top module named shared_mac with exactly these ports:
  input clock, reset (synchronous, active-high), mode (0 = accumulating
  lane, 1 = product lane), en, a[7:0], b[7:0]; output y[15:0].
  No other external signals.

BEHAVIORAL CONTRACT
- All words are two's complement: a and b are signed 8-bit, y is signed
  16-bit (raw 16-bit wrapping).
- On a clock edge with reset=1: internal accumulator and y are cleared.
- On a clock edge with reset=0 and en=1:
  mode=0: y <= (accumulator + a*b) mod 2^16 and the accumulator takes the
          same value (running sum of all mode-0 products since reset).
  mode=1: y <= (a*b) mod 2^16; the accumulator is unchanged.
- On a clock edge with en=0: y and the accumulator hold.
- The product is the exact signed 8x8 product; no rounding or saturation.
- mode may change only while en=0 (mutually exclusive lanes); the design
  must hold state across mode changes and never mix lanes within a cycle.

SHARING OBJECTIVE
- Exactly ONE 8x8 multiplier structure in the design (the two input designs
  each contain one; a merged design with two is rejected).
- Synthesized area strictly below the sum of the two input designs.

FORBIDDEN: $readmem*, $fopen/system tasks, initial/final blocks, delays,
DPI/PLI, testbench constructs."""

ANTI_CHEAT = (
    (re.compile(r"\$system\b|\$readmem(?:h|b)?\b", re.I), "system or readmem I/O"),
    (re.compile(r"\$(?:fopen|fread|fwrite|fscanf|fclose)\b", re.I), "file I/O"),
    (re.compile(r"\b(?:DPI|PLI)\b|import\s+\"DPI-C\"", re.I), "DPI/PLI"),
    (re.compile(r"\$test\$plusargs\b", re.I), "plusargs"),
    (re.compile(r"\b(?:initial|final)\b", re.I), "initial/final block"),
)


def _oracle_stream(stim: list[tuple[int, int, int, int]]) -> list[int]:
    """Cycle-aligned expected y for (mode, en, a, b, reset) stimulus tuples."""
    out: list[int] = []
    acc = 0
    y = 0
    for mode, en, a, b, rst in stim:
        if rst:
            acc = 0
            y = 0
        elif en:
            p = (a - 256 if a >= 128 else a) * (b - 256 if b >= 128 else b)
            if mode == 0:
                acc = (acc + p) & 0xFFFF
                y = acc
            else:
                y = p & 0xFFFF
        out.append(y)
    return out


def make_mac_judge(candidate_path: Path, work: Path) -> dict:
    """Compile a fresh Verilator sim and compare the candidate against the
    oracle on randomized stimulus with resets, en gaps, and mode switches."""
    verilator = shutil.which("verilator") or os.environ.get("PEWEAVER_VERILATOR")
    if not verilator:
        return {"passed": False, "note": "verilator not found", "retry": True}
    tb = PE / "merge_benchmarks" / "mac_reference" / "mac_holdout_tb.sv"
    rng = random.Random(0x5ACED1CE)
    stim: list[tuple[int, int, int, int]] = []
    mode = 0
    pending_toggle = False
    prev_en = 0
    for k in range(1200):
        if k % 211 == 0:
            pending_toggle = True
        en = 0 if (k % 97) < 7 else 1
        rst = 1 if k in (0, 1, 403, 404) else 0
        # contract: mode may change only while en=0 (Sol review fix)
        if pending_toggle and prev_en == 0 and not rst:
            mode ^= 1
            pending_toggle = False
        prev_en = en
        stim.append((mode, en, rng.randrange(256), rng.randrange(256), rst))
    work.mkdir(parents=True, exist_ok=True)
    stim_path = work / "stim.txt"
    stim_path.write_text("".join(
        f"{(mode & 1) | ((en & 1) << 1):02x} {a:02x} {b:02x} {rst:02x}\n"
        for mode, en, a, b, rst in stim))
    cap_path = work / "cap.txt"
    build = work / "obj"
    try:
        build_r = call_node(
            sim_node, [verilator, "--binary", "--timing", "--x-assign", "0",
                       "--x-initial", "0", "-Wno-fatal", "--top-module",
                       "mac_holdout_tb", "--Mdir", str(build),
                       str(candidate_path), str(tb)], str(work))
        run_r = call_node(
            sim_node, [str(build / "Vmac_holdout_tb"), f"+STIM={stim_path}",
                       f"+OUT={cap_path}", "+CYCLES=1200"], str(work))
    except RetryableError as exc:
        return {"passed": False, "note": str(exc), "retry": True}
    if not build_r["passed"]:
        return {"passed": False,
                "note": "compile failed: " + (build_r["note"])[-300:]}
    log = run_r["note"]
    if "MAC_DONE" not in log:
        return {"passed": False, "note": log[-300:]}
    got = [int(w, 16) for w in cap_path.read_text().split()]
    expected = _oracle_stream(stim)
    if len(got) != len(expected):
        return {"passed": False,
                "note": f"captured {len(got)} cycles, expected {len(expected)}"}
    mism = [(i, g, e) for i, (g, e) in enumerate(zip(got, expected)) if g != e]
    if mism:
        first = mism[:3]
        return {"passed": False,
                "note": f"{len(mism)}/{len(expected)} mismatches; first: "
                        + "; ".join(f"cyc{i} got {g:04x} exp {e:04x}"
                                    for i, g, e in first)}
    return {"passed": True, "note": f"bit-exact over {len(expected)} cycles"}


def _directed_stim() -> list:
    """Fixed directed stimulus: signed corners, wrap, repeated accumulation,
    mode-1 interruption, reset (plan section 8, required deterministic gate 3)."""
    rng = random.Random(0xD1CEC0DE)
    stim = []
    for a, b in ((0x00, 0x00), (0x01, 0x00), (0x80, 0x01), (0x80, 0x80),
                 (0x7F, 0x80), (0x7F, 0x7F), (0xFF, 0xFF), (0x80, 0xFF)):
        stim.append((0, 1, a, b, 1 if not stim else 0))
    for a, b in [(0x7F, 0x7F)] * 8 + [(0x80, 0x80)] * 8 + [(0xFF, 0xFF)] * 4:
        stim.append((0, 1, a, b, 0))
    stim.append((1, 0, 0x12, 0x34, 0))
    for a, b in ((0x7F, 0x02), (0x80, 0x80), (0x01, 0x7F)):
        stim.append((1, 1, a, b, 0))
    stim.append((0, 0, 0x55, 0x2C, 0))
    for a, b in ((0x40, 0x40), (0xC0, 0x3F)):
        stim.append((0, 1, a, b, 0))
    # en gaps and random padding; mode changes only while en=0 (contract)
    mode = 0
    for _ in range(120):
        en = 1 if rng.random() < 0.8 else 0
        if rng.random() < 0.15 and en == 0:
            mode ^= 1
        stim.append((mode, en, rng.randrange(256),
                     rng.randrange(256), 0))
    stim.append((0, 0, 0, 0, 1))
    stim.append((0, 1, 0x7F, 0x02, 0))
    return stim


def make_mac_directed_judge(candidate_path: Path, work: Path) -> dict:
    """Directed signed-corner judge; same TB and oracle as the randomized
    judge but with the fixed corner stimulus."""
    verilator = shutil.which("verilator") or os.environ.get("PEWEAVER_VERILATOR")
    if not verilator:
        return {"passed": False, "note": "verilator not found", "retry": True}
    tb = PE / "merge_benchmarks" / "mac_reference" / "mac_holdout_tb.sv"
    stim = _directed_stim()
    work.mkdir(parents=True, exist_ok=True)
    stim_path = work / "stim_directed.txt"
    stim_path.write_text("".join(
        f"{(mode & 1) | ((en & 1) << 1):02x} {a:02x} {b:02x} {rst:02x}\n"
        for mode, en, a, b, rst in stim))
    cap_path = work / "cap_directed.txt"
    build = work / "obj_directed"
    try:
        build_r = call_node(
            sim_node, [verilator, "--binary", "--timing", "--x-assign", "0",
                       "--x-initial", "0", "-Wno-fatal", "--top-module",
                       "mac_holdout_tb", "--Mdir", str(build),
                       str(candidate_path), str(tb)], str(work))
        run_r = call_node(
            sim_node, [str(build / "Vmac_holdout_tb"), f"+STIM={stim_path}",
                       f"+OUT={cap_path}", f"+CYCLES={len(stim)}"], str(work))
    except RetryableError as exc:
        return {"passed": False, "note": str(exc), "retry": True}
    if not build_r["passed"]:
        return {"passed": False,
                "note": "compile failed: " + (build_r["note"])[-300:]}
    log = run_r["note"]
    if "MAC_DONE" not in log:
        return {"passed": False, "note": log[-300:]}
    got = [int(w, 16) for w in cap_path.read_text().split()]
    expected = _oracle_stream(stim)
    if len(got) != len(expected):
        return {"passed": False,
                "note": f"captured {len(got)} cycles, expected {len(expected)}"}
    mism = [(i, g, e) for i, (g, e) in enumerate(zip(got, expected)) if g != e]
    if mism:
        first = mism[:3]
        return {"passed": False,
                "note": f"{len(mism)}/{len(expected)} corner mismatches; first: "
                        + "; ".join(f"cyc{i} got {g:04x} exp {e:04x}"
                                    for i, g, e in first)}
    return {"passed": True,
            "note": f"bit-exact on {len(expected)} directed corner cycles"}


SBY = "sby"
FORMAL_DIR = Path(__file__).resolve().parent / "formal"
FORMAL_HARNESS = FORMAL_DIR / "mac_formal_top.sv"


def run_mac_formal(candidate_path: Path, work: Path) -> dict:
    """Bounded SymbiYosys proof of the MAC sequential contract with symbolic
    operands. The harness and the controller-hashed candidate are copied into
    the isolated work dir; missing tooling -> retryable."""
    sby = shutil.which(SBY)
    if not sby:
        return {"passed": False, "note": "sby not found", "retry": True}
    if not FORMAL_HARNESS.is_file():
        return {"passed": False, "note": "formal harness missing"}
    work.mkdir(parents=True, exist_ok=True)
    sby_file = work / "mac_formal.sby"
    sby_file.write_text(
        "[options]\nmode bmc\ndepth 12\n\n"
        "[engines]\nsmtbmc z3\n\n"
        "[script]\nread -formal mac_formal_top.sv\n"
        "read -formal shared_mac.v\nprep -top mac_formal_top\n\n"
        "[files]\n"
        f"{FORMAL_HARNESS}\n{candidate_path}\n")
    try:
        r = call_node(sim_node, [sby, "-f", "-d", str(work / "sby"),
                                 str(sby_file)], str(work), timeout=1800)
    except RetryableError as exc:
        return {"passed": False, "note": str(exc), "retry": True}
    log = r["note"]
    if r["rc"] != 0 and "DONE (PASS" in log:
        return {"passed": False, "note": "sby nonzero rc despite PASS marker",
                "retry": True}
    if "DONE (PASS" in log:
        verdict = "PASS"
    elif "DONE (FAIL" in log or "FAILED" in log or "Unreached cover" in log:
        verdict = "FAIL"
    elif "ERROR" in log or r["rc"] != 0:
        return {"passed": False, "note": "sby error: " + log[-250:],
                "retry": True}
    else:
        verdict = None
    if verdict is None:
        return {"passed": False, "note": "sby status unknown: " + log[-250:]}
    return {"passed": verdict == "PASS",
            "note": f"formal (BMC depth 12, BOUNDED) {verdict}: sequential "
                    f"contract with symbolic operands under declared protocol "
                    f"assumptions"}


def make_gate_ladder(run_root: Path):
    source = run_root / "source"
    bench = source / "merge_benchmarks" / "mac_reference"
    holder: dict = {}

    def g_lint(sandbox: Path) -> GateOutcome:
        cand = sandbox / CANDIDATE
        if not cand.is_file():
            return GateOutcome("lint", False, note=f"{CANDIDATE} missing")
        return dispatch(lint_node, cand.read_text(), "shared_mac",
                        ["clock", "reset", "mode", "en", "a", "b", "y"],
                        name="lint")

    def g_functional(sandbox: Path) -> GateOutcome:
        cand = sandbox / CANDIDATE
        if not cand.is_file():
            return GateOutcome("functional", False, note="candidate missing")
        r = make_mac_judge(cand, run_root / "judge_work")
        return GateOutcome("functional", r["passed"], note=r["note"],
                           retry=r.get("retry", False))

    def g_corners(sandbox: Path) -> GateOutcome:
        cand = sandbox / CANDIDATE
        if not cand.is_file():
            return GateOutcome("corners", False, note="candidate missing")
        r = make_mac_directed_judge(cand, run_root / "judge_work")
        return GateOutcome("corners", r["passed"], note=r["note"],
                           retry=r.get("retry", False))

    def g_formal(sandbox: Path) -> GateOutcome:
        cand = sandbox / CANDIDATE
        if not cand.is_file():
            return GateOutcome("formal", False, note="candidate missing")
        r = run_mac_formal(cand, run_root / "formal_work")
        return GateOutcome("formal", r["passed"], note=r["note"],
                           retry=r.get("retry", False))

    def _mult_count(text: str, top: str) -> tuple:
        work = run_root / "yosys_work"
        work.mkdir(parents=True, exist_ok=True)
        vfile = work / f"{top}.v"
        vfile.write_text(text)
        try:
            r = call_node(yosys_node,
                          f"read_verilog {vfile}; hierarchy -top {top}; "
                          f"proc; opt -full; stat", oss_bin=OSS, timeout=300)
        except RetryableError:
            return None, 0, "yosys unavailable"
        m = re.findall(r"^\s*(\d+)\s+\$(\w*mul\w*)\s*$", r["note"], re.M)
        if not r["passed"]:
            return False, 0, f"yosys could not elaborate {top}"
        return True, sum(int(n) for n, _ in m), "ok"

    def g_structure(sandbox: Path) -> GateOutcome:
        cand = sandbox / CANDIDATE
        if not cand.is_file():
            return GateOutcome("structure", False, note="candidate missing")
        ok, n, note = _mult_count(cand.read_text(), "shared_mac")
        if ok is None:
            return GateOutcome("structure", False, note=note, retry=True)
        if not ok:
            return GateOutcome("structure", False, note=note)
        if n != 1:
            return GateOutcome(
                "structure", False,
                note=f"expected exactly 1 multiplier, found {n}")
        return GateOutcome("structure", True, note="exactly one multiplier")

    def g_area(sandbox: Path) -> GateOutcome:
        cand = sandbox / CANDIDATE
        if not cand.is_file():
            return GateOutcome("area", False, note="candidate missing")
        import hashlib
        cand_key = hashlib.sha256(cand.read_bytes()).hexdigest()
        if cand_key not in holder:
            work = run_root / "yosys_work"
            refs_a = (bench / "mac_a.v").read_text()
            refs_b = (bench / "mac_b.v").read_text()
            areas = {}
            for name, text, top in (("cand", cand.read_text(), "shared_mac"),
                                    ("refa", refs_a, "mac_a"),
                                    ("refb", refs_b, "mac_b")):
                vfile = work / f"area_{name}.v"
                vfile.write_text(text)
                try:
                    r = call_node(yosys_node,
                                  f"read_verilog {vfile}; synth -top {top}; "
                                  f"stat", oss_bin=OSS, timeout=600)
                except RetryableError as exc:
                    return GateOutcome("area", False, note=str(exc),
                                       retry=True)
                m = re.search(r"^\s*(\d+)\s+cells\s*$", r["note"], re.M)
                if not r["passed"] or not m:
                    semantic = name == "cand"
                    return GateOutcome("area", False,
                                       note=f"yosys synth failed for {name}",
                                       retry=not semantic)
                areas[name] = float(m.group(1))
            holder[cand_key] = areas["cand"]
            if "baseline" not in holder:
                holder["baseline"] = areas["refa"] + areas["refb"]
        cand_area = holder[cand_key]
        baseline = holder["baseline"]
        if not cand_area < baseline:
            return GateOutcome(
                "area", False,
                note=f"candidate generic cell count {cand_area:.0f} not below "
                     f"two-reference sum {baseline:.0f}")
        red = 100 * (1 - cand_area / baseline)
        return GateOutcome(
            "area", True,
            note=f"generic Yosys cell count {cand_area:.0f} = {red:.1f}% below "
                 f"the two-reference sum {baseline:.0f} (unweighted generic "
                 f"cell count, not mapped area)",
            detail={"cand_cell_count": cand_area,
                    "baseline_cell_count": baseline})

    return [g_lint, g_functional, g_corners, g_structure, g_area, g_formal]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--turns", type=int, default=16)
    parser.add_argument("--planner-model", default="openrouter/openai/gpt-5.6-sol")
    parser.add_argument("--worker-model", default="openrouter/google/gemini-3.8-flash")
    parser.add_argument("--selftest", action="store_true",
                        help="run the gate ladder against a reference mux and exit")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

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
        st = run_root.parent / f"{args.run_id}-selftest"
        st.mkdir(parents=True, exist_ok=True)
        shared = (
            "module shared_mac(input wire clock, input wire reset, "
            "input wire mode, input wire en, input wire [7:0] a, "
            "input wire [7:0] b, output reg [15:0] y);\n"
            "  wire signed [15:0] pa = $signed(a) * $signed(b);\n"
            "  reg [15:0] acc;\n"
            "  always @(posedge clock) begin\n"
            "    if (reset) begin acc <= 0; y <= 0; end\n"
            "    else if (en && !mode) begin acc <= acc + pa; y <= acc + pa; end\n"
            "    else if (en && mode) y <= pa;\n"
            "  end\n"
            "endmodule\n")
        naive = (
            "module mac_a(input wire clock, input wire reset, "
            "input wire en, input wire [7:0] a, input wire [7:0] b, "
            "output reg [15:0] y);\n"
            "  wire signed [15:0] product = $signed(a) * $signed(b);\n"
            "  reg [15:0] acc;\n"
            "  always @(posedge clock) begin\n"
            "    if (reset) begin acc <= 0; y <= 0; end\n"
            "    else if (en) begin acc <= acc + product; y <= acc + product; end\n"
            "  end\n"
            "endmodule\n"
            "module mac_b(input wire clock, input wire reset, "
            "input wire en, input wire [7:0] a, input wire [7:0] b, "
            "output reg [15:0] y);\n"
            "  wire signed [15:0] product = $signed(a) * $signed(b);\n"
            "  always @(posedge clock) begin\n"
            "    if (reset) y <= 0;\n"
            "    else if (en) y <= product;\n"
            "  end\n"
            "endmodule\n"
            "module shared_mac(input wire clock, input wire reset, "
            "input wire mode, input wire en, input wire [7:0] a, "
            "input wire [7:0] b, output wire [15:0] y);\n"
            "  wire [15:0] ya, yb;\n"
            "  mac_a ua(.clock(clock), .reset(reset), .en(en && !mode), "
            ".a(a), .b(b), .y(ya));\n"
            "  mac_b ub(.clock(clock), .reset(reset), .en(en && mode), "
            ".a(a), .b(b), .y(yb));\n"
            "  assign y = mode ? yb : ya;\n"
            "endmodule\n")
        # Third negative control (plan section 8): a candidate that claims to
        # satisfy a two-product-per-cycle (simultaneous-lane) requirement by
        # under-computing with the single shared multiplier. The frozen MAC
        # contract's lanes are legally mutually exclusive, so TDM is legal
        # there; this control proves the judge is sensitive to any silent
        # arithmetic deviation (a TDM "solver" of a non-serializable contract
        # would diverge the same way and be caught identically).
        double_product = (
            "module shared_mac(input wire clock, input wire reset, "
            "input wire mode, input wire en, input wire [7:0] a, "
            "input wire [7:0] b, output reg [15:0] y);\n"
            "  wire signed [15:0] pa = $signed(a) * $signed(b);\n"
            "  reg [15:0] acc;\n"
            "  always @(posedge clock) begin\n"
            "    if (reset) begin acc <= 0; y <= 0; end\n"
            "    else if (en && !mode) begin acc <= acc + 2*pa; "
            "y <= acc + 2*pa; end\n"
            "    else if (en && mode) y <= pa;\n"
            "  end\n"
            "endmodule\n")
        report = {}
        for name, text in (("shared", shared),
                           ("naive_two_mult", naive),
                           ("double_product_tdm", double_product)):
            d = st / name
            d.mkdir(exist_ok=True)
            (d / CANDIDATE).write_text(text)
            outcomes = [g(d) for g in gates]
            report[name] = [
                {"gate": o.name, "passed": o.passed, "retry": o.retry,
                 "note": o.note[:100]} for o in outcomes]
            all_pass = all(o.passed for o in outcomes)
            report[name + "_all_gates_pass"] = all_pass
        print(json.dumps(report, indent=1))
        shared_ok = report["shared_all_gates_pass"]
        naive_rejected = not report["naive_two_mult_all_gates_pass"]
        tdm_rejected = not report["double_product_tdm_all_gates_pass"]
        print(json.dumps({"selftest_valid": shared_ok and naive_rejected
                          and tdm_rejected,
                          "contract_sensitivity":
                              "single-mult TDM caught on arithmetic deviation"}))
        return 0 if (shared_ok and naive_rejected and tdm_rejected) else 1

    state = ChiaMerge(
        run_id=args.run_id, run_base=RUNS_BASE, inputs=INPUTS, contract=CONTRACT,
        gates=gates, accept_level=len(gates),
        adviser_model=args.planner_model, implementer_model=args.worker_model,
        candidate_filename=CANDIDATE, turns=args.turns, resume=args.resume)
    print(json.dumps({"run_id": args.run_id, "accepted": state.accepted,
                      "best_level": state.best_level,
                      "turns": [h.get("status") for h in state.history]}))
    return 0 if state.accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
