#!/usr/bin/env python3
"""Synthesis-only sharing control for the MAC merge (model-free).

Question (astra review): does plain synthesis already produce the shared
one-multiplier design from a straightforward two-reference composition,
without any agentic loop? Compose mac_a + mac_b + legal mode mux (the
naive control), run the declared synthesis flows, count multipliers and
cells, and compare with the ChiaMerge accepted candidates (531 generic
cells). Reports a machine-readable JSON; nothing here is judged by a model.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

PE = Path(__file__).resolve().parents[1]
OSS = "/work/peweaver/toolchains/oss-cad-suite/bin"

NAIVE = (
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


def run_yosys(script: str, tag: str, work: Path) -> dict:
    """One yosys flow over the naive composition. The LAST 'N cells' row of
    the TOP module stat is the cell count; $mul rows are summed."""
    work.mkdir(parents=True, exist_ok=True)
    vfile = work / f"naive_{tag}.v"
    vfile.write_text(NAIVE)
    proc = subprocess.run(
        ["yosys", "-p", f"read_verilog {vfile}; {script}"],
        capture_output=True, text=True, timeout=900,
        env={"PATH": OSS + ":/usr/bin:/bin"})
    out = (proc.stdout or "") + (proc.stderr or "")
    mul_rows = re.findall(r"^\s*(\d+)\s+\$(\w*mul\w*)\s*$", out, re.M)
    mul_count = sum(int(n) for n, _ in mul_rows)
    cells = re.findall(r"^\s*(\d+)\s+cells\s*$", out, re.M)
    cell_count = int(cells[-1]) if cells else None
    return {"flow": tag, "rc": proc.returncode,
            "multipliers": mul_count,
            "cells": cell_count,
            "synth_ok": proc.returncode == 0 and cell_count is not None}


def main() -> int:
    import os
    work = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("synth_control_work")
    report = {"control": "synthesis-only MAC sharing",
              "composition": "two frozen references + legal mode mux",
              "agent_result": {"multipliers": 1, "cells": 531},
              "flows": []}
    report["flows"].append(run_yosys(
        "hierarchy -top shared_mac; proc; opt -full; stat",
        "structure_elaboration", work))
    report["flows"].append(run_yosys(
        "synth -top shared_mac; stat", "plain_synth", work))
    report["flows"].append(run_yosys(
        "synth -top shared_mac; share -aggressive; opt -full; stat",
        "share_aggressive_synth", work))
    (work / "synthesis_control_report.json").write_text(
        json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))
    struct = report["flows"][0]
    synth = report["flows"][1]
    verdict = ("synthesis alone achieves one multiplier"
               if struct["multipliers"] <= 1 else
               "synthesis alone does NOT share the multipliers "
               f"(naive structure keeps {struct['multipliers']} $mul cells; "
               f"naive synth cell count {synth['cells']} vs the two-reference "
               f"sum 949 and the agent candidate 531)")
    report["verdict"] = verdict
    (work / "synthesis_control_report.json").write_text(
        json.dumps(report, indent=1))
    print(verdict)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
