#!/usr/bin/env python3
"""Assemble the Phase 3 machine-readable result record (fail-closed).

Reads the tool lock, the fixture manifest, and the generated reports/logs in
results/, verifies every required field is present and sane, and writes
results/fft64_baseline_sky130.json. Any missing or inconsistent input is a
hard failure: an incomplete estimate is never emitted.

v2: propagated-clock timing, gate-level (mapped netlist) activity traces,
separate active-streaming and scenario power, energy-per-FFT and throughput,
reset-timing attribution, annotation coverage, flow-input hashing, checked-in
leakage sanity check, ORFS provenance via the tool lock.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path

PHYS = Path(__file__).resolve().parent
REPO = PHYS.parent          # examples/peweaver
FIXTURE = REPO / "benchmarks" / "halo_fft64_reference"
R = PHYS / "results"

SCHEMA = "peweaver-physical-result-2"

CLOCK_PERIOD_NS = 10.0


def last_vcd_timestamp_ps(path: Path) -> int:
    """Return the exact final VCD timestamp without rounding to clock cycles."""
    last_ts = -1
    with Path(path).open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            if line.startswith("#"):
                try:
                    last_ts = max(last_ts, int(line[1:].strip()))
                except ValueError as exc:
                    raise ValueError(f"invalid VCD timestamp: {line.rstrip()!r}") from exc
    if last_ts <= 0:
        raise ValueError(f"no positive timestamp found in {path}")
    return last_ts


def vcd_timestamp_bounds_ps(path: Path) -> tuple[int, int]:
    """Return the exact first/final VCD timestamps, requiring normalization."""
    first_ts = None
    last_ts = -1
    with Path(path).open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            if line.startswith("#"):
                try:
                    ts = int(line[1:].strip())
                except ValueError as exc:
                    raise ValueError(f"invalid VCD timestamp: {line.rstrip()!r}") from exc
                if first_ts is None:
                    first_ts = ts
                last_ts = max(last_ts, ts)
    if first_ts is None or first_ts != 0 or last_ts <= first_ts:
        raise ValueError(
            f"VCD must be normalized to a non-empty #0-based window: "
            f"first={first_ts!r}, last={last_ts!r} in {path}")
    return first_ts, last_ts


def finite_window_energy_nj(power_mw: float, duration_ps: int,
                            transform_count: int) -> float:
    """Compute average energy/transform for one finite activity window."""
    if power_mw < 0 or duration_ps <= 0 or transform_count <= 0:
        raise ValueError("power, duration, and transform count must be valid")
    # mW * ps / 1e6 = nJ.
    return power_mw * duration_ps / (1_000_000.0 * transform_count)

def build_scenario(frame, burst, drain):
    return (
        f"phase 0: power-on async reset (16 cycles) + {drain}-cycle idle drain; "
        f"phase 1: reset-separated frame A (vectors/input4.txt) with output drain; "
        f"explicit idle separation; phase 2: TRUE CONTINUOUS STREAMING BURST - "
        f"di_en asserted for exactly {burst} consecutive samples (frames input4, "
        f"input5, input4) with no reset and no gap inside the burst, producer and "
        f"collector concurrent (fork/join), outputs overlapping inputs; "
        f"phase 3: final idle drain. 10 ns clock throughout. Primary power window: "
        f"the streaming burst only; secondary: the full scenario."
    )

ACTIVITY_SCENARIO = (  # legacy template (kept for reference)
    "phase 0: power-on async reset (16 cycles) + 96-cycle idle drain; "
    "phase 1: reset-separated frame A (vectors/input4.txt) with output drain; "
    "explicit idle separation; phase 2: TRUE CONTINUOUS STREAMING BURST - "
    "di_en asserted for exactly {burst} consecutive samples (frames input4, "
    "input5, input4) with no reset and no gap inside the burst, producer and "
    "collector concurrent (fork/join), outputs overlapping inputs; "
    "phase 3: final idle drain. 10 ns clock throughout. Primary power window: "
    "the streaming burst only (gls_stream.vcd); secondary: the full scenario "
    "(gls_scenario.vcd)."
)

LIMITATIONS = (
    "Provisional end-to-end feasibility result at the frozen open-PDK corner "
    "(sky130A, sky130_fd_sc_hd, tt_025C_1v80) with an open-source tool flow. "
    "Not sign-off silicon power, not a HALO reproduction, and not a clinical "
    "claim. Power is activity-based: unit-delay gate-level simulation of the "
    "mapped netlist provides the VCD activity; OpenSTA propagates activity to "
    "pins without direct annotation (coverage recorded). Timing uses "
    "propagated clocks with 0.10 ns setup / 0.05 ns hold uncertainty at the "
    "tt corner only; no multi-corner signoff, no IR-drop/EM/thermal "
    "analysis, no antenna/fill closure. Leakage is a library-model figure "
    "(order-of-magnitude only; the sky130 liberty power models are "
    "uncalibrated - see the leakage_check record). Reported power values are "
    "workload-window averages, not steady-state silicon measurements."
)


def die(msg: str) -> None:
    sys.exit(f"assemble_results.py: {msg}")


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _json_without_constants(path: Path) -> object:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON constant {value}")

    return json.loads(path.read_text(encoding="utf-8"),
                      parse_constant=reject_constant)


def _finite_number(value: object, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a real number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    if positive and number <= 0.0:
        raise ValueError(f"{label} must be positive")
    return number


def validate_leakage_check(record: object) -> None:
    """Validate the frozen single-cell sanity record before embedding it."""
    if not isinstance(record, dict):
        raise ValueError("leakage record must be a JSON object")
    if record.get("schema") != "peweaver-leakage-check-1":
        raise ValueError("unexpected leakage record schema")
    if record.get("cell") != "sky130_fd_sc_hd__nand2_1":
        raise ValueError("unexpected leakage-check cell")
    if record.get("deck") != "leakage_check/nand2_leak.spice":
        raise ValueError("leakage deck must use the stable repository path")

    corner = record.get("corner")
    if not isinstance(corner, dict):
        raise ValueError("leakage corner must be an object")
    if corner.get("process") != "tt":
        raise ValueError("leakage process must be tt")
    if _finite_number(corner.get("temperature_c"), "temperature_c") != 25.0:
        raise ValueError("leakage temperature must be 25 C")
    vdd = _finite_number(corner.get("vdd_v"), "vdd_v", positive=True)
    if not math.isclose(vdd, 1.8, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("leakage supply must be 1.8 V")
    if corner.get("monte_carlo_switches") != {
            "mc_mm_switch": 0, "mc_pr_switch": 0}:
        raise ValueError("leakage Monte Carlo switches are not frozen")
    if corner.get("body_ties") != {
            "VNB": "VGND (0 V)", "VPB": "VPWR (1.8 V)"}:
        raise ValueError("leakage body ties are not frozen")

    liberty = record.get("liberty_reference")
    if not isinstance(liberty, dict):
        raise ValueError("liberty_reference must be an object")
    if liberty.get("leakage_power_unit") != "1nW":
        raise ValueError("unexpected liberty leakage unit")
    cell_nw = _finite_number(liberty.get("cell_leakage_power_nw"),
                             "cell_leakage_power_nw", positive=True)
    cell_w = _finite_number(liberty.get("cell_leakage_power_w_strict_1nw"),
                            "cell_leakage_power_w_strict_1nw", positive=True)
    if not math.isclose(cell_w, cell_nw * 1e-9, rel_tol=1e-6):
        raise ValueError("cell leakage unit conversion is inconsistent")
    expected_levels = {
        "!A&!B": (0.0, 0.0),
        "!A&B": (0.0, vdd),
        "A&!B": (vdd, 0.0),
        "A&B": (vdd, vdd),
    }
    per_state = liberty.get("per_state_nw")
    if not isinstance(per_state, dict) or set(per_state) != set(expected_levels):
        raise ValueError("liberty per-state leakage must cover exactly four states")
    per_state_nw = {
        state: _finite_number(per_state[state], f"per_state_nw[{state}]",
                              positive=True)
        for state in expected_levels
    }

    measured = record.get("measured")
    if not isinstance(measured, list) or len(measured) != len(expected_levels):
        raise ValueError("measured leakage must contain exactly four states")
    ratios: list[float] = []
    seen: set[str] = set()
    for index, row in enumerate(measured):
        if not isinstance(row, dict):
            raise ValueError(f"measured[{index}] must be an object")
        state = row.get("input_state")
        if state not in expected_levels or state in seen:
            raise ValueError(f"invalid or duplicate measured state {state!r}")
        seen.add(state)
        va = _finite_number(row.get("va_v"), f"measured[{index}].va_v")
        vb = _finite_number(row.get("vb_v"), f"measured[{index}].vb_v")
        expected_va, expected_vb = expected_levels[state]
        if not (math.isclose(va, expected_va, abs_tol=1e-12)
                and math.isclose(vb, expected_vb, abs_tol=1e-12)):
            raise ValueError(f"measured voltage levels disagree for {state}")
        current = _finite_number(row.get("current_a"),
                                 f"measured[{index}].current_a", positive=True)
        leakage_w = _finite_number(row.get("leakage_w"),
                                   f"measured[{index}].leakage_w", positive=True)
        liberty_w = _finite_number(row.get("liberty_w"),
                                   f"measured[{index}].liberty_w", positive=True)
        ratio = _finite_number(row.get("ratio_measured_over_liberty"),
                               f"measured[{index}].ratio", positive=True)
        if not math.isclose(leakage_w, current * vdd, rel_tol=1e-6):
            raise ValueError(f"measured power/current disagree for {state}")
        if not math.isclose(liberty_w, per_state_nw[state] * 1e-9,
                            rel_tol=1e-6):
            raise ValueError(f"liberty conversion disagrees for {state}")
        if not math.isclose(ratio, leakage_w / liberty_w, rel_tol=1e-5):
            raise ValueError(f"measured/liberty ratio disagrees for {state}")
        ratios.append(ratio)
    if seen != set(expected_levels):
        raise ValueError("measured leakage state coverage is incomplete")

    ratio_range = record.get("ratio_measured_over_liberty_range")
    if not isinstance(ratio_range, dict):
        raise ValueError("leakage ratio range must be an object")
    recorded_min = _finite_number(ratio_range.get("min"), "ratio range min",
                                  positive=True)
    recorded_max = _finite_number(ratio_range.get("max"), "ratio range max",
                                  positive=True)
    if not (math.isclose(recorded_min, min(ratios), rel_tol=1e-6)
            and math.isclose(recorded_max, max(ratios), rel_tol=1e-6)):
        raise ValueError("leakage ratio range does not match measured rows")


def load_staged_leakage_check(source: Path, staged: Path) -> dict:
    if not source.is_file() or not staged.is_file():
        raise ValueError("leakage sanity-check source or staged record missing")
    if source.read_bytes() != staged.read_bytes():
        raise ValueError("staged leakage sanity-check record differs from source")
    record = _json_without_constants(source)
    validate_leakage_check(record)
    assert isinstance(record, dict)
    return record


def read_text(path: Path) -> str:
    if not path.is_file():
        die(f"required file missing: {path}")
    return path.read_text(encoding="utf-8", errors="replace")


def parse_power_report(path: Path, label: str) -> dict:
    text = read_text(path)
    totals = re.findall(
        r"^\s*Total\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)",
        text, re.MULTILINE)
    if not totals:
        die(f"could not parse a Total power row from {label}")
    internal_w, switching_w, leakage_w, total_w = (float(v) for v in totals[-1])
    dynamic_w = internal_w + switching_w
    if dynamic_w <= 0.0:
        die(f"{label}: dynamic power is zero - activity trace did not apply; "
            "refusing to emit a vectorless result")
    return {
        "internal_mw": internal_w * 1e3,
        "switching_mw": switching_w * 1e3,
        "leakage_mw": leakage_w * 1e3,
        "total_mw": total_w * 1e3,
    }


DESIGNS = {
    "fft64": {
        "top": "peweaver_ppa_fft64",
        "frame_cycles": 64,
        "fixture": REPO / "benchmarks" / "halo_fft64_reference",
        "result": "fft64_baseline_sky130.json",
        "netlist": "netlists/fft64_ppa_synth.v",
        "vcds": {"rtl": "rtl_scenario.vcd", "gls_scenario": "gls_scenario_norm.vcd",
                 "gls_stream": "gls_stream_norm.vcd"},
        "spef": "spef/fft64_baseline.spef",
        "def": "def/fft64_baseline.def",
        "reports": {"sta_max": "sta_max_paths.rpt", "sta_min": "sta_min_paths.rpt",
                    "sta_setup": "sta_setup_paths.rpt",
                    "sta_hold": "sta_hold_paths.rpt",
                    "sta_recovery": "sta_recovery_paths.rpt",
                    "sta_removal": "sta_removal_paths.rpt",
                    "power_stream": "power_streaming.rpt",
                    "power_scenario": "power_scenario.rpt", "drc": "drc.rpt"},
        "metrics": "metrics.txt",
        "logs": {"yosys": "yosys.log", "fe": "openroad_frontend.log",
                 "be": "openroad_backend.log", "rtl_run": "verilator_rtl_run.log",
                 "gls_scenario": "iverilog_gls_scenario_run.log",
                 "gls_stream": "iverilog_gls_stream_run.log"},
        "activity_tb": "activity/fft64_activity_tb.sv",
        "log_tag": "",
        "burst_samples": 192,
        "frame_desc": "64-point",
        "idle_drain": 96,
        "frame_size": 64,
    },
    "fft128": {
        "top": "peweaver_ppa_fft128",
        "frame_cycles": 128,
        "fixture": REPO / "benchmarks" / "halo_fft128_reference",
        "result": "fft128_baseline_sky130.json",
        "netlist": "netlists/fft128_ppa_synth.v",
        "vcds": {"rtl": "rtl_scenario_fft128.vcd",
                 "gls_scenario": "gls_scenario_fft128_norm.vcd",
                 "gls_stream": "gls_stream_fft128_norm.vcd"},
        "spef": "spef/fft128_baseline.spef",
        "def": "def/fft128_baseline.def",
        "reports": {"sta_max": "sta_max_paths_fft128.rpt",
                    "sta_min": "sta_min_paths_fft128.rpt",
                    "sta_setup": "sta_setup_paths_fft128.rpt",
                    "sta_hold": "sta_hold_paths_fft128.rpt",
                    "sta_recovery": "sta_recovery_paths_fft128.rpt",
                    "sta_removal": "sta_removal_paths_fft128.rpt",
                    "power_stream": "power_streaming_fft128.rpt",
                    "power_scenario": "power_scenario_fft128.rpt",
                    "drc": "drc_fft128.rpt"},
        "metrics": "metrics_fft128.txt",
        "logs": {"yosys": "yosys_fft128.log", "fe": "openroad_frontend_fft128.log",
                 "be": "openroad_backend_fft128.log",
                 "rtl_run": "verilator_rtl_fft128_run.log",
                 "gls_scenario": "iverilog_gls_scenario_fft128_run.log",
                 "gls_stream": "iverilog_gls_stream_fft128_run.log"},
        "activity_tb": "activity/fft128_activity_tb.sv",
        "log_tag": "_fft128",
        "burst_samples": 384,
        "frame_desc": "128-point",
        "idle_drain": 256,
        "frame_size": 128,
    },
    "shared": {
        "top": "peweaver_ppa_shared_fft",
        "frame_cycles": 64,
        "fixture": REPO / "benchmarks" / "halo_fft64_reference",
        "result": "shared_baseline_sky130.json",
        "netlist": "netlists/shared_ppa_synth.v",
        "vcds": {"rtl": "rtl_scenario_shared.vcd",
                 "gls_scenario": "gls_scenario_shared_norm.vcd",
                 "gls_stream": "gls_stream_shared_norm.vcd",
                 "gls_stream_128": "gls_stream_128_shared_norm.vcd"},
        "spef": "spef/shared_baseline.spef",
        "def": "def/shared_baseline.def",
        "reports": {"sta_max": "sta_max_paths_shared.rpt",
                    "sta_min": "sta_min_paths_shared.rpt",
                    "sta_setup": "sta_setup_paths_shared.rpt",
                    "sta_hold": "sta_hold_paths_shared.rpt",
                    "sta_recovery": "sta_recovery_paths_shared.rpt",
                    "sta_removal": "sta_removal_paths_shared.rpt",
                    "power_stream": "power_streaming_shared.rpt",
                    "power_stream_128": "power_streaming_128_shared.rpt",
                    "power_scenario": "power_scenario_shared.rpt",
                    "drc": "drc_shared.rpt"},
        "metrics": "metrics_shared.txt",
        "logs": {"yosys": "yosys_shared.log", "fe": "openroad_frontend_shared.log",
                 "be": "openroad_backend_shared.log",
                 "rtl_run": "verilator_rtl_shared_run.log",
                 "gls_scenario": "iverilog_gls_scenario_shared_run.log",
                 "gls_stream": "iverilog_gls_stream_shared_run.log",
                 "gls_stream_128": "iverilog_gls_stream_128_shared_run.log"},
        "activity_tb": "activity/shared_activity_tb.sv",
        "wrapper": "rtl/peweaver_ppa_shared_fft.v",
        "candidate": "rtl/peweaver_shared_fft.v",
        "log_tag": "_shared",
        "burst_samples": 192,
        "frame_desc": "shared 64/128-point",
        "idle_drain": 256,
        "frame_size": 64,
    },
    "dual": {
        "top": "peweaver_ppa_dual_fft",
        "frame_cycles": 64,
        "fixture": REPO / "benchmarks" / "halo_fft64_reference",
        "result": "dual_baseline_sky130.json",
        "netlist": "netlists/dual_ppa_synth.v",
        "vcds": {"rtl": "rtl_scenario_dual.vcd",
                 "gls_scenario": "gls_scenario_dual_norm.vcd",
                 "gls_stream": "gls_stream_dual_norm.vcd",
                 "gls_stream_128": "gls_stream_128_dual_norm.vcd"},
        "spef": "spef/dual_baseline.spef",
        "def": "def/dual_baseline.def",
        "reports": {"sta_max": "sta_max_paths_dual.rpt",
                    "sta_min": "sta_min_paths_dual.rpt",
                    "sta_setup": "sta_setup_paths_dual.rpt",
                    "sta_hold": "sta_hold_paths_dual.rpt",
                    "sta_recovery": "sta_recovery_paths_dual.rpt",
                    "sta_removal": "sta_removal_paths_dual.rpt",
                    "power_stream": "power_streaming_dual.rpt",
                    "power_stream_128": "power_streaming_128_dual.rpt",
                    "power_scenario": "power_scenario_dual.rpt",
                    "drc": "drc_dual.rpt"},
        "metrics": "metrics_dual.txt",
        "logs": {"yosys": "yosys_dual.log", "fe": "openroad_frontend_dual.log",
                 "be": "openroad_backend_dual.log",
                 "rtl_run": "verilator_rtl_dual_run.log",
                 "gls_scenario": "iverilog_gls_scenario_dual_run.log",
                 "gls_stream": "iverilog_gls_stream_dual_run.log",
                 "gls_stream_128": "iverilog_gls_stream_128_dual_run.log"},
        "activity_tb": "activity/dual_activity_tb.sv",
        "wrapper": "rtl/peweaver_ppa_dual_fft.v",
        "candidate": "rtl/peweaver_ppa_dual_fft.v",
        "log_tag": "_dual",
        "burst_samples": 192,
        "frame_desc": "ungated dual-core 64/128-point reference",
        "idle_drain": 256,
        "frame_size": 64,
    },
    "dual_b": {
        "top": "peweaver_ppa_dual_fft_icg",
        "frame_cycles": 64,
        "fixture": REPO / "benchmarks" / "halo_fft64_reference",
        "result": "dual_b_sky130.json",
        "netlist": "netlists/dual_b_ppa_synth.v",
        "vcds": {"rtl": "rtl_scenario_dual_b.vcd",
                 "gls_scenario": "gls_scenario_dual_b_norm.vcd",
                 "gls_stream": "gls_stream_dual_b_norm.vcd",
                 "gls_stream_128": "gls_stream_128_dual_b_norm.vcd"},
        "spef": "spef/dual_b_baseline.spef",
        "def": "def/dual_b_baseline.def",
        "reports": {"sta_max": "sta_max_paths_dual_b.rpt",
                    "sta_min": "sta_min_paths_dual_b.rpt",
                    "sta_setup": "sta_setup_paths_dual_b.rpt",
                    "sta_hold": "sta_hold_paths_dual_b.rpt",
                    "sta_recovery": "sta_recovery_paths_dual_b.rpt",
                    "sta_removal": "sta_removal_paths_dual_b.rpt",
                    "power_stream": "power_streaming_dual_b.rpt",
                    "power_stream_128": "power_streaming_128_dual_b.rpt",
                    "power_scenario": "power_scenario_dual_b.rpt",
                    "drc": "drc_dual_b.rpt"},
        "metrics": "metrics_dual_b.txt",
        "logs": {"yosys": "yosys_dual_b.log", "fe": "openroad_frontend_dual_b.log",
                 "be": "openroad_backend_dual_b.log",
                 "rtl_run": "verilator_rtl_dual_b_run.log",
                 "gls_scenario": "iverilog_gls_scenario_dual_b_run.log",
                 "gls_stream": "iverilog_gls_stream_dual_b_run.log",
                 "gls_stream_128": "iverilog_gls_stream_128_dual_b_run.log"},
        "activity_tb": "activity/dual_b_activity_tb.sv",
        "wrapper": "rtl/peweaver_ppa_dual_fft_icg.v",
        "candidate": "rtl/peweaver_ppa_dual_fft_icg.v",
        "log_tag": "_dual_b",
        "burst_samples": 192,
        "frame_desc": "power-managed dual-core 64/128-point reference with sky130_fd_sc_hd__dlclkp_4 ICG cells",
        "idle_drain": 256,
        "frame_size": 64,
    },
}


def _physical_input(value: str, label: str) -> tuple[str, Path]:
    path = Path(value)
    if not path.is_absolute():
        path = PHYS / path
    path = path.resolve()
    try:
        path.relative_to(PHYS.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} escaped the physical source tree: {value}") from exc
    if not path.is_file():
        raise ValueError(f"{label} missing: {value}")
    return Path(os.path.relpath(path, PHYS)).as_posix(), path


def build_flow_input_hashes(design: str, cfg: dict, *, synth_template: str,
                            frontend_template: str,
                            backend_template: str) -> dict[str, str]:
    """Hash every repository input that governs the physical measurement."""
    raw_inputs = [
        "tool-lock.json",
        "run-physical.sh",
        "assemble_results.py",
        "constraints/" + design + "_baseline.sdc",
        synth_template,
        "synth/filter_liberty.py",
        frontend_template,
        backend_template,
        cfg.get("wrapper", "rtl/peweaver_ppa_fft" + design[3:] + ".v"),
        "activity/" + design + "_activity_tb.sv",
        "pdk/sky130hd/setRC.tcl",
        "pdk/sky130hd/pdn.tcl",
        "pdk/sky130hd/fastroute.tcl",
        "pdk/sky130hd/make_tracks.tcl",
        "pdk/sky130hd/tapcell.tcl",
        "pdk/sky130hd/rcx_patterns.rules",
        "vcd_normalize.py",
        "leakage_check/nand2_leakage_check.json",
        "leakage_check/nand2_leak.spice",
        "leakage_check/run_leakage_check.sh",
    ]
    if design == "shared":
        raw_inputs.extend((cfg["candidate"], "synth/sky130_simple_map.v"))
    if design in ("dual", "dual_b"):
        raw_inputs.extend((
            "rtl/peweaver_ppa_fft64.v",
            "rtl/peweaver_ppa_fft128.v",
            "rtl/dual/fft128_core.v",
            "rtl/dual/sdfunit128.v",
            "rtl/dual/twiddle128_core.v",
            "rtl/dual/halo_fft128_wrapper.v",
        ))
    if design == "dual_b":
        raw_inputs.append("rtl/sky130_icg_blackbox.v")

    flow_inputs: dict[str, str] = {}
    for value in raw_inputs:
        try:
            key, path = _physical_input(value, "flow input")
        except ValueError as exc:
            die(str(exc))
        flow_inputs[key] = sha256(path)

    fixtures = [Path(cfg["fixture"])]
    if design in ("shared", "dual", "dual_b"):
        fixtures.append(REPO / "benchmarks" / "halo_fft128_reference")
    for fixture in fixtures:
        manifest_path = fixture / "manifest.json"
        if not manifest_path.is_file():
            die(f"fixture manifest missing: {manifest_path}")
        manifest = _json_without_constants(manifest_path)
        if not isinstance(manifest, dict):
            die(f"fixture manifest must be an object: {manifest_path}")
        key = Path(os.path.relpath(manifest_path, PHYS)).as_posix()
        flow_inputs[key] = sha256(manifest_path)
        vector_hashes = manifest.get("upstream", {}).get("vector_files", {})
        if not isinstance(vector_hashes, dict) or not vector_hashes:
            die(f"fixture vector hash manifest missing: {manifest_path}")
        for rel, expected_hash in sorted(vector_hashes.items()):
            vector = fixture / rel
            if not vector.is_file():
                die(f"fixture vector missing: {vector}")
            actual_hash = sha256(vector)
            if actual_hash != expected_hash:
                die(f"fixture vector hash mismatch: {vector}")
            key = Path(os.path.relpath(vector, PHYS)).as_posix()
            flow_inputs[key] = actual_hash
    return flow_inputs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--design", default="fft64")
    parser.add_argument("--synth-template")
    parser.add_argument("--frontend-template")
    parser.add_argument("--backend-template")
    args = parser.parse_args()
    design = args.design
    if design not in DESIGNS:
        die(f"unknown design '{design}' (expected fft64, fft128, shared, dual, or dual_b)")
    cfg = DESIGNS[design]
    frame_cycles = cfg["frame_cycles"]
    fixture = cfg["fixture"]
    synth_template = args.synth_template or f"synth/{design}_synth.ys"
    frontend_template = args.frontend_template or (
        "openroad/dual_d050_frontend.tcl"
        if design in ("dual", "dual_b") else "openroad/fft64_frontend.tcl")
    backend_template = args.backend_template or "openroad/fft64_backend.tcl"
    try:
        synth_template, _ = _physical_input(
            synth_template, "synthesis template")
        frontend_template, _ = _physical_input(
            frontend_template, "frontend template")
        backend_template, _ = _physical_input(
            backend_template, "backend template")
    except ValueError as exc:
        die(str(exc))

    lock = json.loads((PHYS / "tool-lock.json").read_text(encoding="utf-8"))
    manifest = json.loads((fixture / "manifest.json").read_text(encoding="utf-8"))

    # ------------------------------------------------ pinned source hashes
    sources: dict[str, str] = {}
    for entry in manifest["sources"]:
        path = (fixture / entry).resolve()
        if not path.is_file():
            die(f"manifest source missing: {entry}")
        sources[entry] = sha256(path)
    if design in ("shared", "dual", "dual_b"):
        fixture128 = REPO / "benchmarks" / "halo_fft128_reference"
        manifest128 = json.loads((fixture128 / "manifest.json").read_text(encoding="utf-8"))
        for entry in manifest128["sources"]:
            path = (fixture128 / entry).resolve()
            if not path.is_file():
                die(f"FFT128 manifest source missing: {entry}")
            sources[f"fft128/{entry}"] = sha256(path)
        sources[cfg["candidate"]] = sha256(PHYS / cfg["candidate"])
        sources[cfg["wrapper"]] = sha256(PHYS / cfg["wrapper"])

    # ------------------------------------------------ synthesis report
    yosys_log = read_text(R / "logs" / cfg["logs"]["yosys"])
    m = re.search(
        r"Chip area for module '\\?" + cfg["top"] + r"':\s*([0-9.]+)", yosys_log)
    synth_area_um2 = float(m.group(1)) if m else None
    cell_matches = re.findall(r"^\s*(\d+)\s+\S+\s+cells\s*$", yosys_log,
                              re.MULTILINE)
    synth_cell_count = int(cell_matches[-1]) if cell_matches else None
    if synth_area_um2 is None or synth_cell_count is None:
        die("could not parse synthesis area/cell count from yosys.log")

    # ------------------------------------------------ P&R metrics
    metrics: dict[str, float] = {}
    for line in read_text(R / "reports" / cfg["metrics"]).splitlines():
        parts = line.split()
        if len(parts) == 2:
            try:
                metrics[parts[0]] = float(parts[1])
            except ValueError:
                die(f"unparsable metrics.txt line: {line!r}")
    for key in ("instance_count", "worst_slack_max_ns",
                "total_negative_slack_max_ns", "worst_slack_min_ns"):
        if key not in metrics:
            die(f"metrics.txt missing {key}")

    or_log = read_text(R / "logs" / cfg["logs"]["be"])
    m = re.search(
        r"Design area\s+([0-9.]+)\s+u\^?2\s+([0-9.]+)% utilization", or_log)
    pnr_area_um2 = float(m.group(1)) if m else None
    utilization_pct = float(m.group(2)) if m else None
    if pnr_area_um2 is None or utilization_pct is None:
        die("could not parse Design area/utilization from the backend log")

    # Overall metrics are retained as a cross-check, while the published
    # numbers below come from path-group-specific reports.
    overall_wns_max = metrics["worst_slack_max_ns"]
    overall_wns_min = metrics["worst_slack_min_ns"]

    # Timing is reported by semantic path class.  The external asynchronous
    # reset port is waived only at the reset-synchronizer boundary; the
    # synchronizer's registered release into the core remains timed here.
    def worst_reported_slack(report_name: str, check_name: str,
                             expected_group: str, expected_type: str) -> float:
        report = read_text(R / "reports" / report_name)
        groups = set(re.findall(r"^Path Group:\s*(\S+)\s*$", report, re.MULTILINE))
        types = set(re.findall(r"^Path Type:\s*(\S+)\s*$", report, re.MULTILINE))
        if groups != {expected_group} or types != {expected_type}:
            die(f"{check_name} report has groups/types {groups}/{types}; "
                f"expected {expected_group}/{expected_type}")
        if re.search(r"^Startpoint:\s+reset\s+\(", report, re.MULTILINE):
            die(f"{check_name} report contains an untimed external reset path")
        slacks = [float(value) for value in re.findall(
            r"^\s*([-+0-9.eE]+)\s+slack\s+\((?:MET|VIOLATED)\)\s*$",
            report, re.MULTILINE)]
        if not slacks:
            die(f"could not parse {check_name} slack from {report_name}")
        return min(slacks)

    setup_wns = worst_reported_slack(
        cfg["reports"]["sta_setup"], "setup", "core_clock", "max")
    hold_wns = worst_reported_slack(
        cfg["reports"]["sta_hold"], "hold", "core_clock", "min")
    recovery_wns = worst_reported_slack(
        cfg["reports"]["sta_recovery"], "reset recovery", "asynchronous", "max")
    removal_wns = worst_reported_slack(
        cfg["reports"]["sta_removal"], "reset removal", "asynchronous", "min")
    timing_met = all(slack >= 0.0 for slack in
                     (setup_wns, hold_wns, recovery_wns, removal_wns))

    # ------------------------------------------------ activity annotation
    annotations = [int(n) for n in
                   re.findall(r"Annotated (\d+) pin activities", or_log)]
    expected_annotations = 3 if design in ("shared", "dual", "dual_b") else 2
    if len(annotations) < expected_annotations:
        die(f"expected {expected_annotations} Annotated-pin-activities records "
            f"in the backend log, found {annotations}")
    annotation_stream = annotations[0]
    annotation_stream_128 = annotations[1] if design in ("shared", "dual", "dual_b") else None
    annotation_scenario = annotations[2] if design in ("shared", "dual", "dual_b") else annotations[1]
    if (annotation_stream <= 0 or annotation_scenario <= 0
            or (annotation_stream_128 is not None and annotation_stream_128 <= 0)):
        die(f"VCD activity annotation must be nonzero for both windows; "
            f"streaming={annotation_stream}, scenario={annotation_scenario}")

    # ------------------------------------------------ VCD window from actual file
    # Preserve the exact final picosecond timestamp.  The dump ends on a
    # half-cycle boundary, so reducing it to int(clock cycles) biases energy.
    vcd_stream_path = R / "activity" / cfg["vcds"]["gls_stream"]
    if not vcd_stream_path.is_file():
        die("normalized streaming VCD missing")
    try:
        first_vcd_ts, last_vcd_ts = vcd_timestamp_bounds_ps(vcd_stream_path)
        vcd_window_ps = last_vcd_ts - first_vcd_ts
    except ValueError as exc:
        die(str(exc))
    vcd_window_cycles = vcd_window_ps / (CLOCK_PERIOD_NS * 1000.0)
    vcd_window_us = vcd_window_ps / 1_000_000.0
    n_frames = 3
    print(f"  VCD window: {vcd_window_cycles:.3f} cycles "
          f"({vcd_window_us:.6f} us)")

    # ------------------------------------------------ power (two windows)
    power_stream = parse_power_report(R / "reports" / cfg["reports"]["power_stream"],
                                      cfg["reports"]["power_stream"])
    power_scenario = parse_power_report(R / "reports" / cfg["reports"]["power_scenario"],
                                        cfg["reports"]["power_scenario"])
    power_stream_128 = None
    vcd_window_128_ps = None
    if design in ("shared", "dual", "dual_b"):
        power_stream_128 = parse_power_report(
            R / "reports" / cfg["reports"]["power_stream_128"],
            cfg["reports"]["power_stream_128"])
        try:
            first128, last128 = vcd_timestamp_bounds_ps(
                R / "activity" / cfg["vcds"]["gls_stream_128"])
            vcd_window_128_ps = last128 - first128
        except ValueError as exc:
            die(str(exc))

    # ------------------------------------------------ leakage sanity check
    source_leak = PHYS / "leakage_check" / "nand2_leakage_check.json"
    copied_leak = R / "leakage_check" / "nand2_leakage_check.json"
    try:
        leakage_check = load_staged_leakage_check(source_leak, copied_leak)
    except (json.JSONDecodeError, ValueError) as exc:
        die(f"invalid leakage sanity-check record: {exc}")

    # ------------------------------------------------ artifacts
    artifacts: dict[str, dict[str, object]] = {}
    for label, path in (
        ("synth_netlist", R / cfg["netlist"]),
        ("rtl_scenario_vcd", R / "activity" / cfg["vcds"]["rtl"]),
        ("gls_scenario_vcd", R / "activity" / cfg["vcds"]["gls_scenario"]),
        ("gls_stream_vcd", R / "activity" / cfg["vcds"]["gls_stream"]),
        ("spef", R / cfg["spef"]),
        ("def", R / cfg["def"]),
        ("sta_max_paths", R / "reports" / cfg["reports"]["sta_max"]),
        ("sta_min_paths", R / "reports" / cfg["reports"]["sta_min"]),
        ("sta_setup_paths", R / "reports" / cfg["reports"]["sta_setup"]),
        ("sta_hold_paths", R / "reports" / cfg["reports"]["sta_hold"]),
        ("sta_recovery_paths", R / "reports" / cfg["reports"]["sta_recovery"]),
        ("sta_removal_paths", R / "reports" / cfg["reports"]["sta_removal"]),
        ("power_streaming_report", R / "reports" / cfg["reports"]["power_stream"]),
        ("power_scenario_report", R / "reports" / cfg["reports"]["power_scenario"]),
        ("drc_report", R / "reports" / cfg["reports"]["drc"]),
        ("yosys_log", R / "logs" / cfg["logs"]["yosys"]),
        ("openroad_frontend_log", R / "logs" / cfg["logs"]["fe"]),
        ("openroad_backend_log", R / "logs" / cfg["logs"]["be"]),
        ("rtl_activity_run_log", R / "logs" / cfg["logs"]["rtl_run"]),
        ("gls_scenario_run_log", R / "logs" / cfg["logs"]["gls_scenario"]),
        ("gls_stream_run_log", R / "logs" / cfg["logs"]["gls_stream"]),
        ("leakage_sanity_record", copied_leak),
    ):
        p = Path(path)
        if not p.is_file():
            die(f"required artifact missing: {p}")
        artifacts[label] = {"path": str(p), "sha256": sha256(p), "bytes": p.stat().st_size}
    if design in ("shared", "dual", "dual_b"):
        for label, path in (
            ("gls_stream_128_vcd", R / "activity" / cfg["vcds"]["gls_stream_128"]),
            ("power_streaming_128_report", R / "reports" / cfg["reports"]["power_stream_128"]),
            ("gls_stream_128_log", R / "logs" / cfg["logs"]["gls_stream_128"]),
        ):
            if not path.is_file():
                die(f"required shared artifact missing: {path}")
            artifacts[label] = {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size}

    drc_lines = (R / "reports" / cfg["reports"]["drc"]).read_text(encoding="utf-8",
                                                      errors="replace")
    drc_violations = len(re.findall(r"violation", drc_lines, re.IGNORECASE))

    # ------------------------------------------------ flow-input hashes
    flow_inputs = build_flow_input_hashes(
        design, cfg, synth_template=synth_template,
        frontend_template=frontend_template,
        backend_template=backend_template)

    record = {
        "schema": SCHEMA,
        "status": "provisional end-to-end feasibility result",
        "generated_from": {
            "tool_lock": "physical/tool-lock.json",
            "fixture_manifest": str(fixture / "manifest.json"),
            "templates": {
                "synthesis": synth_template,
                "frontend": frontend_template,
                "backend": backend_template,
            },
        },
        "design": {
            "name": manifest["name"],
            "top": cfg["top"],
            "top_role": ("PEWeaver-owned PPA integration wrapper (async-assert/"
                         "sync-deassert reset) around the pinned, untouched "
                         + design.upper() + " reference"),
            "tier": manifest.get("tier"),
            "reference_source_hashes_sha256": sources,
            "fixture_manifest_sha256": sha256(fixture / "manifest.json"),
        },
        "pdk": {
            "name": lock["pdk"]["name"],
            "volare_version": lock["pdk"]["volare_version"],
            "cell_library": lock["pdk"]["standard_cell_library"],
            "timing_corner": lock["pdk"]["timing_corner"],
            "orfs_platform_commit": lock["orfs_platform_files"].get("pinned_commit"),
        },
        "tools": {
            "openroad": lock["tools"]["openroad"]["version"],
            "yosys": lock["tools"]["yosys"]["version"],
            "verilator": lock["tools"]["verilator"]["version"],
        },
        "constraints": {
            "clock_period_ns": CLOCK_PERIOD_NS,
            "clock_uncertainty_setup_ns": 0.10,
            "clock_uncertainty_hold_ns": 0.05,
            "clock_analysis": "propagated (post-CTS) in all reported timing",
            "io_delay_ns": 1.5,
            "driving_cell": "sky130_fd_sc_hd__buf_4",
            "output_load_pf": 0.5,
            "max_fanout": 16,
            "floorplan": "utilization 40%, aspect ratio 1.0, 5 um core space",
            "routing_layers": "met1-met5 signal, met3-met5 clock",
        },
        "activity": {
            "scenario": build_scenario(
                cfg.get("frame_size", 64),
                cfg.get("burst_samples", 192),
                cfg.get("idle_drain", 96)),
            "testbench_sha256": sha256(PHYS / cfg["activity_tb"]),
            "streaming_vcd_sha256": artifacts["gls_stream_vcd"]["sha256"],
            "scenario_vcd_sha256": artifacts["gls_scenario_vcd"]["sha256"],
            "activity_source": ("unit-delay gate-level simulation of the mapped "
                                "netlist with Icarus Verilog and the sky130 "
                                "FUNCTIONAL models (OpenLane-style GLS); "
                                "golden outputs verified on the mapped netlist "
                                "in the same runs"),
            "annotated_pins_streaming": annotation_stream,
            "annotated_pins_scenario": annotation_scenario,
            "vcd_normalization": {
                "tool": "vcd_normalize.py",
                "description": ("scenario and streaming timestamps shifted so "
                                "first event is at #0; simulator $date headers "
                                "canonicalized; clock period validated at 10000 ps"),
                "streaming_vcd_hash": artifacts["gls_stream_vcd"]["sha256"],
                "scenario_vcd_hash": artifacts["gls_scenario_vcd"]["sha256"],
            },
            "annotated_pins_note": ("pins directly annotated from the VCD; "
                                    "remaining internal activity is propagated "
                                    "by OpenSTA from annotated pins"),
        },
        "results": {
            "synthesis": {
                "cell_count": synth_cell_count,
                "cell_area_um2": synth_area_um2,
            },
            "pnr": {
                "instance_count": int(metrics["instance_count"]),
                "cell_area_um2": pnr_area_um2,
                "area_note": ("design_area is the placed standard-cell area "
                              "(sum of cell areas); the die/core footprint is "
                              "larger due to utilization margin and routing"
                              ),
                "utilization_pct": utilization_pct,
                "worst_slack_max_ns": setup_wns,
                "worst_slack_min_ns": hold_wns,
                "setup_slack_ns": setup_wns,
                "hold_slack_ns": hold_wns,
                "reset_recovery_slack_ns": recovery_wns,
                "reset_removal_slack_ns": removal_wns,
                "total_negative_slack_max_ns":
                    metrics["total_negative_slack_max_ns"],
                "overall_worst_slack_max_ns": overall_wns_max,
                "overall_worst_slack_min_ns": overall_wns_min,
                "timing_met": timing_met,
                "timing_note": ("propagated clocks, uncertainty per constraints; "
                                "external async reset is the intentional "
                                "asynchronous boundary (not timed with the "
                                "1.5 ns input delay); the PEWeaver PPA wrapper "
                                "synchronizes reset release, and synchronized "
                                "reset-to-core recovery/removal is reported"),
                "external_async_reset_boundary_waived": True,
            },
            "power_mw": {
                "streaming_window": {
                    **power_stream,
                    "definition": ("average power over the three-frame "
                                   "continuous-streaming burst only"),
                },
                "scenario_window": {
                    **power_scenario,
                    "definition": ("average power over the full "
                                   "reset/idle/streaming scenario"),
                },
                "basis": ("gate-level (mapped netlist, iverilog GLS) VCD-seeded "
                          "activity, OpenSTA-propagated, after OpenRCX extraction"),
            },
            "energy_per_fft_nj": {
                "value": finite_window_energy_nj(
                    power_stream["total_mw"], vcd_window_ps, n_frames),
                "definition": ("finite 3-frame window energy per transform: "
                               "streaming-window average power × VCD duration / 3 "
                               "(includes pipeline fill and drain; NOT "
                               "sustained steady-state)"),
                "measurement_window": {
                    "duration_ps": vcd_window_ps,
                    "duration_us": vcd_window_us,
                    "clock_cycles": vcd_window_cycles,
                    "transform_count": n_frames,
                },
            },
            "throughput": {
                "fft_per_s": 1.0 / (frame_cycles * CLOCK_PERIOD_NS * 1e-9),
                "definition": "one transform per " + str(frame_cycles) + " clock cycles",
            },
        },
        "leakage_check": leakage_check,
        "artifacts": artifacts,
        "flow_input_hashes_sha256": flow_inputs,
        "drc_violation_lines": drc_violations,
        "limitations": LIMITATIONS,
        "claim_boundary": (
            "provisional implementation estimate only; no sign-off power, no "
            "HALO reproduction, no clinical claim, no silicon measurement"
        ),
    }

    if design in ("shared", "dual", "dual_b"):
        assert power_stream_128 is not None and vcd_window_128_ps is not None
        separate_placed_area = 164408.0 + 260477.0
        separate_synth_area = 141235.6424 + 218887.2440
        if design == "shared":
            design_name = "peweaver_shared_fft64_fft128_candidate"
            top_role = ("PEWeaver shared configurable 64/128-point FFT "
                        "candidate with the same reset and I/O contract as "
                        "the two frozen standalone baselines")
        elif design == "dual":
            design_name = "peweaver_ungated_dual_fft64_fft128_reference"
            top_role = ("PEWeaver no-sharing control: the two frozen "
                        "standalone FFT cores placed on one die; inactive "
                        "core held with di_en=0, both clocks running; "
                        "matched schedule with the shared candidate")
        else:
            design_name = "peweaver_power_managed_dual_fft64_fft128_reference"
            top_role = ("PEWeaver power-managed control: the two frozen "
                        "standalone FFT cores placed on one die with characterized "
                        "sky130_fd_sc_hd__dlclkp_4 ICG cells; inactive core clock "
                        "gated; matched schedule with the shared candidate")
        record["design"].update({
            "name": design_name,
            "top_role": top_role,
            "fixture_manifests": [
                str(REPO / "benchmarks" / "halo_fft64_reference" / "manifest.json"),
                str(REPO / "benchmarks" / "halo_fft128_reference" / "manifest.json"),
            ],
        })
        record["activity"].update({
            "scenario": ("functional transition scenario checks 64-point single "
                         "and three-frame continuous streams, reset/mode switch, "
                         "then the equivalent 128-point workloads"),
            "streaming_128_vcd_sha256": artifacts["gls_stream_128_vcd"]["sha256"],
            "annotated_pins_streaming_128": annotation_stream_128,
        })
        record["results"]["power_mw"]["streaming_window_64"] = \
            record["results"]["power_mw"].pop("streaming_window")
        record["results"]["power_mw"]["streaming_window_128"] = {
            **power_stream_128,
            "definition": "average power over the 128-point three-frame continuous-streaming burst",
        }
        record["results"]["energy_per_fft_nj"] = {
            "mode64": {
                "value": finite_window_energy_nj(power_stream["total_mw"], vcd_window_ps, 3),
                "duration_ps": vcd_window_ps,
            },
            "mode128": {
                "value": finite_window_energy_nj(power_stream_128["total_mw"], vcd_window_128_ps, 3),
                "duration_ps": vcd_window_128_ps,
            },
            "definition": "finite three-frame window energy per transform, including fill and drain",
        }
        record["results"]["throughput"] = {
            "mode64_fft_per_s": 1.0 / (64 * CLOCK_PERIOD_NS * 1e-9),
            "mode128_fft_per_s": 1.0 / (128 * CLOCK_PERIOD_NS * 1e-9),
        }
        record["results"]["area_comparison"] = {
            "candidate_placed_cell_area_um2": pnr_area_um2,
            "standalone_placed_area_sum_um2": separate_placed_area,
            "placed_reduction_vs_standalone_sum_pct":
                100.0 * (1.0 - pnr_area_um2 / separate_placed_area),
            "candidate_synthesis_cell_area_um2": synth_area_um2,
            "standalone_synthesis_area_sum_um2": separate_synth_area,
            "synthesis_reduction_vs_standalone_sum_pct":
                100.0 * (1.0 - synth_area_um2 / separate_synth_area),
            "comparison_note": ("The 44% target is an upper-bound comparison "
                                "against the sum of standalone placed areas. "
                                "The separately measured placed Dual A control "
                                "is reported independently and is not substituted "
                                "for this preregistered denominator."),
        }
        record["limitations"] += (
            " Shared area reduction is reported against the sum of standalone "
            "placed baselines; the physically measured Dual A combined-chip "
            "control is a separate comparison."
        )

    out = R / cfg["result"]
    out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"assemble_results.py: wrote {out}")
    print(f"  synth: {synth_cell_count} cells, {synth_area_um2:.1f} um2")
    print(f"  pnr:   {int(metrics['instance_count'])} instances, "
          f"{pnr_area_um2:.1f} um2, {utilization_pct:.1f}% util, "
          f"setup={setup_wns:.3f} ns, hold={hold_wns:.3f} ns, "
          f"recovery={recovery_wns:.3f} ns, removal={removal_wns:.3f} ns, "
          f"timing_met={timing_met}")
    print(f"  power (streaming): total={power_stream['total_mw']:.4f} mW "
          f"(internal={power_stream['internal_mw']:.4f}, "
          f"switching={power_stream['switching_mw']:.4f}, "
          f"leakage={power_stream['leakage_mw']:.6f})")
    print(f"  power (scenario):  total={power_scenario['total_mw']:.4f} mW")
    if design in ("shared", "dual", "dual_b"):
        print(f"  energy/FFT: mode64={record['results']['energy_per_fft_nj']['mode64']['value']:.3f} nJ, "
              f"mode128={record['results']['energy_per_fft_nj']['mode128']['value']:.3f} nJ")
        print(f"  placed reduction vs standalone sum: "
              f"{record['results']['area_comparison']['placed_reduction_vs_standalone_sum_pct']:.3f}%")
    else:
        print(f"  energy/FFT: {record['results']['energy_per_fft_nj']['value']:.3f} nJ; "
              f"throughput: {record['results']['throughput']['fft_per_s']/1e6:.4f} MFFT/s")
    print(f"  annotated pins: streaming={annotation_stream}, "
          f"scenario={annotation_scenario}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
