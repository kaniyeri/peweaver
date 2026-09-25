#!/usr/bin/env python3
"""CHIA-Native Power Reduction Evaluator Nodes.

Domain-neutral ``@ChiaFunction`` evaluator nodes for activity-based physical
power estimation and verification on SkyWater 130nm standard cells:
- ``power_activity_node``: executes OpenSTA activity-based power extraction (VCD + Liberty)
- ``power_pareto_judge``: evaluates candidate power vs baseline across sequential, combinational, and total dissipation
"""

from __future__ import annotations

import math
import hashlib
import re
import subprocess
from pathlib import Path
from typing import Any, Callable

from chia.base.ChiaFunction import ChiaFunction

from chia_merge import GateOutcome
from evaluator_nodes import RetryableError, dispatch


@ChiaFunction(resources={"yosys": 1})
def power_activity_node(
    netlist_path: str,
    vcd_path: str,
    top_module: str,
    tb_scope: str,
    lib_path: str,
    work_dir: str,
    clk_name: str = "clock",
    clk_period_ns: float = 10.0,
    timeout_s: int = 300,
    sta_path: str = "/usr/bin/sta",
) -> dict[str, Any]:
    """Execute OpenSTA to compute activity-based power from a gate-level netlist and VCD trace.

    Returns structured power breakdown in milliwatts (mW) and micro-watts (uW).
    Raises RetryableError on tool failure or missing inputs.
    """
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    netlist = Path(netlist_path).resolve()
    vcd = Path(vcd_path).resolve()
    lib = Path(lib_path).resolve()

    if not netlist.is_file():
        raise RetryableError(f"Netlist file not found: {netlist}")
    if not vcd.is_file():
        raise RetryableError(f"VCD activity file not found: {vcd}")
    if not lib.is_file():
        raise RetryableError(f"Liberty file not found: {lib}")

    sta = Path(sta_path)
    if not sta.is_file():
        raise RetryableError(f"OpenSTA executable not found: {sta}")

    # OpenSTA needs the signedness normalization used by the existing flow, but
    # the controller must never mutate a protected input artifact.
    content = netlist.read_text()
    normalized_netlist = work / f"{netlist.name}.sta_input.v"
    normalized_netlist.write_text(re.sub(r"\bsigned\b", "", content))

    def tcl_path(path: Path) -> str:
        return "{" + str(path).replace("}", "\\}") + "}"

    tcl_script = work / f"power_{netlist.stem}.tcl"
    tcl_script.write_text(f"""
read_liberty {tcl_path(lib)}
read_verilog {tcl_path(normalized_netlist)}
link_design {top_module}
create_clock -name {{{clk_name}}} -period {clk_period_ns} [get_ports {{{clk_name}}}]
set_input_delay -clock {{{clk_name}}} 1.0 [all_inputs -no_clocks]
set_output_delay -clock {{{clk_name}}} 1.0 [all_outputs]
read_power_activities -scope {{{tb_scope}}} -vcd {tcl_path(vcd)}
report_power -digits 6
""")

    cmd = [str(sta), str(tcl_script)]
    try:
        res = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            cwd=str(work), timeout=timeout_s
        )
    except subprocess.TimeoutExpired:
        raise RetryableError(f"OpenSTA power analysis timed out after {timeout_s}s")
    except Exception as exc:
        raise RetryableError(f"OpenSTA execution failed: {exc}")

    if res.returncode != 0:
        raise RetryableError(f"OpenSTA returned non-zero ({res.returncode}):\n{res.stdout}")

    rows: dict[str, tuple[float, float, float, float]] = {}
    annotated_pins = 0

    for line in res.stdout.splitlines():
        if "Annotated" in line and "pin activities" in line:
            m = re.search(r"Annotated\s+(\d+)\s+pin activities", line)
            if m:
                annotated_pins = int(m.group(1))
        parts = line.split()
        if parts and parts[0] in {"Sequential", "Combinational", "Total"}:
            if len(parts) < 5:
                raise RetryableError(f"Malformed OpenSTA power row: {line}")
            try:
                rows[parts[0]] = (float(parts[1]) * 1000.0,
                                  float(parts[2]) * 1000.0,
                                  float(parts[3]) * 1e6,
                                  float(parts[4]) * 1000.0)
            except ValueError as exc:
                raise RetryableError(f"Malformed OpenSTA power row: {line}") from exc

    required = {"Sequential", "Combinational", "Total"}
    if annotated_pins <= 0 or not required.issubset(rows):
        raise RetryableError(
            "OpenSTA power report incomplete: "
            f"annotated_pins={annotated_pins}, rows={sorted(rows)}")
    values = [value for row in rows.values() for value in row]
    if any(not math.isfinite(value) or value < 0.0 for value in values):
        raise RetryableError("OpenSTA power report contains invalid values")

    seq = rows["Sequential"]
    comb = rows["Combinational"]
    total = rows["Total"]
    if total[3] <= 0.0:
        raise RetryableError("OpenSTA reported non-positive total power")

    return {
        "passed": True,
        "annotated_pins": annotated_pins,
        "total_mW": total[3],
        "comb_mW": comb[3],
        "seq_mW": seq[3],
        "switch_mW": total[1],
        "leak_uW": total[2],
        "netlist_sha256": hashlib.sha256(netlist.read_bytes()).hexdigest(),
        "sta_input_sha256": hashlib.sha256(
            normalized_netlist.read_bytes()).hexdigest(),
        "sta_output": res.stdout,
    }


@ChiaFunction(resources={"yosys": 1})
def power_pareto_judge(
    baseline: dict[str, float],
    candidate: dict[str, float],
    min_total_drop_pct: float = 5.0,
    objective_names: tuple[str, ...] = ("total_mW",),
) -> dict[str, Any]:
    """Classify a candidate against a baseline under all-minimize objectives."""
    names = tuple(objective_names)
    if not names:
        return {"passed": False, "verdict": "INVALID",
                "detail": "objective_names must not be empty"}
    try:
        b_values = {name: float(baseline[name]) for name in names}
        c_values = {name: float(candidate[name]) for name in names}
    except (KeyError, TypeError, ValueError) as exc:
        return {"passed": False, "verdict": "INVALID",
                "detail": f"missing or nonnumeric objective: {exc}"}
    if any(not math.isfinite(value) for value in
           (*b_values.values(), *c_values.values())):
        return {"passed": False, "verdict": "INVALID",
                "detail": "objective values must be finite"}

    b_tot = float(baseline.get("total_mW", float("nan")))
    c_tot = float(candidate.get("total_mW", float("nan")))
    if not math.isfinite(b_tot) or not math.isfinite(c_tot) or b_tot <= 0.0:
        return {"passed": False, "verdict": "INVALID",
                "detail": "total_mW baseline must be positive and finite"}

    drop_tot = ((b_tot - c_tot) / b_tot) * 100.0 if b_tot > 0 else 0.0
    candidate_dominates = (
        all(c_values[name] <= b_values[name] for name in names)
        and any(c_values[name] < b_values[name] for name in names))
    baseline_dominates = (
        all(b_values[name] <= c_values[name] for name in names)
        and any(b_values[name] < c_values[name] for name in names))
    if candidate_dominates:
        verdict = "PARETO"
    elif baseline_dominates:
        verdict = "DOMINATED"
    else:
        verdict = "INCOMPARABLE"
    target_met = drop_tot >= min_total_drop_pct
    b_seq = float(baseline.get("seq_mW", 0.0))
    c_seq = float(candidate.get("seq_mW", 0.0))
    drop_seq = ((b_seq - c_seq) / b_seq) * 100.0 if b_seq > 0 else 0.0
    return {
        "passed": candidate_dominates and target_met,
        "drop_total_pct": drop_tot,
        "drop_seq_pct": drop_seq,
        "target_met": target_met,
        "verdict": verdict,
        "objectives": {name: {"baseline": b_values[name],
                               "candidate": c_values[name],
                               "delta": c_values[name] - b_values[name]}
                        for name in names},
        "detail": f"Pareto={verdict}; total power drop={drop_tot:+.2f}% "
                   f"(required >= {min_total_drop_pct:.1f}%); "
                   f"sequential power drop={drop_seq:+.2f}%",
    }


def make_power_activity_gate(
    baseline: dict[str, float],
    *,
    netlist_name: str,
    vcd_name: str,
    top_module: str,
    tb_scope: str,
    lib_path: str,
    objective_names: tuple[str, ...] = ("total_mW",),
    clk_name: str = "clock",
    clk_period_ns: float = 10.0,
    sta_path: str = "/usr/bin/sta",
) -> Callable[[Path], GateOutcome]:
    """Build a ChiaPowerSave-compatible measured-power gate.

    The returned gate accepts a sandbox containing a candidate netlist and its
    activity VCD.  It measures the candidate through ``dispatch`` and records
    the Pareto relation as diagnostics; ChiaPowerSave remains responsible for
    archive promotion, dominance, targets, and hard constraints.  Equal to the
    baseline is therefore valid for incumbent seeding and final repeats.
    """
    def gate(sandbox: Path) -> GateOutcome:
        netlist = sandbox / netlist_name
        vcd = sandbox / vcd_name
        if not netlist.is_file() or not vcd.is_file():
            return GateOutcome(
                "power_activity", False,
                note=f"missing activity artifacts: {netlist.name}/{vcd.name}")
        work = sandbox / ".power_activity"
        measured = dispatch(
            power_activity_node,
            str(netlist), str(vcd), top_module, tb_scope, lib_path, str(work),
            clk_name=clk_name, clk_period_ns=clk_period_ns,
            sta_path=sta_path, name="power_activity")
        if not measured.passed:
            return GateOutcome(
                "power_activity", False, note=measured.note,
                retry=measured.retry, detail=measured.detail)
        metrics = {key: value for key, value in measured.detail.items()
                   if isinstance(value, (int, float))
                   and not isinstance(value, bool)}
        judged = dispatch(
            power_pareto_judge, baseline, metrics,
            objective_names=objective_names, name="power_pareto")
        detail = dict(measured.detail)
        detail["pareto_verdict"] = judged.detail.get("verdict", "")
        detail["pareto_objectives"] = judged.detail.get("objectives", {})
        if not judged.passed and judged.detail.get("verdict") == "INVALID":
            return GateOutcome(
                "power_activity", False,
                note=f"invalid power objectives: {judged.note}",
                retry=judged.retry, detail=detail)
        return GateOutcome(
            "power_activity", True,
            note=f"activity power measured; Pareto={judged.detail.get('verdict', '')}",
            detail=detail)

    return gate
