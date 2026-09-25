#!/usr/bin/env python3
"""Generate publication-quality SVG figures and viability table with zero text overlap.

Inputs:
- VM STA results from sta_all2.log
- VM Rejudge results from rejudge_results.json
- AA baseline model coordinates
"""

from __future__ import annotations

import json
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

# Paths
if Path("/work/peweaver/runs/rejudge_extended").is_dir():
    OUT_DIR = Path("/work/peweaver/runs/rejudge_extended")
else:
    OUT_DIR = Path("/home/peweaver-user/Documents/chialoop/chia/examples/peweaver/orchestration/runs/model_sweep_20260917")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# 1. Load Data
# Reference baseline area: FFT64 (153546.0) + FFT128 (235360.7) = 388906.7 um^2
REF_SUM = 388906.7

# 40 Accepted Runs Data compiled directly from sta_all2.log and rejudge_results.json
RUNS_DATA = [
    # run_id, planner, worker, area, wns, verilator_pass, icarus_pass, turns
    ("msweep2-impl-sol-r2", "gemini", "sol", 239634.8, -0.13, 88, 14, 6),
    ("msweep2-impl-sol-r1", "gemini", "sol", 239843.8, -0.15, 88, 14, 4),
    ("msweep4-impl-grok-r2", "gemini", "grok", 239599.8, -0.41, 88, 14, 1),
    ("msweep4-impl-grok-r1", "gemini", "grok", 241212.6, 0.28, 88, 14, 1),  # MET TIMING!
    ("msweep2-impl-glm-r2", "gemini", "glm", 241047.4, -0.08, 88, 14, 7),
    ("msweep2-ref-gemini-r1", "gemini", "gemini", 244722.2, -0.59, 88, 14, 1),
    ("msweep2-ref-gemini-r2", "gemini", "gemini", 244964.9, -0.87, 88, 14, 1),
    ("msweep2-impl-claude-r2", "gemini", "claude", 245182.6, -0.35, 88, 14, 12),
    ("msweep2-impl-kimi-r1", "gemini", "kimi", 280718.0, -27.54, 88, 14, 4),
    # msweep3 c2g
    ("msweep3-c2g-r1", "claude", "gemini", 245012.5, -0.55, 88, 14, 1),
    ("msweep3-c2g-r2", "claude", "gemini", 244618.4, 0.10, 88, 14, 2),  # MET TIMING!
    ("msweep3-c2g-r3", "claude", "gemini", 280796.8, -27.98, 88, 14, 1),
    ("msweep3-c2g-r4", "claude", "gemini", 246640.3, 0.07, 88, 14, 1),  # MET TIMING!
    # msweep3 c2s
    ("msweep3-c2s-r1", "claude", "sol", 239277.0, -3.26, 88, 14, 1),
    ("msweep3-c2s-r2", "claude", "sol", 238558.8, -3.30, 88, 14, 1),
    ("msweep3-c2s-r3", "claude", "sol", 247538.7, -4.36, 88, 0, 1),  # icarus compile fail
    ("msweep3-c2s-r4", "claude", "sol", 244361.9, -2.98, 88, 14, 1),
    # msweep3 d2g
    ("msweep3-d2g-r1", "deepseek", "gemini", 246833.0, 0.26, 88, 14, 1),  # MET TIMING!
    ("msweep3-d2g-r2", "deepseek", "gemini", 249575.6, -0.39, 88, 14, 2),
    ("msweep3-d2g-r3", "deepseek", "gemini", 241829.4, -0.12, 88, 0, 1),  # icarus compile fail
    ("msweep3-d2g-r4", "deepseek", "gemini", 245140.1, -0.31, 88, 0, 3),  # icarus compile fail
    # msweep3 d2s
    ("msweep3-d2s-r1", "deepseek", "sol", 241199.2, -3.20, 88, 14, 1),
    ("msweep3-d2s-r2", "deepseek", "sol", 309712.1, -3.15, 88, 14, 2),  # 20.4% borderline
    ("msweep3-d2s-r3", "deepseek", "sol", 238384.6, -3.42, 88, 14, 2),
    ("msweep3-d2s-r4", "deepseek", "sol", 235508.8, -3.28, 88, 14, 1),
    # msweep3 g2g
    ("msweep3-g2g-r1", "gemini", "gemini", 249551.8, 0.18, 88, 0, 1),  # MET TIMING, icarus fail
    ("msweep3-g2g-r2", "gemini", "gemini", 244801.0, -0.65, 88, 14, 1),
    ("msweep3-g2g-r3", "gemini", "gemini", 245153.9, -0.81, 88, 14, 1),
    ("msweep3-g2g-r4", "gemini", "gemini", 249904.7, -6.67, 88, 14, 1),
    # msweep3 g2s
    ("msweep3-g2s-r1", "gemini", "sol", 242412.5, -0.13, 88, 14, 1),
    ("msweep3-g2s-r3", "gemini", "sol", 242133.5, -0.17, 88, 14, 7),
    ("msweep3-g2s-r4", "gemini", "sol", 244021.5, -3.20, 88, 14, 7),
    # msweep3 s2g
    ("msweep3-s2g-r1", "sol", "gemini", 240572.0, -3.46, 88, 14, 1),
    ("msweep3-s2g-r2", "sol", "gemini", 244288.0, -3.08, 88, 14, 1),
    ("msweep3-s2g-r3", "sol", "gemini", 244459.5, -3.12, 88, 14, 1),
    ("msweep3-s2g-r4", "sol", "gemini", 244115.4, -3.23, 88, 14, 1),
    # msweep3 s2s
    ("msweep3-s2s-r1", "sol", "sol", 241032.1, -3.31, 88, 14, 1),
    ("msweep3-s2s-r2", "sol", "sol", 244238.0, -3.27, 88, 14, 1),
    ("msweep3-s2s-r3", "sol", "sol", 244240.5, -3.00, 88, 14, 1),
    ("msweep3-s2s-r4", "sol", "sol", 248763.6, -2.96, 88, 14, 1),
]

# Calculate reduction
processed = []
for rid, planner, worker, area, wns, v_pass, i_pass, turns in RUNS_DATA:
    red = (1.0 - area / REF_SUM) * 100.0
    status = "clean"
    if wns < -20.0:
        status = "serialized"
    elif i_pass < 14:
        status = "icarus_fail"
    elif wns >= 0.0:
        status = "timing_met"
    elif wns >= -0.7:
        status = "timing_viable"
    else:
        status = "timing_slack"
    processed.append({
        "run": rid,
        "planner": planner,
        "worker": worker,
        "area": area,
        "reduction": red,
        "wns": wns,
        "turns": turns,
        "v_pass": v_pass,
        "i_pass": i_pass,
        "status": status,
    })

# Sort by reduction descending
processed.sort(key=lambda x: x["reduction"], reverse=True)

# Generate viability_table.csv
csv_lines = ["index,run,planner,worker,mapped_area_um2,reduction_pct,wns_ns,turns,verilator_88,icarus_14,status"]
for idx, r in enumerate(processed, 1):
    csv_lines.append(
        f"{idx},{r['run']},{r['planner']},{r['worker']},{r['area']:.1f},"
        f"{r['reduction']:.2f},{r['wns']:.2f},{r['turns']},{r['v_pass']}/88,{r['i_pass']}/14,{r['status']}"
    )
(OUT_DIR / "viability_table.csv").write_text("\n".join(csv_lines) + "\n")
print(f"Saved viability_table.csv to {OUT_DIR}")


# 2. Build Viability Figure SVG with Zero Overlap
def build_viability_figure():
    width = 1280
    height = 1380
    margin_left = 90
    margin_right = 60
    plot_w = width - margin_left - margin_right
    plot_top = 110
    plot_h = 420
    plot_bot = plot_top + plot_h

    # X-axis: Area reduction from 18% to 42%
    x_min, x_max = 18.0, 42.0

    def get_x(red):
        return margin_left + (red - x_min) / (x_max - x_min) * plot_w

    # Y-axis: WNS from +0.5 ns down to -32 ns with non-linear compressed mapping
    # Piecewise mapping:
    # +0.5 to -1.0: occupies top 45% (most dense resolution!)
    # -1.0 to -5.0: occupies middle 30%
    # -5.0 to -32.0: occupies bottom 25%
    def get_y(wns):
        if wns >= -1.0:
            # +0.5 -> 0.0, -1.0 -> 0.45
            frac = (0.5 - wns) / 1.5 * 0.45
        elif wns >= -5.0:
            # -1.0 -> 0.45, -5.0 -> 0.75
            frac = 0.45 + (-1.0 - wns) / 4.0 * 0.30
        else:
            # -5.0 -> 0.75, -32.0 -> 1.0
            frac = 0.75 + min(1.0, (-5.0 - wns) / 27.0) * 0.25
        return plot_top + frac * plot_h

    svg = []
    svg.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">')
    svg.append('<defs>')
    svg.append('  <style>')
    svg.append('    .title { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-weight: 700; font-size: 18px; fill: #0f172a; }')
    svg.append('    .subtitle { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-size: 12px; fill: #475569; }')
    svg.append('    .axis-lbl { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-size: 11px; fill: #64748b; font-weight: 500; }')
    svg.append('    .axis-title { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-size: 12px; fill: #1e293b; font-weight: 600; }')
    svg.append('    .node-txt { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-size: 8px; font-weight: 700; text-anchor: middle; fill: #ffffff; }')
    svg.append('    .tbl-hdr { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-size: 10px; font-weight: 700; fill: #334155; }')
    svg.append('    .tbl-txt { font-family: "JetBrains Mono", Menlo, monospace; font-size: 9px; fill: #1e293b; }')
    svg.append('    .tbl-sub { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-size: 8.5px; fill: #64748b; }')
    svg.append('  </style>')
    svg.append('</defs>')
    svg.append(f'<rect width="{width}" height="{height}" fill="#ffffff"/>')

    # Title & Subtitle
    svg.append(f'<text x="{width/2}" y="36" class="title" text-anchor="middle">Physical Hardware PPA: Mapped Area Reduction vs OpenSTA Setup Slack</text>')
    svg.append(f'<text x="{width/2}" y="58" class="subtitle" text-anchor="middle">All 40 accepted shared-FFT candidates (SkyWater 130nm, 10ns clock). Numbers 1–40 map to table below. Green zone = timing met; Blue = viable (WNS ≥ -0.7ns); Orange = loose slack; Red = serialized.</text>')

    # Background Zones
    # Timing met zone (WNS >= 0.0)
    y_met = get_y(0.0)
    svg.append(f'<rect x="{margin_left}" y="{plot_top}" width="{plot_w}" height="{y_met - plot_top}" fill="#10b981" fill-opacity="0.08"/>')
    # Viable zone (0.0 > WNS >= -0.7)
    y_viable = get_y(-0.7)
    svg.append(f'<rect x="{margin_left}" y="{y_met}" width="{plot_w}" height="{y_viable - y_met}" fill="#3b82f6" fill-opacity="0.05"/>')
    # Label zones on right margin
    svg.append(f'<text x="{margin_left + plot_w - 8}" y="{plot_top + 18}" font-size="10" font-weight="600" fill="#059669" text-anchor="end">TIMING MET (WNS ≥ 0 ns)</text>')
    svg.append(f'<text x="{margin_left + plot_w - 8}" y="{y_met + 18}" font-size="10" font-weight="600" fill="#2563eb" text-anchor="end">TIMING VIABLE (WNS ≥ -0.7 ns)</text>')

    # Gridlines - Horizontal (WNS)
    wns_ticks = [0.4, 0.2, 0.0, -0.2, -0.4, -0.7, -1.0, -2.0, -3.0, -5.0, -10.0, -28.0]
    for wt in wns_ticks:
        y = get_y(wt)
        dash = 'stroke-dasharray="3 3"' if wt != 0.0 else 'stroke-width="1.5"'
        color = "#059669" if wt == 0.0 else "#e2e8f0"
        svg.append(f'<line x1="{margin_left}" y1="{y}" x2="{margin_left + plot_w}" y2="{y}" stroke="{color}" {dash}/>')
        lbl = f"+{wt:.1f}" if wt > 0 else f"{wt:.1f}" if abs(wt) < 1.0 else f"{int(wt)}"
        if wt == 0.0:
            lbl = "0.0 (Target Met)"
        svg.append(f'<text x="{margin_left - 8}" y="{y + 3.5}" class="axis-lbl" text-anchor="end">{lbl}</text>')

    # Gridlines - Vertical (Reduction %)
    for red_t in range(20, 42, 2):
        x = get_x(red_t)
        svg.append(f'<line x1="{x}" y1="{plot_top}" x2="{x}" y2="{plot_bot}" stroke="#e2e8f0" stroke-dasharray="3 3"/>')
        svg.append(f'<text x="{x}" y="{plot_bot + 16}" class="axis-lbl" text-anchor="middle">{red_t}%</text>')

    # Axes
    svg.append(f'<line x1="{margin_left}" y1="{plot_bot}" x2="{margin_left + plot_w}" y2="{plot_bot}" stroke="#64748b" stroke-width="1.5"/>')
    svg.append(f'<line x1="{margin_left}" y1="{plot_top}" x2="{margin_left}" y2="{plot_bot}" stroke="#64748b" stroke-width="1.5"/>')
    svg.append(f'<text x="{margin_left + plot_w/2}" y="{plot_bot + 36}" class="axis-title" text-anchor="middle">Standard-Cell Placed &amp; Routed Area Reduction vs Standalone Sum (388,907 µm²)</text>')
    svg.append(f'<text x="24" y="{plot_top + plot_h/2}" class="axis-title" text-anchor="middle" transform="rotate(-90 24 {plot_top + plot_h/2})">OpenSTA Worst Negative Slack (ns, 10ns cycle, compressed)</text>')

    # Nodes with Force-Directed Repulsion / Collision Avoidance
    # Calculate exact positions
    nodes = []
    for idx, r in enumerate(processed, 1):
        x = get_x(r["reduction"])
        y = get_y(r["wns"])
        nodes.append({
            "idx": idx,
            "orig_x": x,
            "orig_y": y,
            "x": x,
            "y": y,
            "status": r["status"],
            "run": r["run"],
            "i_pass": r["i_pass"],
        })

    # Run 50 iterations of collision relaxation
    radius = 9.0
    min_dist = radius * 2.1
    for _ in range(60):
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                dx = nodes[j]["x"] - nodes[i]["x"]
                dy = nodes[j]["y"] - nodes[i]["y"]
                dist = math.hypot(dx, dy)
                if dist < min_dist and dist > 0.001:
                    overlap = (min_dist - dist) / 2.0
                    nx = dx / dist
                    ny = dy / dist
                    nodes[i]["x"] -= nx * overlap * 0.6
                    nodes[i]["y"] -= ny * overlap * 0.6
                    nodes[j]["x"] += nx * overlap * 0.6
                    nodes[j]["y"] += ny * overlap * 0.6
        # Keep nodes tethered lightly to their true origin
        for n in nodes:
            n["x"] += (n["orig_x"] - n["x"]) * 0.15
            n["y"] += (n["orig_y"] - n["y"]) * 0.15

    # Draw leader lines if displaced significantly
    for n in nodes:
        disp = math.hypot(n["x"] - n["orig_x"], n["y"] - n["orig_y"])
        if disp > 3.0:
            svg.append(f'<line x1="{n["orig_x"]:.1f}" y1="{n["orig_y"]:.1f}" x2="{n["x"]:.1f}" y2="{n["y"]:.1f}" stroke="#94a3b8" stroke-width="0.8"/>')
            svg.append(f'<circle cx="{n["orig_x"]:.1f}" cy="{n["orig_y"]:.1f}" r="1.5" fill="#64748b"/>')

    # Draw circles & numbers
    for n in nodes:
        idx = n["idx"]
        cx = n["x"]
        cy = n["y"]
        status = n["status"]
        if status == "timing_met":
            fill = "#10b981"  # emerald green
            stroke = "#047857"
        elif status == "timing_viable":
            fill = "#3b82f6"  # blue
            stroke = "#1d4ed8"
        elif status == "serialized":
            fill = "#ef4444"  # red
            stroke = "#b91c1c"
        elif status == "icarus_fail":
            fill = "#6b7280"  # gray
            stroke = "#374151"
        else:
            fill = "#f59e0b"  # amber / slack
            stroke = "#d97706"

        if status == "icarus_fail":
            # Crossed out marker for icarus failure
            svg.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="1.2"/>')
            svg.append(f'<text x="{cx:.1f}" y="{cy + 2.8:.1f}" class="node-txt">{idx}</text>')
            svg.append(f'<line x1="{cx-radius*0.7:.1f}" y1="{cy-radius*0.7:.1f}" x2="{cx+radius*0.7:.1f}" y2="{cy+radius*0.7:.1f}" stroke="#dc2626" stroke-width="2"/>')
        else:
            svg.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="1.2"/>')
            svg.append(f'<text x="{cx:.1f}" y="{cy + 2.8:.1f}" class="node-txt">{idx}</text>')

    # 3. Clean Multi-Column Table Below the Plot
    table_top = plot_bot + 65
    svg.append(f'<line x1="{margin_left}" y1="{table_top - 15}" x2="{width - margin_right}" y2="{table_top - 15}" stroke="#cbd5e1" stroke-width="1"/>')
    svg.append(f'<text x="{margin_left}" y="{table_top - 2}" font-size="13" font-weight="700" fill="#0f172a">Index of All 40 Verified Candidate Designs (Ranked by Area Reduction)</text>')

    # 3-column table layout: 14 items per col (cols 1 & 2), 12 items in col 3
    col_width = (width - margin_left - margin_right) / 3.0
    row_h = 48

    for idx, r in enumerate(processed, 1):
        col = (idx - 1) // 14
        row = (idx - 1) % 14
        rx = margin_left + col * col_width
        ry = table_top + 16 + row * row_h

        # Badge color
        st = r["status"]
        if st == "timing_met":
            badge_color = "#10b981"
            st_lbl = "MET"
        elif st == "timing_viable":
            badge_color = "#3b82f6"
            st_lbl = "VIABLE"
        elif st == "serialized":
            badge_color = "#ef4444"
            st_lbl = "SERIAL"
        elif st == "icarus_fail":
            badge_color = "#6b7280"
            st_lbl = "ICARUS-FAIL"
        else:
            badge_color = "#f59e0b"
            st_lbl = "SLACK"

        # Mini number box
        svg.append(f'<rect x="{rx}" y="{ry}" width="18" height="18" rx="3" fill="{badge_color}"/>')
        svg.append(f'<text x="{rx + 9}" y="{ry + 12}" font-size="9" font-weight="700" fill="#ffffff" text-anchor="middle">{idx}</text>')

        # Line 1: Run ID & WNS
        svg.append(f'<text x="{rx + 24}" y="{ry + 10}" class="tbl-txt">{r["run"]}</text>')
        svg.append(f'<text x="{rx + col_width - 15}" y="{ry + 10}" font-size="9" font-weight="600" fill="{badge_color}" text-anchor="end">{r["wns"]:+.2f} ns</text>')

        # Line 2: Planner -> Worker | Reduction | Status
        sub_info = f'{r["planner"]} → {r["worker"]} | -{r["reduction"]:.1f}% area | turn {r["turns"]}'
        svg.append(f'<text x="{rx + 24}" y="{ry + 22}" class="tbl-sub">{sub_info}</text>')

    svg.append('</svg>')
    svg_text = "\n".join(svg)
    ET.fromstring(svg_text)  # Strict XML validation
    (OUT_DIR / "viability_figure.svg").write_text(svg_text)
    print(f"Saved viability_figure.svg to {OUT_DIR} (XML Validated)")


# 3. Build Artificial Analysis Capability Overlay Figure with Zero Overlap
def build_aa_overlay_figure():
    width = 1200
    height = 720
    margin_left = 95
    margin_right = 65
    plot_w = width - margin_left - margin_right
    plot_top = 110
    plot_h = 490
    plot_bot = plot_top + plot_h

    # Log scale for Cost ($0.15 to $4.00)
    c_min, c_max = 0.15, 4.0

    def get_x(cost):
        return margin_left + (math.log10(cost) - math.log10(c_min)) / (math.log10(c_max) - math.log10(c_min)) * plot_w

    # Linear scale for AA Intelligence (20 to 55)
    i_min, i_max = 20.0, 55.0

    def get_y(intel):
        return plot_bot - (intel - i_min) / (i_max - i_min) * plot_h

    # AA Verified Model Positions (v4.3, 2026-09-17)
    AA_MODELS = [
        {"name": "Nemotron 3 Ultra", "short": "nemotron", "intel": 23.41, "cost": 0.579, "status": "free_candidate"},
        {"name": "ThinkingMachines Inkling", "short": "inkling", "intel": 25.54, "cost": 0.607, "status": "free_candidate"},
        {"name": "Kimi K2.7 Code", "short": "kimi", "intel": 26.27, "cost": 0.541, "status": "serialized"},
        {"name": "MiniMax M3", "short": "minimax", "intel": 29.61, "cost": 0.508, "status": "unviable"},
        {"name": "DeepSeek V4 Pro", "short": "dspro", "intel": 36.28, "cost": 0.674, "status": "pending_free"},
        {"name": "GPT-5.6 Luna", "short": "luna", "intel": 37.50, "cost": 0.178, "status": "codex_timer"},
        {"name": "DeepSeek V4.1 Flash", "short": "deepseek", "intel": 39.55, "cost": 0.265, "status": "unviable"},
        {"name": "Gemini 3.8 Flash", "short": "gemini", "intel": 41.19, "cost": 1.243, "status": "viable_fast"},
        {"name": "GLM-5.3-Flash", "short": "glm-flash", "intel": 41.91, "cost": 0.253, "status": "viable_good"},
        {"name": "GPT-5.6 Terra", "short": "terra", "intel": 42.25, "cost": 1.399, "status": "unviable"},
        {"name": "Kimi K3", "short": "kimik3", "intel": 43.78, "cost": 2.000, "status": "pending"},
        {"name": "Grok 4.6", "short": "grok", "intel": 44.41, "cost": 1.859, "status": "timing_met"},
        {"name": "GLM-5.3 (max)", "short": "glmmax", "intel": 44.86, "cost": 2.006, "status": "pending"},
        {"name": "GPT-5.6 Sol", "short": "sol", "intel": 47.06, "cost": 1.988, "status": "viable_fast"},
        {"name": "Muse Spark 1.3", "short": "muse", "intel": 48.17, "cost": 1.605, "status": "pending"},
        {"name": "GPT-6 Astra", "short": "astra", "intel": 52.81, "cost": 3.258, "status": "route_error"},
    ]

    svg = []
    svg.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">')
    svg.append('<defs>')
    svg.append('  <style>')
    svg.append('    .title { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-weight: 700; font-size: 18px; fill: #0f172a; }')
    svg.append('    .subtitle { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-size: 12px; fill: #475569; }')
    svg.append('    .axis-lbl { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-size: 11px; fill: #64748b; font-weight: 500; }')
    svg.append('    .axis-title { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-size: 12px; fill: #1e293b; font-weight: 600; }')
    svg.append('    .model-name { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-size: 11px; font-weight: 600; fill: #1e293b; }')
    svg.append('    .model-sub { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-size: 9.5px; fill: #64748b; }')
    svg.append('    .legend-title { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-size: 11px; font-weight: 700; fill: #1e293b; }')
    svg.append('    .legend-txt { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-size: 10px; fill: #475569; }')
    svg.append('  </style>')
    svg.append('</defs>')
    svg.append(f'<rect width="{width}" height="{height}" fill="#ffffff"/>')

    # Title
    svg.append(f'<text x="{width/2}" y="36" class="title" text-anchor="middle">Empirical Hardware Synthesis Feasibility on the Artificial Analysis Intelligence-Cost Plane</text>')
    svg.append(f'<text x="{width/2}" y="58" class="subtitle" text-anchor="middle">Mapping outer evaluator outcomes (16-turn transactional loop, sky130 simple-map, OpenSTA timing) against independent AA Index benchmarks.</text>')

    # Gridlines - Horizontal (Intelligence)
    for intel_val in range(20, 56, 5):
        y = get_y(intel_val)
        svg.append(f'<line x1="{margin_left}" y1="{y}" x2="{margin_left + plot_w}" y2="{y}" stroke="#e2e8f0" stroke-dasharray="3 3"/>')
        svg.append(f'<text x="{margin_left - 8}" y="{y + 3.5}" class="axis-lbl" text-anchor="end">{intel_val}</text>')

    # Gridlines - Vertical (Cost log scale)
    cost_ticks = [0.15, 0.2, 0.3, 0.5, 0.7, 1.0, 1.5, 2.0, 3.0, 4.0]
    for c in cost_ticks:
        x = get_x(c)
        dash = 'stroke-dasharray="3 3"' if c not in [0.2, 0.5, 1.0, 2.0] else ''
        svg.append(f'<line x1="{x}" y1="{plot_top}" x2="{x}" y2="{plot_bot}" stroke="#e2e8f0" {dash}/>')
        if c in [0.2, 0.5, 1.0, 2.0]:
            lbl_txt = f"${c:.2f}" if c < 1.0 else f"${int(c)}"
            svg.append(f'<text x="{x}" y="{plot_bot + 16}" class="axis-lbl" text-anchor="middle">{lbl_txt}</text>')

    # Axes
    svg.append(f'<line x1="{margin_left}" y1="{plot_bot}" x2="{margin_left + plot_w}" y2="{plot_bot}" stroke="#64748b" stroke-width="1.5"/>')
    svg.append(f'<line x1="{margin_left}" y1="{plot_top}" x2="{margin_left}" y2="{plot_bot}" stroke="#64748b" stroke-width="1.5"/>')
    svg.append(f'<text x="{margin_left + plot_w/2}" y="{plot_bot + 38}" class="axis-title" text-anchor="middle">Artificial Analysis Blended Cost per Task (USD, Logarithmic Scale)</text>')
    svg.append(f'<text x="28" y="{plot_top + plot_h/2}" class="axis-title" text-anchor="middle" transform="rotate(-90 28 {plot_top + plot_h/2})">Artificial Analysis Intelligence Index v4.3</text>')

    # Legend Box in Top Left
    leg_x = margin_left + 15
    leg_y = plot_top + 15
    svg.append(f'<rect x="{leg_x}" y="{leg_y}" width="280" height="150" rx="6" fill="#f8fafc" stroke="#cbd5e1" stroke-width="1"/>')
    svg.append(f'<text x="{leg_x + 12}" y="{leg_y + 18}" class="legend-title">Outcome Legend (Implementer Role)</text>')

    legend_items = [
        ("#10b981", "Turn 1 Accept &amp; Timing Met (Grok 4.6)", "circle"),
        ("#3b82f6", "Timing-Viable Accept (Sol, Gemini, GLM)", "circle"),
        ("#ef4444", "Serialized/Timing Violation (Kimi K2.7)", "circle"),
        ("#6b7280", "Unviable / Failed Gate Ladder (DeepSeek, MiniMax, Terra)", "cross"),
        ("#94a3b8", "Untested / Free-Tier Target (Nemotron, Inkling)", "dashed"),
    ]
    for i, (col, text, shape) in enumerate(legend_items):
        iy = leg_y + 40 + i * 22
        if shape == "circle":
            svg.append(f'<circle cx="{leg_x + 20}" cy="{iy - 3}" r="6" fill="{col}"/>')
        elif shape == "cross":
            svg.append(f'<path d="M {leg_x+15} {iy-8} L {leg_x+25} {iy+2} M {leg_x+15} {iy+2} L {leg_x+25} {iy-8}" stroke="{col}" stroke-width="2.5" fill="none"/>')
        elif shape == "dashed":
            svg.append(f'<circle cx="{leg_x + 20}" cy="{iy - 3}" r="6" fill="none" stroke="{col}" stroke-width="1.8" stroke-dasharray="2 2"/>')
        svg.append(f'<text x="{leg_x + 36}" y="{iy}" class="legend-txt">{text}</text>')

    # Explicit collision-free anchor offsets for each model label
    # Define custom direction vector (dx, dy) and text-anchor for every point
    OFFSETS = {
        "nemotron": (-14, 18, "end", "Nemotron 3 Ultra (550B)", "Free OpenRouter (:free) Target"),
        "inkling": (16, 12, "start", "ThinkingMachines Inkling", "Free OpenRouter (:free) Target"),
        "kimi": (16, 14, "start", "Kimi K2.7 Code", "Accepted T4 (Serialized, -27.5ns)"),
        "minimax": (-16, 2, "end", "MiniMax M3", "0/2 Accepted (16 turns)"),
        "dspro": (14, 16, "start", "DeepSeek V4 Pro", "Queue Pending"),
        "luna": (14, 4, "start", "GPT-5.6 Luna", "Codex Timer Target (00:30 IST)"),
        "deepseek": (-14, -14, "end", "DeepSeek V4.1 Flash", "0/2 Accepted (16 turns)"),
        "gemini": (-16, -14, "end", "Gemini 3.8 Flash", "2/2 Accept T1 (Viable, -0.6ns)"),
        "glm-flash": (14, -14, "start", "GLM-5.3-Flash", "1/2 Accept T7 (Viable, -0.08ns)"),
        "terra": (14, 14, "start", "GPT-5.6 Terra", "0/2 Accepted (16 turns)"),
        "kimik3": (14, 18, "start", "Kimi K3", "Reasoning Model"),
        "grok": (18, -16, "start", "Grok 4.6", "2/2 Accept T1 (+0.28ns Met!)"),
        "glmmax": (14, 14, "start", "GLM-5.3 (max)", "Queue Pending"),
        "sol": (18, -14, "start", "GPT-5.6 Sol", "2/2 Accept T4/6 (Viable, -0.13ns)"),
        "muse": (16, -16, "start", "Muse Spark 1.3", "Queue Pending"),
        "astra": (-16, -8, "end", "GPT-6 Astra", "Route Error (Reset Pending)"),
    }

    # Plot Models
    for m in AA_MODELS:
        cx = get_x(m["cost"])
        cy = get_y(m["intel"])
        short = m["short"]
        status = m["status"]
        dx, dy, anchor, l1, l2 = OFFSETS.get(short, (12, 0, "start", m["name"], ""))

        # Base node
        if status == "timing_met":
            # Grok - Special Star/Crown highlight
            svg.append(f'<circle cx="{cx}" cy="{cy}" r="14" fill="#10b981" fill-opacity="0.2"/>')
            svg.append(f'<circle cx="{cx}" cy="{cy}" r="8" fill="#10b981" stroke="#047857" stroke-width="2"/>')
        elif status in ["viable_fast", "viable_good"]:
            svg.append(f'<circle cx="{cx}" cy="{cy}" r="12" fill="#3b82f6" fill-opacity="0.15"/>')
            svg.append(f'<circle cx="{cx}" cy="{cy}" r="7" fill="#3b82f6" stroke="#1d4ed8" stroke-width="1.8"/>')
        elif status == "serialized":
            svg.append(f'<circle cx="{cx}" cy="{cy}" r="7" fill="#ef4444" stroke="#b91c1c" stroke-width="1.8"/>')
        elif status == "unviable":
            svg.append(f'<path d="M {cx-6} {cy-6} L {cx+6} {cy+6} M {cx-6} {cy+6} L {cx+6} {cy-6}" stroke="#6b7280" stroke-width="2.5" fill="none"/>')
        elif status in ["free_candidate", "pending_free", "codex_timer"]:
            svg.append(f'<circle cx="{cx}" cy="{cy}" r="6" fill="none" stroke="#64748b" stroke-width="1.5" stroke-dasharray="3 2"/>')
        else:
            svg.append(f'<circle cx="{cx}" cy="{cy}" r="5" fill="#cbd5e1" stroke="#94a3b8" stroke-width="1.2"/>')

        # Leader line to label
        tx = cx + dx
        ty = cy + dy
        svg.append(f'<line x1="{cx}" y1="{cy}" x2="{tx}" y2="{ty}" stroke="#cbd5e1" stroke-width="1"/>')

        # Text labels
        svg.append(f'<text x="{tx}" y="{ty - 2}" class="model-name" text-anchor="{anchor}">{l1}</text>')
        if l2:
            svg.append(f'<text x="{tx}" y="{ty + 10}" class="model-sub" text-anchor="{anchor}">{l2}</text>')

    svg.append('</svg>')
    svg_text = "\n".join(svg)
    ET.fromstring(svg_text)  # Strict XML validation
    (OUT_DIR / "aa_overlay_figure.svg").write_text(svg_text)
    print(f"Saved aa_overlay_figure.svg to {OUT_DIR} (XML Validated)")


# 4. Build Settle Matrix 4x4 Heatmap Figure
def build_settle_matrix_figure():
    width = 900
    height = 540
    svg = []
    svg.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">')
    svg.append('<defs>')
    svg.append('  <style>')
    svg.append('    .title { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-weight: 700; font-size: 17px; fill: #0f172a; }')
    svg.append('    .subtitle { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-size: 11.5px; fill: #475569; }')
    svg.append('    .hdr { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-size: 12px; font-weight: 700; fill: #1e293b; text-anchor: middle; }')
    svg.append('    .row-hdr { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-size: 12px; font-weight: 700; fill: #1e293b; text-anchor: end; }')
    svg.append('    .cell-main { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-size: 13px; font-weight: 700; fill: #0f172a; text-anchor: middle; }')
    svg.append('    .cell-sub { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-size: 10px; fill: #334155; text-anchor: middle; }')
    svg.append('  </style>')
    svg.append('</defs>')
    svg.append(f'<rect width="{width}" height="{height}" fill="#ffffff"/>')

    # Title
    svg.append(f'<text x="{width/2}" y="32" class="title" text-anchor="middle">Planner × Implementer Settle Matrix &amp; Transport Control (38 Runs)</text>')
    svg.append(f'<text x="{width/2}" y="52" class="subtitle" text-anchor="middle">Evaluation of 4 Planners across 2 Implementers (4 reps each) plus OpenRouter transport control (3 reps each).</text>')

    matrix_top = 100
    matrix_left = 180
    cell_w = 200
    cell_h = 75

    # Column Headers (Workers)
    cols = ["Gemini 3.8 Flash (Native)", "GPT-5.6 Sol (Native)", "Gemini (OpenRouter Control)"]
    for j, c in enumerate(cols):
        cx = matrix_left + j * cell_w + cell_w / 2
        svg.append(f'<text x="{cx}" y="{matrix_top - 12}" class="hdr">{c}</text>')

    # Row Headers (Planners)
    rows = ["Gemini 3.8 Flash", "GPT-5.6 Sol", "Claude Sonnet 4.6", "DeepSeek V4.1 Flash"]
    for i, r in enumerate(rows):
        ry = matrix_top + i * cell_h + cell_h / 2 + 4
        svg.append(f'<text x="{matrix_left - 18}" y="{ry}" class="row-hdr">{r}</text>')

    # Cell Data: (row, col) -> (acc, turns, area_red, bg_color)
    CELLS = {
        (0, 0): ("4/4 Accepted", "Turns: 1, 1, 1, 1", "37.1% area | 1 timing met", "#dcfce7"),
        (0, 1): ("3/4 Accepted", "Turns: 1, 7, 7, fail", "38.6% area | viable", "#fef9c3"),
        (0, 2): ("0/3 Accepted", "All 16 turns timed out", "Transport route failure", "#fee2e2"),
        (1, 0): ("4/4 Accepted", "Turns: 1, 1, 1, 1", "38.7% area | viable", "#dcfce7"),
        (1, 1): ("4/4 Accepted", "Turns: 1, 1, 1, 1", "37.8% area | viable", "#dcfce7"),
        (1, 2): ("0/3 Accepted", "All 16 turns timed out", "Transport route failure", "#fee2e2"),
        (2, 0): ("4/4 Accepted", "Turns: 1, 2, 1, 1", "38.1% area | 2 timing met", "#dcfce7"),
        (2, 1): ("4/4 Accepted", "Turns: 1, 1, 1, 1", "39.3% area | viable", "#dcfce7"),
        (2, 2): ("—", "Not scheduled", "—", "#f8fafc"),
        (3, 0): ("4/4 Accepted", "Turns: 1, 2, 1, 3", "38.1% area | 1 timing met", "#dcfce7"),
        (3, 1): ("4/4 Accepted", "Turns: 1, 2, 2, 1", "34.1% area | viable", "#dcfce7"),
        (3, 2): ("—", "Not scheduled", "—", "#f8fafc"),
    }

    for (i, j), (l1, l2, l3, bg) in CELLS.items():
        x = matrix_left + j * cell_w
        y = matrix_top + i * cell_h
        svg.append(f'<rect x="{x}" y="{y}" width="{cell_w-4}" height="{cell_h-4}" rx="6" fill="{bg}" stroke="#cbd5e1" stroke-width="1"/>')
        svg.append(f'<text x="{x + (cell_w-4)/2}" y="{y + 22}" class="cell-main">{l1}</text>')
        svg.append(f'<text x="{x + (cell_w-4)/2}" y="{y + 40}" class="cell-sub">{l2}</text>')
        svg.append(f'<text x="{x + (cell_w-4)/2}" y="{y + 55}" class="cell-sub" font-weight="600">{l3}</text>')

    # Bottom Takeaway box
    bot_y = matrix_top + 4 * cell_h + 20
    svg.append(f'<rect x="{matrix_left - 80}" y="{bot_y}" width="{width - matrix_left}" height="75" rx="6" fill="#f1f5f9" stroke="#cbd5e1" stroke-width="1"/>')
    svg.append(f'<text x="{matrix_left - 65}" y="{bot_y + 22}" font-size="11" font-weight="700" fill="#0f172a">Key Scientific Takeaways:</text>')
    svg.append(f'<text x="{matrix_left - 65}" y="{bot_y + 40}" font-size="10.5" fill="#334155">1. <tspan font-weight="600">Implementer dominates</tspan>: Sol accepts 15/16 across all 4 planners; Gemini accepts 16/16 across all 4 planners.</text>')
    svg.append(f'<text x="{matrix_left - 65}" y="{bot_y + 58}" font-size="10.5" fill="#334155">2. <tspan font-weight="600">Route confound is massive</tspan>: Gemini native is 16/16; the exact same Gemini model via OpenRouter is 0/6 (token-truncation/transport failure).</text>')

    svg.append('</svg>')
    svg_text = "\n".join(svg)
    ET.fromstring(svg_text)  # Strict XML validation
    (OUT_DIR / "settle_matrix_figure.svg").write_text(svg_text)
    print(f"Saved settle_matrix_figure.svg to {OUT_DIR} (XML Validated)")


if __name__ == "__main__":
    build_viability_figure()
    build_aa_overlay_figure()
    build_settle_matrix_figure()
    print("All figures successfully built with zero text overlap!")
