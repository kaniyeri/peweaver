#!/usr/bin/env python3
"""Generate Paired Thermal Heatmap & GDS Layout Footprint Figures.

Produces:
  - fig4_paired_thermal_comparison.svg: Side-by-side thermal heatmaps with common color scale
  - fig5_layout_footprint_comparison.svg: Side-by-side physical layout footprints
"""

from __future__ import annotations

import json
import math
from pathlib import Path

FIG_DIR = Path(__file__).resolve().parent
SIM_DIR = FIG_DIR.parent / "thermal" / "sim_runs"


def parse_grid_file(path: Path) -> list[list[float]]:
    """Parse Layer 0 32x32 matrix from HotSpot grid steady file."""
    vals = []
    in_layer0 = False
    with open(path) as f:
        for line in f:
            if "Layer 0:" in line:
                in_layer0 = True
                continue
            if "Layer 1:" in line:
                break
            if in_layer0 and line.strip():
                parts = line.split()
                if len(parts) == 2:
                    vals.append(float(parts[1]))
    if len(vals) != 32 * 32 or not all(math.isfinite(value) for value in vals):
        raise ValueError(f"expected a finite 32x32 Layer-0 grid in {path}")
    # Reshape 32x32
    matrix = []
    for r in range(32):
        matrix.append(vals[r*32 : (r+1)*32])
    return matrix


def temp_to_color(t_k: float, t_min: float = 300.25, t_max: float = 300.55) -> str:
    """Map temperature in Kelvin to RGB hex color using a smooth thermal palette (blue -> yellow -> red)."""
    norm = max(0.0, min(1.0, (t_k - t_min) / (t_max - t_min)))
    # 4-stage palette:
    # 0.0 -> #2563eb (blue)
    # 0.33 -> #06b6d4 (cyan)
    # 0.66 -> #f59e0b (amber)
    # 1.0 -> #dc2626 (red)
    if norm < 0.33:
        f = norm / 0.33
        r = int(37 + f * (6 - 37))
        g = int(99 + f * (182 - 99))
        b = int(235 + f * (212 - 235))
    elif norm < 0.66:
        f = (norm - 0.33) / 0.33
        r = int(6 + f * (245 - 6))
        g = int(182 + f * (158 - 182))
        b = int(212 + f * (11 - 212))
    else:
        f = (norm - 0.66) / 0.34
        r = int(245 + f * (220 - 245))
        g = int(158 + f * (38 - 158))
        b = int(11 + f * (38 - 11))
    return f"#{r:02x}{g:02x}{b:02x}"


def generate_paired_thermal_svg():
    """Generate Fig 4: Paired thermal heatmaps with common color scale.
    
    Reads the CURRENT Layer-0 grid maps from the verified runner's naming
    (s0_64_amb_300K_rc1.grid.steady / a_64_amb_300K_rc1.grid.steady for the
    actual-die geometry, s0_comm_64_amb_300K_rc1.grid.steady for the common
    footprint) and computes peak callouts from the parsed data (never hard-coded).
    """
    # Prefer the audited current-runner grid files (rc=1.0 point)
    grid_a = parse_grid_file(SIM_DIR / "a_64_amb_300K_rc1.grid.steady")
    grid_s0 = parse_grid_file(SIM_DIR / "s0_comm_64_amb_300K_rc1.grid.steady")
    peak_a_mk = round((max(max(r) for r in grid_a) - 300.0) * 1e3)
    peak_s0_mk = round((max(max(r) for r in grid_s0) - 300.0) * 1e3)
    
    svg = []
    svg.append('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 460" width="800" height="460" style="background:#ffffff; font-family:sans-serif;">')
    
    # Title
    svg.append('<text x="400" y="32" font-size="16" font-weight="bold" text-anchor="middle" fill="#0f172a">Modeled On-Die Thermal Distribution: Dual Control vs. Shared Hardware</text>')
    svg.append('<text x="400" y="52" font-size="12" text-anchor="middle" fill="#64748b">Mode-64 Streaming Workload | Ambient = 300.00 K (26.85 °C) | R_convec = 1.0 K/W | HotSpot 32×32 Grid</text>')
    
    # Common color scale range
    t_min = 300.0 + min(peak_s0_mk, peak_a_mk) / 1e3 - 0.03
    t_max = 300.0 + max(peak_s0_mk, peak_a_mk) / 1e3 + 0.01
    
    # Panel 1: Dual Baseline A (Left)
    px1, py, size = 60, 90, 280
    svg.append(f'<!-- Panel A: Dual Control -->')
    svg.append(f'<text x="{px1 + size/2}" y="{py - 14}" font-size="13" font-weight="bold" text-anchor="middle" fill="#1e293b">Ungated Dual Baseline (A)</text>')
    svg.append(f'<text x="{px1 + size/2}" y="{py - 2}" font-size="11" text-anchor="middle" fill="#dc2626">Power: 61.52 mW | Footprint: 0.962 mm × 0.962 mm</text>')
    
    cell_w = size / 32.0
    for r in range(32):
        for c in range(32):
            val = grid_a[r][c]
            col = temp_to_color(val, t_min, t_max)
            x = px1 + c * cell_w
            y = py + r * cell_w
            svg.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{cell_w+0.1:.2f}" height="{cell_w+0.1:.2f}" fill="{col}"/>')
            
    # Border & Sub-block Annotations for Dual A
    svg.append(f'<rect x="{px1}" y="{py}" width="{size}" height="{size}" fill="none" stroke="#334155" stroke-width="2"/>')
    # Divider between 64 core (~38%) and 128 core (~62%)
    div_x = px1 + size * 0.38
    svg.append(f'<line x1="{div_x}" y1="{py}" x2="{div_x}" y2="{py+size}" stroke="#ffffff" stroke-width="1.5" stroke-dasharray="4"/>')
    svg.append(f'<text x="{px1 + size*0.19}" y="{py + size/2}" font-size="11" font-weight="bold" fill="#ffffff" text-anchor="middle" style="text-shadow: 1px 1px 2px #000;">Core 64\n(Active)</text>')
    svg.append(f'<text x="{px1 + size*0.69}" y="{py + size/2}" font-size="11" font-weight="bold" fill="#ffffff" text-anchor="middle" style="text-shadow: 1px 1px 2px #000;">Core 128\n(Idling Clocked)</text>')
    
    # Max temp callout for A
    svg.append(f'<rect x="{px1 + 10}" y="{py + size - 32}" width="140" height="24" rx="3" fill="#ffffff" fill-opacity="0.9"/>')
    svg.append(f'<text x="{px1 + 80}" y="{py + size - 16}" font-size="11" font-weight="bold" fill="#991b1b" text-anchor="middle">Peak Rise: +{peak_a_mk} mK</text>')

    # Panel 2: Shared S0 in Common Footprint (Right)
    px2 = 420
    svg.append(f'<!-- Panel S0: Shared Hardware -->')
    svg.append(f'<text x="{px2 + size/2}" y="{py - 14}" font-size="13" font-weight="bold" text-anchor="middle" fill="#1e293b">Shared Design (S0) in Common Outline</text>')
    svg.append(f'<text x="{px2 + size/2}" y="{py - 2}" font-size="11" text-anchor="middle" fill="#047857">Power: 39.82 mW | Core: 0.792 mm × 0.792 mm</text>')
    
    for r in range(32):
        for c in range(32):
            val = grid_s0[r][c]
            col = temp_to_color(val, t_min, t_max)
            x = px2 + c * cell_w
            y = py + r * cell_w
            svg.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{cell_w+0.1:.2f}" height="{cell_w+0.1:.2f}" fill="{col}"/>')
            
    svg.append(f'<rect x="{px2}" y="{py}" width="{size}" height="{size}" fill="none" stroke="#334155" stroke-width="2"/>')
    
    # Outline of centered active S0 core
    core_frac = 0.79179 / 0.96155
    margin_f = (1.0 - core_frac) / 2.0
    cx = px2 + size * margin_f
    cy = py + size * margin_f
    cs = size * core_frac
    svg.append(f'<rect x="{cx:.1f}" y="{cy:.1f}" width="{cs:.1f}" height="{cs:.1f}" fill="none" stroke="#ffffff" stroke-width="2" stroke-dasharray="4"/>')
    svg.append(f'<text x="{cx + cs/2}" y="{cy + cs/2}" font-size="12" font-weight="bold" fill="#ffffff" text-anchor="middle" style="text-shadow: 1px 1px 2px #000;">Shared Core S0\n(39.82 mW)</text>')
    svg.append(f'<text x="{px2 + size/2}" y="{cy - 8}" font-size="9.5" fill="#475569" text-anchor="middle">Inactive Silicon Margin (0 mW)</text>')
    
    # Max temp callout for S0
    svg.append(f'<rect x="{px2 + 10}" y="{py + size - 32}" width="140" height="24" rx="3" fill="#ffffff" fill-opacity="0.9"/>')
    svg.append(f'<text x="{px2 + 80}" y="{py + size - 16}" font-size="11" font-weight="bold" fill="#065f46" text-anchor="middle">Peak Rise: +{peak_s0_mk} mK</text>')

    # Synchronized Colorbar (Bottom)
    cb_x, cb_y, cb_w, cb_h = 180, 405, 440, 16
    svg.append('<!-- Synchronized Colorbar -->')
    svg.append(f'<text x="{cb_x - 15}" y="{cb_y + 12}" font-size="11" font-weight="bold" text-anchor="end" fill="#334155">ΔT Rise:</text>')
    
    # Draw colorbar gradient segments
    num_segs = 100
    seg_w = cb_w / num_segs
    for s in range(num_segs):
        frac = s / float(num_segs)
        val = t_min + frac * (t_max - t_min)
        col = temp_to_color(val, t_min, t_max)
        svg.append(f'<rect x="{cb_x + s * seg_w:.1f}" y="{cb_y}" width="{seg_w+0.5:.1f}" height="{cb_h}" fill="{col}"/>')
    svg.append(f'<rect x="{cb_x}" y="{cb_y}" width="{cb_w}" height="{cb_h}" fill="none" stroke="#64748b" stroke-width="1"/>')
    
    # Colorbar ticks
    for mk in [300, 350, 400, 450, 500, 550]:
        val_k = 300.0 + mk / 1000.0
        frac = (val_k - t_min) / (t_max - t_min)
        if 0.0 <= frac <= 1.0:
            tx = cb_x + frac * cb_w
            svg.append(f'<line x1="{tx:.1f}" y1="{cb_y+cb_h}" x2="{tx:.1f}" y2="{cb_y+cb_h+4}" stroke="#64748b" stroke-width="1"/>')
            svg.append(f'<text x="{tx:.1f}" y="{cb_y+cb_h+16}" font-size="10" text-anchor="middle" fill="#475569">+{mk} mK</text>')
            
    svg.append('</svg>')
    (FIG_DIR / "fig4_paired_thermal_comparison.svg").write_text("\n".join(svg))
    print(f"Generated {FIG_DIR / 'fig4_paired_thermal_comparison.svg'}")


def generate_layout_comparison_svg():
    """Generate Fig 5: Physical Layout Footprint Comparison."""
    svg = []
    svg.append('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 460" width="760" height="460" style="background:#ffffff; font-family:sans-serif;">')
    
    svg.append('<text x="380" y="32" font-size="16" font-weight="bold" text-anchor="middle" fill="#0f172a">Silicon Die Outline &amp; Core Footprint Schematic</text>')
    svg.append('<text x="380" y="52" font-size="12" text-anchor="middle" fill="#64748b">Exact Scaled Dimensions from Routed DEF &amp; GDS in SkyWater 130 nm (Illustrative Schematic)</text>')
    
    # Dimensions:
    # A: 961.55 um -> 280 px
    # Scale = 280 px / 961.55 um = 0.2912 px / um
    scale = 280.0 / 961.55
    s0_px = 791.79 * scale # ~230.5 px
    a_px = 280.0
    
    py = 85
    
    # Left: Dual A
    ax, ay = 70, py
    svg.append(f'<g transform="translate({ax},{ay})">')
    svg.append(f'<text x="{a_px/2}" y="-12" font-size="13" font-weight="bold" text-anchor="middle" fill="#1e293b">Ungated Dual Baseline (A)</text>')
    svg.append(f'<rect x="0" y="0" width="{a_px}" height="{a_px}" fill="#f1f5f9" stroke="#ef4444" stroke-width="2.5"/>')
    # Standard cell core area (~429k um2 out of 924k um2 die)
    core_w = a_px * 0.94
    core_h = a_px * 0.94
    core_off = (a_px - core_w) / 2.0
    svg.append(f'<rect x="{core_off}" y="{core_off}" width="{core_w}" height="{core_h}" fill="#fee2e2" fill-opacity="0.6" stroke="#f87171" stroke-width="1.5" stroke-dasharray="4"/>')
    
    # Core division
    div_x = core_off + core_w * 0.38
    svg.append(f'<line x1="{div_x}" y1="{core_off}" x2="{div_x}" y2="{core_off+core_h}" stroke="#ef4444" stroke-width="1.5"/>')
    svg.append(f'<text x="{core_off + core_w*0.19}" y="{a_px/2}" font-size="11" font-weight="bold" fill="#b91c1c" text-anchor="middle">FFT64 Core\n164k um²</text>')
    svg.append(f'<text x="{div_x + (core_off+core_w - div_x)/2}" y="{a_px/2}" font-size="11" font-weight="bold" fill="#b91c1c" text-anchor="middle">FFT128 Core\n260k um²</text>')
    
    # Dimension labels
    svg.append(f'<text x="{a_px/2}" y="{a_px + 20}" font-size="11" text-anchor="middle" fill="#475569">Width: 961.55 µm</text>')
    svg.append(f'<text x="-15" y="{a_px/2}" font-size="11" text-anchor="middle" transform="rotate(-90 -15 {a_px/2})" fill="#475569">Height: 961.55 µm</text>')
    
    svg.append(f'<rect x="15" y="{a_px + 32}" width="{a_px - 30}" height="42" rx="4" fill="#fef2f2" stroke="#fca5a5" stroke-width="1"/>')
    svg.append(f'<text x="{a_px/2}" y="{a_px + 48}" font-size="10.5" font-weight="bold" fill="#991b1b" text-anchor="middle">Placed Cell Area: 429,130 µm²</text>')
    svg.append(f'<text x="{a_px/2}" y="{a_px + 64}" font-size="10" fill="#7f1d1d" text-anchor="middle">Die Footprint: 924,578 µm² (53,191 cells)</text>')
    svg.append('</g>')
    
    # Right: Shared S0
    sx, sy = 430, py + (a_px - s0_px)/2.0 # Centered vertically with A
    svg.append(f'<g transform="translate({sx},{sy})">')
    svg.append(f'<text x="{s0_px/2}" y="-16" font-size="13" font-weight="bold" text-anchor="middle" fill="#1e293b">Shared Hardware (S0)</text>')
    svg.append(f'<rect x="0" y="0" width="{s0_px}" height="{s0_px}" fill="#f0fdf4" stroke="#10b981" stroke-width="2.5"/>')
    
    s0_core_w = s0_px * 0.94
    s0_core_h = s0_px * 0.94
    s0_core_off = (s0_px - s0_core_w) / 2.0
    svg.append(f'<rect x="{s0_core_off}" y="{s0_core_off}" width="{s0_core_w}" height="{s0_core_h}" fill="#dcfce7" fill-opacity="0.8" stroke="#34d399" stroke-width="1.5" stroke-dasharray="4"/>')
    svg.append(f'<text x="{s0_px/2}" y="{s0_px/2 - 6}" font-size="12" font-weight="bold" fill="#065f46" text-anchor="middle">Unified SDF Core</text>')
    svg.append(f'<text x="{s0_px/2}" y="{s0_px/2 + 12}" font-size="10.5" fill="#047857" text-anchor="middle">Reconfigurable 64 / 128</text>')
    
    svg.append(f'<text x="{s0_px/2}" y="{s0_px + 20}" font-size="11" text-anchor="middle" fill="#475569">Width: 791.79 µm</text>')
    svg.append(f'<text x="-15" y="{s0_px/2}" font-size="11" text-anchor="middle" transform="rotate(-90 -15 {s0_px/2})" fill="#475569">Height: 791.79 µm</text>')
    
    svg.append(f'<rect x="10" y="{s0_px + 32}" width="{s0_px - 20}" height="42" rx="4" fill="#ecfdf5" stroke="#6ee7b7" stroke-width="1"/>')
    svg.append(f'<text x="{s0_px/2}" y="{s0_px + 48}" font-size="10.5" font-weight="bold" fill="#065f46" text-anchor="middle">Placed Cell Area: 286,970 µm²</text>')
    svg.append(f'<text x="{s0_px/2}" y="{s0_px + 64}" font-size="10" fill="#047857" text-anchor="middle">Die Footprint: 626,931 µm² (39,886 cells)</text>')
    svg.append('</g>')
    
    # Central Comparison Callout Banner
    bx, by = 350, 190
    svg.append(f'<g transform="translate({bx},{by})">')
    svg.append('<rect x="-45" y="-35" width="90" height="70" rx="6" fill="#1e293b" stroke="#0f172a" stroke-width="1.5"/>')
    svg.append('<text x="0" y="-12" font-size="11" font-weight="bold" fill="#38bdf8" text-anchor="middle">AREA WIN</text>')
    svg.append('<text x="0" y="8" font-size="14" font-weight="bold" fill="#ffffff" text-anchor="middle">−33.1%</text>')
    svg.append('<text x="0" y="24" font-size="9" fill="#94a3b8" text-anchor="middle">Cell Area</text>')
    svg.append('</g>')
    
    svg.append('</svg>')
    (FIG_DIR / "fig5_layout_footprint_comparison.svg").write_text("\n".join(svg))
    print(f"Generated {FIG_DIR / 'fig5_layout_footprint_comparison.svg'}")


if __name__ == "__main__":
    generate_paired_thermal_svg()
    generate_layout_comparison_svg()
