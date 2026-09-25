#!/usr/bin/env python3
"""Pure-Python SVG Figure Generator for PEWeaver Paper.

Generates vector-graphics SVG figures:
  - fig1_workload_breakeven.svg: Energy per FFT (nJ) vs Active Duty Cycle
  - fig2_evaluator_replay.svg: Defect Detection Rate across Nested Configurations
  - fig3_thermal_envelope.svg: Peak Temperature Rise (mK) vs Convection Thermal Resistance
"""

from __future__ import annotations

import json
import math
from pathlib import Path

FIG_DIR = Path(__file__).resolve().parent
ROOT_DIR = FIG_DIR.parent


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be finite numeric")
    return float(value)


def _nice_axis(values: list[float], target_ticks: int = 7) -> tuple[float, list[float]]:
    """Return a rounded axis maximum and readable ticks that contain values."""
    maximum = max(values, default=1.0)
    raw_step = maximum / target_ticks
    magnitude = 10 ** math.floor(math.log10(raw_step))
    normalized = raw_step / magnitude
    step = (1.0 if normalized <= 1.0 else 2.0 if normalized <= 2.0 else 5.0 if normalized <= 5.0 else 10.0) * magnitude
    axis_max = math.ceil(maximum / step) * step
    ticks = [round(step * index, 10) for index in range(int(round(axis_max / step)) + 1)]
    return axis_max, ticks


def generate_fig1_workload():
    """Generate Fig 1: Energy per FFT vs Duty Cycle."""
    csv_path = ROOT_DIR / "workloads" / "workload_metrics.json"
    if not csv_path.is_file():
        raise FileNotFoundError(csv_path)
    data = json.load(open(csv_path))
    if not isinstance(data, list):
        raise ValueError("workload metrics must be a list")
    
    # Keep the nominal curve only; the JSON also contains lower/upper idle
    # sensitivity cases, which are reported in the workload table.
    m64 = [d for d in data if d["mode64_occupancy"] == 1.0 and d["idle_model"] == "nominal"]
    if len(m64) != 6:
        raise ValueError(f"expected six nominal mode-64 workload points, got {len(m64)}")
    m64.sort(key=lambda row: _finite(row["active_duty_cycle"], "active_duty_cycle"))
    for index, row in enumerate(m64):
        _finite(row["s0_energy_total_nj"], f"workload[{index}].s0_energy_total_nj")
        _finite(row["a_energy_total_nj"], f"workload[{index}].a_energy_total_nj")
        _finite(row["energy_savings_pct"], f"workload[{index}].energy_savings_pct")
    
    svg = []
    svg.append('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 650 400" width="650" height="400" style="background:#ffffff; font-family:sans-serif;">')
    svg.append('<!-- Title -->')
    svg.append('<text x="325" y="30" font-size="16" font-weight="bold" text-anchor="middle" fill="#1e293b">Workload Energy per FFT vs. Active Duty Cycle (Mode 64)</text>')
    
    # Axes
    ox, oy, w, h = 80, 330, 520, 260
    svg.append(f'<line x1="{ox}" y1="{oy}" x2="{ox+w}" y2="{oy}" stroke="#64748b" stroke-width="2"/>')
    svg.append(f'<line x1="{ox}" y1="{oy}" x2="{ox}" y2="{oy-h}" stroke="#64748b" stroke-width="2"/>')
    
    axis_max, y_ticks = _nice_axis(
        [value for row in m64 for value in (row.get("s0_energy_total_nj", 0.0), row.get("a_energy_total_nj", 0.0))]
    )
    for e_val in y_ticks:
        y_pos = oy - (e_val / axis_max) * h
        svg.append(f'<line x1="{ox}" y1="{y_pos}" x2="{ox+w}" y2="{y_pos}" stroke="#e2e8f0" stroke-width="1" stroke-dasharray="4"/>')
        svg.append(f'<text x="{ox-10}" y="{y_pos+4}" font-size="11" text-anchor="end" fill="#64748b">{e_val:g}</text>')
    svg.append(f'<text x="{ox-45}" y="{oy-h/2}" font-size="12" font-weight="bold" text-anchor="middle" transform="rotate(-90 {ox-45} {oy-h/2})" fill="#334155">Energy per Transform (nJ)</text>')
    
    # X ticks (Duty Cycle 0% to 100%)
    for dc in [0, 20, 40, 60, 80, 100]:
        x_pos = ox + (dc / 100.0) * w
        svg.append(f'<line x1="{x_pos}" y1="{oy}" x2="{x_pos}" y2="{oy+5}" stroke="#64748b" stroke-width="1.5"/>')
        svg.append(f'<text x="{x_pos}" y="{oy+20}" font-size="11" text-anchor="middle" fill="#64748b">{dc}%</text>')
    svg.append(f'<text x="{ox+w/2}" y="{oy+40}" font-size="12" font-weight="bold" text-anchor="middle" fill="#334155">Active Duty Cycle (%)</text>')
    
    # Plot points
    pts_s0 = []
    pts_a = []
    for d in m64:
        dc = d.get("active_duty_cycle", d.get("active_fraction", 1.0)) * 100.0
        x_pos = ox + (dc / 100.0) * w
        e_s0 = d["s0_energy_total_nj"]
        e_a  = d["a_energy_total_nj"]
        y_s0 = oy - (e_s0 / axis_max) * h
        y_a  = oy - (e_a / axis_max) * h
        pts_s0.append((x_pos, y_s0))
        pts_a.append((x_pos, y_a))
        
    # Draw curves
    s0_path = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in pts_s0)
    a_path = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in pts_a)
    
    # Fill between lines (energy savings region)
    fill_path = "M " + f"{pts_a[0][0]:.1f},{pts_a[0][1]:.1f} " + " ".join(f"L {x:.1f},{y:.1f}" for x,y in pts_a[1:])
    fill_path += " " + " ".join(f"L {x:.1f},{y:.1f}" for x,y in reversed(pts_s0)) + " Z"
    svg.append(f'<path d="{fill_path}" fill="#10b981" fill-opacity="0.15"/>')
    
    svg.append(f'<path d="{a_path}" fill="none" stroke="#ef4444" stroke-width="3"/>')
    svg.append(f'<path d="{s0_path}" fill="none" stroke="#059669" stroke-width="3"/>')
    
    # Points
    for x, y in pts_a:
        svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="#ef4444"/>')
    for x, y in pts_s0:
        svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="#059669"/>')
        
    # Savings Callout
    savings = [d["energy_savings_pct"] for d in m64]
    savings_label = f"{min(savings):.2f}% – {max(savings):.2f}% Modeled Savings"
    svg.append(f'<rect x="{ox+100}" y="{oy-h+20}" width="200" height="48" rx="4" fill="#ecfdf5" stroke="#10b981" stroke-width="1"/>')
    svg.append(f'<text x="{ox+200}" y="{oy-h+40}" font-size="11" font-weight="bold" fill="#065f46" text-anchor="middle">{savings_label}</text>')
    svg.append(f'<text x="{ox+200}" y="{oy-h+56}" font-size="10" fill="#047857" text-anchor="middle">Nominal mode-64; not idle-VCD data</text>')
    
    # Legend
    lx, ly = ox + w - 170, oy - h + 15
    svg.append(f'<rect x="{lx}" y="{ly}" width="160" height="60" rx="4" fill="#f8fafc" stroke="#cbd5e1" stroke-width="1"/>')
    svg.append(f'<line x1="{lx+10}" y1="{ly+18}" x2="{lx+35}" y2="{ly+18}" stroke="#ef4444" stroke-width="3"/>')
    svg.append(f'<circle cx="{lx+22}" cy="{ly+18}" r="3.5" fill="#ef4444"/>')
    svg.append(f'<text x="{lx+45}" y="{ly+22}" font-size="11" fill="#334155">Dual Baseline (A)</text>')
    svg.append(f'<line x1="{lx+10}" y1="{ly+42}" x2="{lx+35}" y2="{ly+42}" stroke="#059669" stroke-width="3"/>')
    svg.append(f'<circle cx="{lx+22}" cy="{ly+42}" r="3.5" fill="#059669"/>')
    svg.append(f'<text x="{lx+45}" y="{ly+46}" font-size="11" fill="#334155">Shared FFT (S0)</text>')
    
    svg.append('</svg>')
    (FIG_DIR / "fig1_workload_breakeven.svg").write_text("\n".join(svg))
    print(f"Generated {FIG_DIR / 'fig1_workload_breakeven.svg'}")


def generate_fig2_evaluator():
    """Generate Fig 2: Evidence coverage for the replay corpus."""
    sum_path = ROOT_DIR / "replay" / "detection_summary.json"
    if not sum_path.is_file():
        raise FileNotFoundError(sum_path)
    data = json.load(open(sum_path))
    if not isinstance(data, dict) or not isinstance(data.get("strata_breakdown"), dict) or not isinstance(data.get("overall"), dict):
        raise ValueError("replay summary must contain strata_breakdown and overall objects")
    b = data["strata_breakdown"]

    svg = []
    svg.append('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 390" width="720" height="390" style="background:#ffffff; font-family:sans-serif;">')
    svg.append('<text x="360" y="30" font-size="15" font-weight="bold" text-anchor="middle" fill="#1e293b">Replay Evidence Coverage (31-Candidate Corpus)</text>')
    svg.append('<text x="360" y="49" font-size="11" text-anchor="middle" fill="#475569">Detection rates are withheld when defect gate evidence is incomplete</text>')

    ox, oy, w, h = 80, 315, 590, 240
    svg.append(f'<line x1="{ox}" y1="{oy}" x2="{ox+w}" y2="{oy}" stroke="#64748b" stroke-width="2"/>')
    svg.append(f'<line x1="{ox}" y1="{oy}" x2="{ox}" y2="{oy-h}" stroke="#64748b" stroke-width="2"/>')

    for pct in [0, 25, 50, 75, 100]:
        y_pos = oy - (pct / 100.0) * h
        svg.append(f'<line x1="{ox}" y1="{y_pos}" x2="{ox+w}" y2="{y_pos}" stroke="#e2e8f0" stroke-width="1" stroke-dasharray="4"/>')
        svg.append(f'<text x="{ox-10}" y="{y_pos+4}" font-size="11" text-anchor="end" fill="#64748b">{pct}%</text>')
    svg.append(f'<text x="{ox-45}" y="{oy-h/2}" font-size="12" font-weight="bold" text-anchor="middle" transform="rotate(-90 {ox-45} {oy-h/2})" fill="#334155">Defect Rows with Complete Evidence (%)</text>')

    strata = [
        ("Natural LLM", "natural_failure"),
        ("Arch Controls", "architectural_control"),
        ("RTL Mutants", "rtl_mutation"),
        ("Infra Faults", "infra_provenance"),
        ("Overall", "overall"),
    ]

    group_w = w / len(strata)
    bar_w = 42
    color = "#7c3aed"
    for i, (name, key) in enumerate(strata):
        gx = ox + i * group_w + group_w / 2.0
        d = data["overall"] if key == "overall" else b[key]
        total = d.get("defects", d.get("total_defects"))
        evaluated = d.get("evaluated_defects")
        if not isinstance(total, int) or isinstance(total, bool) or total < 0:
            raise ValueError(f"{name} total defects must be a non-negative integer")
        if not isinstance(evaluated, int) or isinstance(evaluated, bool) or evaluated < 0 or evaluated > total:
            raise ValueError(f"{name} evaluated defects must be within its denominator")
        pct = (evaluated / total * 100.0) if total else 0.0
        bar_h = (pct / 100.0) * h
        x = gx - bar_w / 2.0
        svg.append(f'<text x="{gx}" y="{oy+18}" font-size="10" font-weight="bold" text-anchor="middle" fill="#334155">{name} ({total})</text>')
        if bar_h:
            svg.append(f'<rect x="{x}" y="{oy-bar_h}" width="{bar_w}" height="{bar_h}" rx="2" fill="{color}"/>')
        svg.append(f'<text x="{gx}" y="{oy-bar_h-6 if bar_h else oy-8}" font-size="10" font-weight="bold" text-anchor="middle" fill="#5b21b6">{evaluated}/{total}</text>')

    svg.append(f'<rect x="{ox+110}" y="55" width="14" height="14" rx="2" fill="{color}"/>')
    svg.append(f'<text x="{ox+130}" y="66" font-size="10" fill="#334155">Defect rows with complete local evidence</text>')
    overall = data["overall"]
    svg.append(f'<text x="{ox+w/2}" y="{oy+52}" font-size="11" text-anchor="middle" fill="#475569">Detection statistics: NOT REPORTED ({overall.get("evaluated_defects", 0)}/{overall.get("total_defects", 0)} defect rows evidence-complete)</text>')
    svg.append('</svg>')
    (FIG_DIR / "fig2_evaluator_replay.svg").write_text("\n".join(svg))
    print(f"Generated {FIG_DIR / 'fig2_evaluator_replay.svg'}")


def generate_fig3_thermal():
    """Generate Fig 3: Temperature Rise vs Convection Resistance."""
    thm_path = ROOT_DIR / "thermal" / "thermal_results.json"
    if not thm_path.is_file():
        raise FileNotFoundError(thm_path)
    data = json.load(open(thm_path))
    rows = data["geometry1_actual_die"]["amb_300K"]
    if not isinstance(rows, list) or not rows:
        raise ValueError("thermal actual-die rows must be a non-empty list")
    for index, row in enumerate(rows):
        _finite(row["r_convec_k_per_w"], f"thermal[{index}].r_convec_k_per_w")
        _finite(row["mode64"]["s0_peak_rise_k"], f"thermal[{index}].s0_peak_rise_k")
        _finite(row["mode64"]["a_peak_rise_k"], f"thermal[{index}].a_peak_rise_k")
    
    svg = []
    svg.append('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 650 380" width="650" height="380" style="background:#ffffff; font-family:sans-serif;">')
    svg.append('<text x="325" y="30" font-size="16" font-weight="bold" text-anchor="middle" fill="#1e293b">Modeled Peak Temperature Rise vs. Convection Thermal Resistance</text>')
    
    ox, oy, w, h = 80, 310, 520, 240
    svg.append(f'<line x1="{ox}" y1="{oy}" x2="{ox+w}" y2="{oy}" stroke="#64748b" stroke-width="2"/>')
    svg.append(f'<line x1="{ox}" y1="{oy}" x2="{ox}" y2="{oy-h}" stroke="#64748b" stroke-width="2"/>')
    
    # Y axis: 0 to 1200 mK (1.2 K)
    for mk in [0, 300, 600, 900, 1200]:
        y_pos = oy - (mk / 1200.0) * h
        svg.append(f'<line x1="{ox}" y1="{y_pos}" x2="{ox+w}" y2="{y_pos}" stroke="#e2e8f0" stroke-width="1" stroke-dasharray="4"/>')
        svg.append(f'<text x="{ox-10}" y="{y_pos+4}" font-size="11" text-anchor="end" fill="#64748b">{mk} mK</text>')
    svg.append(f'<text x="{ox-45}" y="{oy-h/2}" font-size="12" font-weight="bold" text-anchor="middle" transform="rotate(-90 {ox-45} {oy-h/2})" fill="#334155">Peak Temperature Rise (mK)</text>')
    
    # X axis: R_conv 0 to 10 K/W
    for rc in [0, 2, 4, 6, 8, 10]:
        x_pos = ox + (rc / 10.0) * w
        svg.append(f'<line x1="{x_pos}" y1="{oy}" x2="{x_pos}" y2="{oy+5}" stroke="#64748b" stroke-width="1.5"/>')
        svg.append(f'<text x="{x_pos}" y="{oy+20}" font-size="11" text-anchor="middle" fill="#64748b">{rc}</text>')
    svg.append(f'<text x="{ox+w/2}" y="{oy+40}" font-size="12" font-weight="bold" text-anchor="middle" fill="#334155">Convection Thermal Resistance R_conv (K/W)</text>')
    
    pts_s0 = []
    pts_a = []
    for r in rows:
        rc = r["r_convec_k_per_w"]
        x_pos = ox + (rc / 10.0) * w
        y_s0 = oy - (r["mode64"]["s0_peak_rise_k"] * 1000.0 / 1200.0) * h
        y_a = oy - (r["mode64"]["a_peak_rise_k"] * 1000.0 / 1200.0) * h
        pts_s0.append((x_pos, y_s0))
        pts_a.append((x_pos, y_a))
        
    s0_path = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in pts_s0)
    a_path = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in pts_a)
    
    svg.append(f'<path d="{a_path}" fill="none" stroke="#dc2626" stroke-width="3"/>')
    svg.append(f'<path d="{s0_path}" fill="none" stroke="#2563eb" stroke-width="3"/>')
    
    for x, y in pts_a: svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="#dc2626"/>')
    for x, y in pts_s0: svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="#2563eb"/>')
    
    # Legend
    lx, ly = ox + 30, 50
    svg.append(f'<rect x="{lx}" y="{ly}" width="200" height="52" rx="4" fill="#f8fafc" stroke="#cbd5e1" stroke-width="1"/>')
    svg.append(f'<line x1="{lx+10}" y1="{ly+16}" x2="{lx+35}" y2="{ly+16}" stroke="#dc2626" stroke-width="3"/>')
    svg.append(f'<circle cx="{lx+22}" cy="{ly+16}" r="3.5" fill="#dc2626"/>')
    svg.append(f'<text x="{lx+45}" y="{ly+20}" font-size="11" fill="#334155">Dual Baseline A (Actual Die)</text>')
    svg.append(f'<line x1="{lx+10}" y1="{ly+36}" x2="{lx+35}" y2="{ly+36}" stroke="#2563eb" stroke-width="3"/>')
    svg.append(f'<circle cx="{lx+22}" cy="{ly+36}" r="3.5" fill="#2563eb"/>')
    svg.append(f'<text x="{lx+45}" y="{ly+40}" font-size="11" fill="#334155">Shared S0 (Actual Die)</text>')
    
    svg.append('</svg>')
    (FIG_DIR / "fig3_thermal_envelope.svg").write_text("\n".join(svg))
    print(f"Generated {FIG_DIR / 'fig3_thermal_envelope.svg'}")


if __name__ == "__main__":
    generate_fig1_workload()
    generate_fig2_evaluator()
    generate_fig3_thermal()
