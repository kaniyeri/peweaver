#!/usr/bin/env python3
"""PEWeaver Multi-Domain Post-Merge Power Reduction Engine.

Evaluates and proves activity-based power reduction on SkyWater 130nm (OpenSTA + VCD)
across three post-merge benchmark domains:
1. MAC (Multiply-Accumulate)
2. FIR (8-tap Dual-Context Filter)
3. DWT (Discrete Wavelet Transform Dual-Context)

Techniques evaluated:
- Characterized Integrated Clock Gating (sky130_fd_sc_hd__dlclkp_4)
- Operand Isolation on Multipliers and Arithmetic Adders
- Context / Decimation Phase Gating
"""

from __future__ import annotations

import os
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path

WORK_BASE = Path(
    os.environ.get(
        "PEWEAVER_POWER_REDUCTION_WORK_BASE",
        "/work/peweaver/runs/chia_power_reduction",
    )
)

OSS = "/work/peweaver/toolchains/oss-cad-suite/bin"
LIB = "/work/peweaver/toolchains/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib"
PRIM_V = "/work/peweaver/toolchains/.volare/sky130A/libs.ref/sky130_fd_sc_hd/verilog/primitives.v"
CELL_V = "/work/peweaver/toolchains/.volare/sky130A/libs.ref/sky130_fd_sc_hd/verilog/sky130_fd_sc_hd.v"
ICG_BOX = "/work/peweaver/source/chia/examples/peweaver/physical/rtl/sky130_icg_blackbox.v"


def run_cmd(cmd: str, cwd: Path) -> str:
    env = os.environ.copy()
    env["PATH"] = f"{OSS}:{env.get('PATH', '')}"
    r = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=cwd, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"Command failed in {cwd}:\n{cmd}\n\nOutput:\n{r.stdout}")
    return r.stdout


def measure_opensta_power(work_dir: Path, top_module: str, synth_netlist: str, vcd_file: str, tb_scope: str, clk_name: str = "clock") -> dict:
    """Run OpenSTA reading Sky130 liberty, SDC, and VCD activity to extract power metrics."""
    # Strip any 'signed' keywords from the synthesized netlist so OpenSTA parses cleanly
    netlist_path = work_dir / synth_netlist
    content = netlist_path.read_text()
    cleaned = re.sub(r"\bsigned\b", "", content)
    netlist_path.write_text(cleaned)

    tcl_path = work_dir / f"power_{synth_netlist}.tcl"
    netlist_abs = (work_dir / synth_netlist).resolve()
    vcd_abs = (work_dir / vcd_file).resolve()
    tcl_path.write_text(f"""
read_liberty {LIB}
read_verilog {netlist_abs}
link_design {top_module}
create_clock -name {clk_name} -period 10.0 [get_ports {clk_name}]
set_input_delay -clock {clk_name} 1.0 [all_inputs -no_clocks]
set_output_delay -clock {clk_name} 1.0 [all_outputs]
read_power_activities -scope {tb_scope} -vcd {vcd_abs}
report_power -digits 6
""")
    sta_out = run_cmd(f"/usr/bin/sta {tcl_path.name}", cwd=work_dir)
    
    total_mW = 0.0
    seq_mW = 0.0
    comb_mW = 0.0
    switch_mW = 0.0

    for line in sta_out.splitlines():
        parts = line.split()
        if line.startswith("Total") and len(parts) >= 5:
            switch_mW = float(parts[2]) * 1000.0
            total_mW = float(parts[4]) * 1000.0
        elif line.startswith("Sequential") and len(parts) >= 5:
            seq_mW = float(parts[4]) * 1000.0
        elif line.startswith("Combinational") and len(parts) >= 5:
            comb_mW = float(parts[4]) * 1000.0

    return {
        "total_mW": total_mW,
        "comb_mW": comb_mW,
        "seq_mW": seq_mW,
        "switch_mW": switch_mW,
        "sta_out": sta_out
    }


# ==============================================================================
# DOMAIN 1: MAC POWER REDUCTION
# ==============================================================================

MAC_BASELINE = """// Baseline accepted shared_mac
module shared_mac (
    input  wire        clock,
    input  wire        reset,
    input  wire        mode,
    input  wire        en,
    input  wire [7:0]  a,
    input  wire [7:0]  b,
    output reg  [15:0] y
);
    reg  [15:0] acc;
    wire signed [15:0] product = $signed(a) * $signed(b);
    wire        [15:0] sum     = acc + product;

    always @(posedge clock) begin
        if (reset) begin
            acc <= 16'd0;
            y   <= 16'd0;
        end else if (en) begin
            if (!mode) begin
                acc <= sum;
                y   <= sum;
            end else begin
                y   <= product;
            end
        end
    end
endmodule
"""

MAC_POWER_OPT = """// Power-Optimized shared_mac: Characterized ICG + Operand Isolation
module shared_mac (
    input  wire        clock,
    input  wire        reset,
    input  wire        mode,
    input  wire        en,
    input  wire [7:0]  a,
    input  wire [7:0]  b,
    output reg  [15:0] y
);
    reg  [15:0] acc;

    // 1. Multiplier Operand Isolation
    wire [7:0] a_iso = en ? a : 8'd0;
    wire [7:0] b_iso = en ? b : 8'd0;
    wire signed [15:0] product = $signed(a_iso) * $signed(b_iso);

    // 2. Accumulator Adder Gating
    wire [15:0] acc_iso = (!mode) ? acc : 16'd0;
    wire [15:0] sum     = acc_iso + product;

    // 3. Characterized Integrated Clock Gating (sky130_fd_sc_hd__dlclkp_4)
    wire gated_clk;
    sky130_fd_sc_hd__dlclkp_4 u_icg (
        .CLK(clock),
        .GATE(en | reset),
        .GCLK(gated_clk)
    );

    always @(posedge gated_clk or posedge reset) begin
        if (reset) begin
            acc <= 16'd0;
            y   <= 16'd0;
        end else begin
            if (!mode) begin
                acc <= sum;
                y   <= sum;
            end else begin
                y   <= product;
            end
        end
    end
endmodule
"""

MAC_TB = """`timescale 1ns/1ps
module mac_power_tb;
    reg clock = 0, reset = 0, mode = 0, en = 0;
    reg [7:0] a = 0, b = 0;
    wire [15:0] y;
    always #5 clock = ~clock; // 100 MHz (10ns period)

    shared_mac dut (
        .clock(clock), .reset(reset), .mode(mode), .en(en),
        .a(a), .b(b), .y(y));

    reg [7:0] smem [0:8191];
    integer k, out_fd;
    initial begin
        $dumpfile("activity.vcd");
        $dumpvars(0, mac_power_tb);
        out_fd = $fopen("cap.txt", "w");
        $readmemh("stim.txt", smem);
        for (k = 0; k < 4*1200; k = k + 4) begin
            mode  = smem[k][0];
            en    = smem[k][1];
            a     = smem[k+1];
            b     = smem[k+2];
            reset = smem[k+3][0];
            @(posedge clock);
            @(negedge clock);
            $fwrite(out_fd, "%h\\n", y);
        end
        $fclose(out_fd);
        $finish;
    end
endmodule
"""


def eval_mac():
    work = WORK_BASE / "mac"
    work.mkdir(parents=True, exist_ok=True)
    print("\n=======================================================")
    print("DOMAIN 1: MAC (Multiply-Accumulate) Power Optimization")
    print("=======================================================")

    rng = random.Random(0x5ACED1CE)
    stim = []
    mode = 0; pending = False; prev_en = 0
    for k in range(1200):
        if k % 150 == 0: pending = True
        en = 1 if (k % 4) < 2 else 0
        rst = 1 if k in (0, 1, 400, 401) else 0
        if pending and prev_en == 0 and not rst:
            mode ^= 1; pending = False
        prev_en = en
        stim.append((mode, en, rng.randrange(256), rng.randrange(256), rst))
    with open(work / "stim.txt", "w") as f:
        for m, e, a, b, r in stim:
            f.write(f"{(m & 1) | ((e & 1) << 1):02x} {a:02x} {b:02x} {r:02x}\n")

    (work / "mac_power_tb.sv").write_text(MAC_TB)

    # 1. Baseline
    (work / "mac_base.v").write_text(MAC_BASELINE)
    run_cmd(f"yosys -p 'read_verilog mac_base.v; synth -top shared_mac; dfflibmap -liberty {LIB}; abc -liberty {LIB}; clean; write_verilog -noattr mac_base_sky130.v'", cwd=work)
    run_cmd(f"iverilog -g2012 -DFUNCTIONAL -DUNIT_DELAY=#1 {PRIM_V} {CELL_V} mac_base_sky130.v mac_power_tb.sv -o sim_base.vvp", cwd=work)
    run_cmd("vvp sim_base.vvp", cwd=work)
    os.replace(work / "activity.vcd", work / "activity_base.vcd")
    os.replace(work / "cap.txt", work / "cap_base.txt")
    base = measure_opensta_power(work, "shared_mac", "mac_base_sky130.v", "activity_base.vcd", "mac_power_tb/dut")

    # 2. Power-Optimized
    (work / "mac_opt.v").write_text(MAC_POWER_OPT)
    run_cmd(f"yosys -p 'read_verilog -lib {ICG_BOX}; read_verilog mac_opt.v; synth -top shared_mac; dfflibmap -liberty {LIB}; abc -liberty {LIB}; clean; write_verilog -noattr mac_opt_sky130.v'", cwd=work)
    run_cmd(f"iverilog -g2012 -DFUNCTIONAL -DUNIT_DELAY=#1 {PRIM_V} {CELL_V} mac_opt_sky130.v mac_power_tb.sv -o sim_opt.vvp", cwd=work)
    run_cmd("vvp sim_opt.vvp", cwd=work)
    os.replace(work / "activity.vcd", work / "activity_opt.vcd")
    os.replace(work / "cap.txt", work / "cap_opt.txt")
    opt = measure_opensta_power(work, "shared_mac", "mac_opt_sky130.v", "activity_opt.vcd", "mac_power_tb/dut")

    # Verify bit-exact equivalence
    base_cap = (work / "cap_base.txt").read_text()
    opt_cap = (work / "cap_opt.txt").read_text()
    assert base_cap == opt_cap, "Functional mismatch between baseline and power-optimized MAC!"
    print("Functional verification: BIT-EXACT MATCH across 1200 cycles!")

    delta_tot = (1.0 - opt["total_mW"] / base["total_mW"]) * 100.0
    delta_comb = (1.0 - opt["comb_mW"] / base["comb_mW"]) * 100.0
    delta_seq = (1.0 - opt["seq_mW"] / base["seq_mW"]) * 100.0
    delta_switch = (1.0 - opt["switch_mW"] / base["switch_mW"]) * 100.0

    print(f"Baseline:  Total = {base['total_mW']:.4f} mW | Comb = {base['comb_mW']:.4f} mW | Seq = {base['seq_mW']:.4f} mW | Switching = {base['switch_mW']:.4f} mW")
    print(f"Optimized: Total = {opt['total_mW']:.4f} mW | Comb = {opt['comb_mW']:.4f} mW | Seq = {opt['seq_mW']:.4f} mW | Switching = {opt['switch_mW']:.4f} mW")
    print(f"--> Total Power Drop:         {delta_tot:+.2f}%")
    print(f"--> Switching Power Drop:     {delta_switch:+.2f}%")
    print(f"--> Combinational Power Drop: {delta_comb:+.2f}%")
    print(f"--> Sequential Power Drop:    {delta_seq:+.2f}%")

    return {"base": base, "opt": opt, "delta_tot": delta_tot, "delta_switch": delta_switch, "delta_seq": delta_seq, "delta_comb": delta_comb}


# ==============================================================================
# DOMAIN 2: FIR DUAL-CONTEXT FILTER POWER REDUCTION
# ==============================================================================

FIR_BASELINE = """// Baseline accepted fir_shared from fir-merge-1
module fir_shared #(
    parameter WIDTH = 16
) (
    input  wire                 clock,
    input  wire                 reset,
    input  wire                 ctx,
    input  wire                 en,
    input  wire signed [15:0]   x,
    output reg  signed [39:0]   y_a,
    output reg  signed [39:0]   y_b
);
    localparam signed [15:0] CA0 = 16'sd16384, CA1 = -16'sd8192, CA2 = 16'sd4096, CA3 = 16'sd2048;
    localparam signed [15:0] CA4 = 16'sd1024,  CA5 = 16'sd512,  CA6 = 16'sd256,  CA7 = 16'sd128;

    localparam signed [15:0] CB0 = 16'sd12288, CB1 = -16'sd14336, CB2 = 16'sd5325, CB3 = 16'sd2662;
    localparam signed [15:0] CB4 = 16'sd1331,  CB5 = 16'sd665,   CB6 = 16'sd333,  CB7 = 16'sd166;

    reg signed [15:0] z_a [0:7];
    reg signed [15:0] z_b [0:7];

    wire signed [31:0] ma0 = CA0 * z_a[0], ma1 = CA1 * z_a[1], ma2 = CA2 * z_a[2], ma3 = CA3 * z_a[3];
    wire signed [31:0] ma4 = CA4 * z_a[4], ma5 = CA5 * z_a[5], ma6 = CA6 * z_a[6], ma7 = CA7 * z_a[7];

    wire signed [31:0] mb0 = CB0 * z_b[0], mb1 = CB1 * z_b[1], mb2 = CB2 * z_b[2], mb3 = CB3 * z_b[3];
    wire signed [31:0] mb4 = CB4 * z_b[4], mb5 = CB5 * z_b[5], mb6 = CB6 * z_b[6], mb7 = CB7 * z_b[7];

    wire signed [31:0] m0 = ctx ? mb0 : ma0, m1 = ctx ? mb1 : ma1, m2 = ctx ? mb2 : ma2, m3 = ctx ? mb3 : ma3;
    wire signed [31:0] m4 = ctx ? mb4 : ma4, m5 = ctx ? mb5 : ma5, m6 = ctx ? mb6 : ma6, m7 = ctx ? mb7 : ma7;

    wire signed [39:0] sum = {{8{m0[31]}}, m0} + {{8{m1[31]}}, m1} + {{8{m2[31]}}, m2} + {{8{m3[31]}}, m3} +
                             {{8{m4[31]}}, m4} + {{8{m5[31]}}, m5} + {{8{m6[31]}}, m6} + {{8{m7[31]}}, m7};

    integer i;
    always @(posedge clock) begin
        if (reset) begin
            for (i=0; i<8; i=i+1) begin z_a[i] <= 16'sd0; z_b[i] <= 16'sd0; end
            y_a <= 40'sd0; y_b <= 40'sd0;
        end else if (en) begin
            if (!ctx) begin
                z_a[0] <= x; for (i=1; i<8; i=i+1) z_a[i] <= z_a[i-1];
                y_a <= sum;
            end else begin
                z_b[0] <= x; for (i=1; i<8; i=i+1) z_b[i] <= z_b[i-1];
                y_b <= sum;
            end
        end
    end
endmodule
"""

FIR_POWER_OPT = """// Power-Optimized fir_shared: Split-Context ICG + Multiplier Isolation
module fir_shared #(
    parameter WIDTH = 16
) (
    input  wire                 clock,
    input  wire                 reset,
    input  wire                 ctx,
    input  wire                 en,
    input  wire signed [15:0]   x,
    output reg  signed [39:0]   y_a,
    output reg  signed [39:0]   y_b
);
    localparam signed [15:0] CA0 = 16'sd16384, CA1 = -16'sd8192, CA2 = 16'sd4096, CA3 = 16'sd2048;
    localparam signed [15:0] CA4 = 16'sd1024,  CA5 = 16'sd512,  CA6 = 16'sd256,  CA7 = 16'sd128;

    localparam signed [15:0] CB0 = 16'sd12288, CB1 = -16'sd14336, CB2 = 16'sd5325, CB3 = 16'sd2662;
    localparam signed [15:0] CB4 = 16'sd1331,  CB5 = 16'sd665,   CB6 = 16'sd333,  CB7 = 16'sd166;

    reg signed [15:0] z_a [0:7];
    reg signed [15:0] z_b [0:7];

    // 1. Context-Aware Characterized ICG Clock Gating
    wire clk_a, clk_b;
    sky130_fd_sc_hd__dlclkp_4 u_icg_a (
        .CLK(clock), .GATE((en & ~ctx) | reset), .GCLK(clk_a)
    );
    sky130_fd_sc_hd__dlclkp_4 u_icg_b (
        .CLK(clock), .GATE((en & ctx) | reset), .GCLK(clk_b)
    );

    // 2. Multiplier Operand Isolation
    wire signed [15:0] za_iso [0:7];
    wire signed [15:0] zb_iso [0:7];
    genvar g;
    generate
        for (g=0; g<8; g=g+1) begin : iso_gen
            assign za_iso[g] = (~ctx & en) ? z_a[g] : 16'sd0;
            assign zb_iso[g] = (ctx & en)  ? z_b[g] : 16'sd0;
        end
    endgenerate

    wire signed [31:0] ma0 = CA0 * za_iso[0], ma1 = CA1 * za_iso[1], ma2 = CA2 * za_iso[2], ma3 = CA3 * za_iso[3];
    wire signed [31:0] ma4 = CA4 * za_iso[4], ma5 = CA5 * za_iso[5], ma6 = CA6 * za_iso[6], ma7 = CA7 * za_iso[7];

    wire signed [31:0] mb0 = CB0 * zb_iso[0], mb1 = CB1 * zb_iso[1], mb2 = CB2 * zb_iso[2], mb3 = CB3 * zb_iso[3];
    wire signed [31:0] mb4 = CB4 * zb_iso[4], mb5 = CB5 * zb_iso[5], mb6 = CB6 * zb_iso[6], mb7 = CB7 * zb_iso[7];

    wire signed [31:0] m0 = ctx ? mb0 : ma0, m1 = ctx ? mb1 : ma1, m2 = ctx ? mb2 : ma2, m3 = ctx ? mb3 : ma3;
    wire signed [31:0] m4 = ctx ? mb4 : ma4, m5 = ctx ? mb5 : ma5, m6 = ctx ? mb6 : ma6, m7 = ctx ? mb7 : ma7;

    wire signed [39:0] sum = {{8{m0[31]}}, m0} + {{8{m1[31]}}, m1} + {{8{m2[31]}}, m2} + {{8{m3[31]}}, m3} +
                             {{8{m4[31]}}, m4} + {{8{m5[31]}}, m5} + {{8{m6[31]}}, m6} + {{8{m7[31]}}, m7};

    integer i;
    always @(posedge clk_a or posedge reset) begin
        if (reset) begin
            for (i=0; i<8; i=i+1) z_a[i] <= 16'sd0;
            y_a <= 40'sd0;
        end else begin
            z_a[0] <= x; for (i=1; i<8; i=i+1) z_a[i] <= z_a[i-1];
            y_a <= sum;
        end
    end

    always @(posedge clk_b or posedge reset) begin
        if (reset) begin
            for (i=0; i<8; i=i+1) z_b[i] <= 16'sd0;
            y_b <= 40'sd0;
        end else begin
            z_b[0] <= x; for (i=1; i<8; i=i+1) z_b[i] <= z_b[i-1];
            y_b <= sum;
        end
    end
endmodule
"""

FIR_TB = """`timescale 1ns/1ps
module fir_power_tb;
    reg clock = 0, reset = 0, ctx = 0, en = 0;
    reg signed [15:0] x = 0;
    wire signed [39:0] y_a, y_b;
    always #5 clock = ~clock;

    fir_shared dut (
        .clock(clock), .reset(reset), .ctx(ctx), .en(en), .x(x),
        .y_a(y_a), .y_b(y_b));

    reg [31:0] smem [0:8191];
    integer k, out_fd;
    initial begin
        $dumpfile("activity.vcd");
        $dumpvars(0, fir_power_tb);
        out_fd = $fopen("cap.txt", "w");
        $readmemh("stim.txt", smem);
        for (k = 0; k < 1200; k = k + 1) begin
            ctx   = smem[k][17];
            en    = smem[k][16];
            reset = smem[k][18];
            x     = smem[k][15:0];
            @(posedge clock);
            @(negedge clock);
            $fwrite(out_fd, "%h %h\\n", y_a, y_b);
        end
        $fclose(out_fd);
        $finish;
    end
endmodule
"""


def eval_fir():
    work = WORK_BASE / "fir"
    work.mkdir(parents=True, exist_ok=True)
    print("\n=======================================================")
    print("DOMAIN 2: FIR (Dual-Context Filter) Power Optimization")
    print("=======================================================")

    rng = random.Random(0x46495231)
    stim = []
    ctx = 0; pending_ctx = False; prev_en = 0
    for k in range(1200):
        if k % 120 == 0: pending_ctx = True
        en = 1 if (k % 4) < 2 else 0
        rst = 1 if k in (0, 1, 500, 501) else 0
        if pending_ctx and prev_en == 0 and not rst:
            ctx ^= 1; pending_ctx = False
        prev_en = en
        x_val = rng.randrange(-32768, 32767) & 0xFFFF
        stim.append((ctx, en, rst, x_val))

    with open(work / "stim.txt", "w") as f:
        for c, e, r, x in stim:
            word = (r << 18) | (c << 17) | (e << 16) | x
            f.write(f"{word:08x}\n")

    (work / "fir_power_tb.sv").write_text(FIR_TB)

    # 1. Baseline
    (work / "fir_base.v").write_text(FIR_BASELINE)
    run_cmd(f"yosys -p 'read_verilog fir_base.v; synth -top fir_shared; dfflibmap -liberty {LIB}; abc -liberty {LIB}; clean; write_verilog -noattr fir_base_sky130.v'", cwd=work)
    run_cmd(f"iverilog -g2012 -DFUNCTIONAL -DUNIT_DELAY=#1 {PRIM_V} {CELL_V} fir_base_sky130.v fir_power_tb.sv -o sim_base.vvp", cwd=work)
    run_cmd("vvp sim_base.vvp", cwd=work)
    os.replace(work / "activity.vcd", work / "activity_base.vcd")
    os.replace(work / "cap.txt", work / "cap_base.txt")
    base = measure_opensta_power(work, "fir_shared", "fir_base_sky130.v", "activity_base.vcd", "fir_power_tb/dut")

    # 2. Power-Optimized
    (work / "fir_opt.v").write_text(FIR_POWER_OPT)
    run_cmd(f"yosys -p 'read_verilog -lib {ICG_BOX}; read_verilog fir_opt.v; synth -top fir_shared; dfflibmap -liberty {LIB}; abc -liberty {LIB}; clean; write_verilog -noattr fir_opt_sky130.v'", cwd=work)
    run_cmd(f"iverilog -g2012 -DFUNCTIONAL -DUNIT_DELAY=#1 {PRIM_V} {CELL_V} fir_opt_sky130.v fir_power_tb.sv -o sim_opt.vvp", cwd=work)
    run_cmd("vvp sim_opt.vvp", cwd=work)
    os.replace(work / "activity.vcd", work / "activity_opt.vcd")
    os.replace(work / "cap.txt", work / "cap_opt.txt")
    opt = measure_opensta_power(work, "fir_shared", "fir_opt_sky130.v", "activity_opt.vcd", "fir_power_tb/dut")

    # Verify bit-exact equivalence
    base_cap = (work / "cap_base.txt").read_text()
    opt_cap = (work / "cap_opt.txt").read_text()
    assert base_cap == opt_cap, "Functional mismatch between baseline and power-optimized FIR!"
    print("Functional verification: BIT-EXACT MATCH across 1200 cycles!")

    delta_tot = (1.0 - opt["total_mW"] / base["total_mW"]) * 100.0
    delta_comb = (1.0 - opt["comb_mW"] / base["comb_mW"]) * 100.0
    delta_seq = (1.0 - opt["seq_mW"] / base["seq_mW"]) * 100.0
    delta_switch = (1.0 - opt["switch_mW"] / base["switch_mW"]) * 100.0

    print(f"Baseline:  Total = {base['total_mW']:.4f} mW | Comb = {base['comb_mW']:.4f} mW | Seq = {base['seq_mW']:.4f} mW | Switching = {base['switch_mW']:.4f} mW")
    print(f"Optimized: Total = {opt['total_mW']:.4f} mW | Comb = {opt['comb_mW']:.4f} mW | Seq = {opt['seq_mW']:.4f} mW | Switching = {opt['switch_mW']:.4f} mW")
    print(f"--> Total Power Drop:         {delta_tot:+.2f}%")
    print(f"--> Switching Power Drop:     {delta_switch:+.2f}%")
    print(f"--> Combinational Power Drop: {delta_comb:+.2f}%")
    print(f"--> Sequential Power Drop:    {delta_seq:+.2f}%")

    return {"base": base, "opt": opt, "delta_tot": delta_tot, "delta_switch": delta_switch, "delta_seq": delta_seq, "delta_comb": delta_comb}


# ==============================================================================
# DOMAIN 3: DWT DUAL-CONTEXT WAVELET TRANSFORM POWER REDUCTION
# ==============================================================================

DWT_BASELINE = """// Baseline accepted dwt_shared from dwt-merge-1
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
    localparam signed [15:0] H0 = 15826, H1 = 27411, H2 = 7345, H3 = -4240;
    localparam signed [15:0] G0 = -4240, G1 = -7345, G2 = 27411, G3 = -15826;

    reg signed [15:0] a_w0, a_w1, a_w2;
    reg               a_ph;

    reg signed [15:0] b_w0, b_w1, b_w2;
    reg signed [15:0] b_q0, b_q1, b_q2, b_q3;
    reg               b_ph, b_mpar, b_pending;

    wire sel_b_l2 = ctx && (!b_ph) && b_pending;

    wire signed [15:0] in0 = sel_b_l2 ? b_q0 : x;
    wire signed [15:0] in1 = sel_b_l2 ? b_q1 : (ctx ? b_w0 : a_w0);
    wire signed [15:0] in2 = sel_b_l2 ? b_q2 : (ctx ? b_w1 : a_w1);
    wire signed [15:0] in3 = sel_b_l2 ? b_q3 : (ctx ? b_w2 : a_w2);

    wire signed [39:0] mult_lo0 = H0 * in0, mult_lo1 = H1 * in1, mult_lo2 = H2 * in2, mult_lo3 = H3 * in3;
    wire signed [39:0] mult_hi0 = G0 * in0, mult_hi1 = G1 * in1, mult_hi2 = G2 * in2, mult_hi3 = G3 * in3;

    wire signed [39:0] lo_sum = mult_lo0 + mult_lo1 + mult_lo2 + mult_lo3;
    wire signed [39:0] hi_sum = mult_hi0 + mult_hi1 + mult_hi2 + mult_hi3;

    always @(posedge clock) begin
        if (reset) begin
            a_w0 <= 16'sd0; a_w1 <= 16'sd0; a_w2 <= 16'sd0; a_ph <= 1'b0;
            a_l1_lo <= 40'sd0; a_l1_hi <= 40'sd0; a_l1_valid <= 1'b0;
            b_w0 <= 16'sd0; b_w1 <= 16'sd0; b_w2 <= 16'sd0;
            b_q0 <= 16'sd0; b_q1 <= 16'sd0; b_q2 <= 16'sd0; b_q3 <= 16'sd0;
            b_ph <= 1'b0; b_mpar <= 1'b0; b_pending <= 1'b0;
            b_l1_lo <= 40'sd0; b_l1_hi <= 40'sd0; b_l1_valid <= 1'b0;
            b_l2_lo <= 40'sd0; b_l2_hi <= 40'sd0; b_l2_valid <= 1'b0;
        end else begin
            a_l1_valid <= 1'b0; b_l1_valid <= 1'b0; b_l2_valid <= 1'b0;
            if (en) begin
                if (!ctx) begin
                    a_w0 <= x; a_w1 <= a_w0; a_w2 <= a_w1;
                    if (a_ph) begin
                        a_l1_lo <= lo_sum; a_l1_hi <= hi_sum; a_l1_valid <= 1'b1;
                    end
                    a_ph <= ~a_ph;
                end else begin
                    b_w0 <= x; b_w1 <= b_w0; b_w2 <= b_w1;
                    if (b_ph) begin
                        b_l1_lo <= lo_sum; b_l1_hi <= hi_sum; b_l1_valid <= 1'b1;
                        b_q3 <= b_q2; b_q2 <= b_q1; b_q1 <= b_q0; b_q0 <= lo_sum[30:15];
                        if (b_mpar) b_pending <= 1'b1;
                        b_mpar <= ~b_mpar;
                    end else if (b_pending) begin
                        b_l2_lo <= lo_sum; b_l2_hi <= hi_sum; b_l2_valid <= 1'b1;
                        b_pending <= 1'b0;
                    end
                    b_ph <= ~b_ph;
                end
            end
        end
    end
endmodule
"""

DWT_POWER_OPT = """// Power-Optimized dwt_shared: Decimation Gating & Characterized ICG
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
    localparam signed [15:0] H0 = 15826, H1 = 27411, H2 = 7345, H3 = -4240;
    localparam signed [15:0] G0 = -4240, G1 = -7345, G2 = 27411, G3 = -15826;

    reg signed [15:0] a_w0, a_w1, a_w2;
    reg               a_ph;

    reg signed [15:0] b_w0, b_w1, b_w2;
    reg signed [15:0] b_q0, b_q1, b_q2, b_q3;
    reg               b_ph, b_mpar, b_pending;

    // 1. Context Clock Gating
    wire clk_a, clk_b;
    sky130_fd_sc_hd__dlclkp_4 u_icg_a (
        .CLK(clock), .GATE((en & ~ctx) | reset), .GCLK(clk_a)
    );
    sky130_fd_sc_hd__dlclkp_4 u_icg_b (
        .CLK(clock), .GATE((en & ctx) | reset), .GCLK(clk_b)
    );

    wire sel_b_l2 = ctx && (!b_ph) && b_pending;

    wire signed [15:0] in0_raw = sel_b_l2 ? b_q0 : x;
    wire signed [15:0] in1_raw = sel_b_l2 ? b_q1 : (ctx ? b_w0 : a_w0);
    wire signed [15:0] in2_raw = sel_b_l2 ? b_q2 : (ctx ? b_w1 : a_w1);
    wire signed [15:0] in3_raw = sel_b_l2 ? b_q3 : (ctx ? b_w2 : a_w2);

    // 2. Active-Cycle Multiplier Operand Isolation:
    // Only compute filter products when an active context is producing valid outputs!
    wire mult_active = en && ( (!ctx && a_ph) || (ctx && (b_ph || b_pending)) );
    wire signed [15:0] in0 = mult_active ? in0_raw : 16'sd0;
    wire signed [15:0] in1 = mult_active ? in1_raw : 16'sd0;
    wire signed [15:0] in2 = mult_active ? in2_raw : 16'sd0;
    wire signed [15:0] in3 = mult_active ? in3_raw : 16'sd0;

    wire signed [39:0] mult_lo0 = H0 * in0, mult_lo1 = H1 * in1, mult_lo2 = H2 * in2, mult_lo3 = H3 * in3;
    wire signed [39:0] mult_hi0 = G0 * in0, mult_hi1 = G1 * in1, mult_hi2 = G2 * in2, mult_hi3 = G3 * in3;

    wire signed [39:0] lo_sum = mult_lo0 + mult_lo1 + mult_lo2 + mult_lo3;
    wire signed [39:0] hi_sum = mult_hi0 + mult_hi1 + mult_hi2 + mult_hi3;

    // Context A registers driven by clk_a
    always @(posedge clk_a or posedge reset) begin
        if (reset) begin
            a_w0 <= 16'sd0; a_w1 <= 16'sd0; a_w2 <= 16'sd0; a_ph <= 1'b0;
            a_l1_lo <= 40'sd0; a_l1_hi <= 40'sd0;
        end else begin
            a_w0 <= x; a_w1 <= a_w0; a_w2 <= a_w1;
            if (a_ph) begin
                a_l1_lo <= lo_sum; a_l1_hi <= hi_sum;
            end
            a_ph <= ~a_ph;
        end
    end

    // Context B registers driven by clk_b
    always @(posedge clk_b or posedge reset) begin
        if (reset) begin
            b_w0 <= 16'sd0; b_w1 <= 16'sd0; b_w2 <= 16'sd0;
            b_q0 <= 16'sd0; b_q1 <= 16'sd0; b_q2 <= 16'sd0; b_q3 <= 16'sd0;
            b_ph <= 1'b0; b_mpar <= 1'b0; b_pending <= 1'b0;
            b_l1_lo <= 40'sd0; b_l1_hi <= 40'sd0;
            b_l2_lo <= 40'sd0; b_l2_hi <= 40'sd0;
        end else begin
            b_w0 <= x; b_w1 <= b_w0; b_w2 <= b_w1;
            if (b_ph) begin
                b_l1_lo <= lo_sum; b_l1_hi <= hi_sum;
                b_q3 <= b_q2; b_q2 <= b_q1; b_q1 <= b_q0; b_q0 <= lo_sum[30:15];
                if (b_mpar) b_pending <= 1'b1;
                b_mpar <= ~b_mpar;
            end else if (b_pending) begin
                b_l2_lo <= lo_sum; b_l2_hi <= hi_sum;
                b_pending <= 1'b0;
            end
            b_ph <= ~b_ph;
        end
    end

    // Valid strobes on un-gated master clock (single-cycle pulses)
    always @(posedge clock) begin
        if (reset) begin
            a_l1_valid <= 1'b0; b_l1_valid <= 1'b0; b_l2_valid <= 1'b0;
        end else begin
            a_l1_valid <= 1'b0; b_l1_valid <= 1'b0; b_l2_valid <= 1'b0;
            if (en) begin
                if (!ctx) begin
                    if (a_ph) a_l1_valid <= 1'b1;
                end else begin
                    if (b_ph) b_l1_valid <= 1'b1;
                    else if (b_pending) b_l2_valid <= 1'b1;
                end
            end
        end
    end
endmodule
"""

DWT_TB = """`timescale 1ns/1ps
module dwt_power_tb;
    reg clock = 0, reset = 0, ctx = 0, en = 0;
    reg signed [15:0] x = 0;
    wire signed [39:0] a_l1_lo, a_l1_hi, b_l1_lo, b_l1_hi, b_l2_lo, b_l2_hi;
    wire a_l1_valid, b_l1_valid, b_l2_valid;
    always #5 clock = ~clock;

    dwt_shared dut (
        .clock(clock), .reset(reset), .ctx(ctx), .en(en), .x(x),
        .a_l1_lo(a_l1_lo), .a_l1_hi(a_l1_hi), .a_l1_valid(a_l1_valid),
        .b_l1_lo(b_l1_lo), .b_l1_hi(b_l1_hi), .b_l1_valid(b_l1_valid),
        .b_l2_lo(b_l2_lo), .b_l2_hi(b_l2_hi), .b_l2_valid(b_l2_valid));

    reg [7:0] smem [0:8191];
    integer k, out_fd;
    initial begin
        $dumpfile("activity.vcd");
        $dumpvars(0, dwt_power_tb);
        out_fd = $fopen("cap.txt", "w");
        $readmemh("stim.txt", smem);
        for (k = 0; k < 1200; k = k + 1) begin
            ctx   = smem[3*k][0];
            en    = smem[3*k][1];
            reset = smem[3*k][2];
            x     = {smem[3*k+1], smem[3*k+2]};
            @(posedge clock);
            @(negedge clock);
            $fwrite(out_fd, "%010h %010h %0d %010h %010h %0d %010h %010h %0d\\n",
                    a_l1_lo, a_l1_hi, a_l1_valid,
                    b_l1_lo, b_l1_hi, b_l1_valid,
                    b_l2_lo, b_l2_hi, b_l2_valid);
        end
        $fclose(out_fd);
        $finish;
    end
endmodule
"""


def eval_dwt():
    work = WORK_BASE / "dwt"
    work.mkdir(parents=True, exist_ok=True)
    print("\n=======================================================")
    print("DOMAIN 3: DWT (Dual-Context Wavelet) Power Optimization")
    print("=======================================================")

    rng = random.Random(0xD17A5EED)
    stim = []
    ctx = 0; pending_ctx = False; prev_en = 0
    for k in range(1200):
        if k % 150 == 0: pending_ctx = True
        en = 1 if (k % 4) < 2 else 0
        rst = 1 if k in (0, 1, 400, 401) else 0
        if pending_ctx and prev_en == 0 and not rst:
            ctx ^= 1; pending_ctx = False
        prev_en = en
        x_val = rng.randrange(-32768, 32767) & 0xFFFF
        stim.append((ctx, en, rst, (x_val >> 8) & 0xFF, x_val & 0xFF))

    with open(work / "stim.txt", "w") as f:
        for c, e, r, xh, xl in stim:
            byte0 = (c & 1) | ((e & 1) << 1) | ((r & 1) << 2)
            f.write(f"{byte0:02x} {xh:02x} {xl:02x}\n")

    (work / "dwt_power_tb.sv").write_text(DWT_TB)

    # 1. Baseline
    (work / "dwt_base.v").write_text(DWT_BASELINE)
    run_cmd(f"yosys -p 'read_verilog dwt_base.v; synth -top dwt_shared; dfflibmap -liberty {LIB}; abc -liberty {LIB}; clean; write_verilog -noattr dwt_base_sky130.v'", cwd=work)
    run_cmd(f"iverilog -g2012 -DFUNCTIONAL -DUNIT_DELAY=#1 {PRIM_V} {CELL_V} dwt_base_sky130.v dwt_power_tb.sv -o sim_base.vvp", cwd=work)
    run_cmd("vvp sim_base.vvp", cwd=work)
    os.replace(work / "activity.vcd", work / "activity_base.vcd")
    os.replace(work / "cap.txt", work / "cap_base.txt")
    base = measure_opensta_power(work, "dwt_shared", "dwt_base_sky130.v", "activity_base.vcd", "dwt_power_tb/dut")

    # 2. Power-Optimized
    (work / "dwt_opt.v").write_text(DWT_POWER_OPT)
    run_cmd(f"yosys -p 'read_verilog -lib {ICG_BOX}; read_verilog dwt_opt.v; synth -top dwt_shared; dfflibmap -liberty {LIB}; abc -liberty {LIB}; clean; write_verilog -noattr dwt_opt_sky130.v'", cwd=work)
    run_cmd(f"iverilog -g2012 -DFUNCTIONAL -DUNIT_DELAY=#1 {PRIM_V} {CELL_V} dwt_opt_sky130.v dwt_power_tb.sv -o sim_opt.vvp", cwd=work)
    run_cmd("vvp sim_opt.vvp", cwd=work)
    os.replace(work / "activity.vcd", work / "activity_opt.vcd")
    os.replace(work / "cap.txt", work / "cap_opt.txt")
    opt = measure_opensta_power(work, "dwt_shared", "dwt_opt_sky130.v", "activity_opt.vcd", "dwt_power_tb/dut")

    # Verify bit-exact equivalence
    base_cap = (work / "cap_base.txt").read_text()
    opt_cap = (work / "cap_opt.txt").read_text()
    assert base_cap == opt_cap, "Functional mismatch between baseline and power-optimized DWT!"
    print("Functional verification: BIT-EXACT MATCH across 1200 cycles!")

    delta_tot = (1.0 - opt["total_mW"] / base["total_mW"]) * 100.0
    delta_comb = (1.0 - opt["comb_mW"] / base["comb_mW"]) * 100.0
    delta_seq = (1.0 - opt["seq_mW"] / base["seq_mW"]) * 100.0
    delta_switch = (1.0 - opt["switch_mW"] / base["switch_mW"]) * 100.0

    print(f"Baseline:  Total = {base['total_mW']:.4f} mW | Comb = {base['comb_mW']:.4f} mW | Seq = {base['seq_mW']:.4f} mW | Switching = {base['switch_mW']:.4f} mW")
    print(f"Optimized: Total = {opt['total_mW']:.4f} mW | Comb = {opt['comb_mW']:.4f} mW | Seq = {opt['seq_mW']:.4f} mW | Switching = {opt['switch_mW']:.4f} mW")
    print(f"--> Total Power Drop:         {delta_tot:+.2f}%")
    print(f"--> Switching Power Drop:     {delta_switch:+.2f}%")
    print(f"--> Combinational Power Drop: {delta_comb:+.2f}%")
    print(f"--> Sequential Power Drop:    {delta_seq:+.2f}%")

    return {"base": base, "opt": opt, "delta_tot": delta_tot, "delta_switch": delta_switch, "delta_seq": delta_seq, "delta_comb": delta_comb}


def main():
    mac_res = eval_mac()
    fir_res = eval_fir()
    dwt_res = eval_dwt()

    print("\n=======================================================")
    print("CHIA MULTI-DOMAIN POWER REDUCTION SUMMARY (SKYWATER 130NM)")
    print("=======================================================")
    def describe_delta(value):
        direction = "lower" if value >= 0 else "higher"
        return f"{abs(value):.2f}% {direction}"

    print(f"1. MAC: Total = {describe_delta(mac_res['delta_tot'])} | Switching = {describe_delta(mac_res['delta_switch'])}")
    print(f"2. FIR: Total = {describe_delta(fir_res['delta_tot'])} | Switching = {describe_delta(fir_res['delta_switch'])}")
    print(f"3. DWT: Total = {describe_delta(dwt_res['delta_tot'])} | Switching = {describe_delta(dwt_res['delta_switch'])}")

    # Generate publication report markdown
    report = f"""# Preliminary Generated-Pair Power Measurements

Activity-based power measurements on **SkyWater 130nm standard cells** (`sky130_fd_sc_hd__tt_025C_1v80.lib`) using OpenSTA and cycle-accurate mapped-netlist VCD simulation. These are generated benchmark RTL pairs, not accepted PEWeaver merge candidates.

| Benchmark Domain | Baseline Power | Power-Optimized | Total Change | Switching Change | Sequential Change | Key Mechanisms |
|---|---:|---:|---:|---:|---:|---|
| **MAC** (8x8 Acc/Prod) | {mac_res['base']['total_mW']:.4f} mW | {mac_res['opt']['total_mW']:.4f} mW | **{describe_delta(mac_res['delta_tot'])}** | **{describe_delta(mac_res['delta_switch'])}** | **{describe_delta(mac_res['delta_seq'])}** | Multiplier operand isolation & adder input gating |
| **FIR** (Dual 8-Tap Q15) | {fir_res['base']['total_mW']:.4f} mW | {fir_res['opt']['total_mW']:.4f} mW | **{describe_delta(fir_res['delta_tot'])}** | **{describe_delta(fir_res['delta_switch'])}** | **{describe_delta(fir_res['delta_seq'])}** | Split-context ICG clock gating & multiplier freeze |
| **DWT** (Dual-Context db2) | {dwt_res['base']['total_mW']:.4f} mW | {dwt_res['opt']['total_mW']:.4f} mW | **{describe_delta(dwt_res['delta_tot'])}** | **{describe_delta(dwt_res['delta_switch'])}** | **{describe_delta(dwt_res['delta_seq'])}** | Active-cycle decimation operand isolation & split ICG |

### Qualification Boundary:
- The original 1200-cycle captures matched within each generated baseline/optimized pair.
- Independent controller-owned mapped-netlist qualification is archived separately in `power_reduction_independent_judge.json`.
- These measurements have no accepted-merge provenance and are not exhaustive correctness or silicon evidence.
- Optimized clock gating uses the characterized `sky130_fd_sc_hd__dlclkp_4` integrated clock latch cell; no combinational clock gating is claimed.
"""
    (WORK_BASE / "POWER_REDUCTION_REPORT.md").write_text(report)
    print(f"\nReport written to {WORK_BASE / 'POWER_REDUCTION_REPORT.md'}")


if __name__ == "__main__":
    main()
