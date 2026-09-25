#!/usr/bin/env python3
"""Unit and integration tests for CHIA-native power nodes (chia_power_nodes.py)."""

from __future__ import annotations

import subprocess
import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.resolve()))

from chia_merge import GateOutcome
import chia_power_nodes as nodes
from chia_power_nodes import (make_power_activity_gate, power_activity_node,
                              power_pareto_judge)
from evaluator_nodes import RetryableError


def test_power_pareto_judge_acceptance():
    baseline = {"total_mW": 1.0, "seq_mW": 0.5, "comb_mW": 0.5}
    candidate = {"total_mW": 0.75, "seq_mW": 0.25, "comb_mW": 0.5}
    res = power_pareto_judge(baseline, candidate, min_total_drop_pct=10.0)
    assert res["passed"] is True
    assert res["verdict"] == "PARETO"
    assert res["drop_total_pct"] == pytest.approx(25.0)
    assert res["drop_seq_pct"] == pytest.approx(50.0)


def test_power_pareto_judge_rejection():
    baseline = {"total_mW": 1.0, "seq_mW": 0.5, "comb_mW": 0.5}
    candidate = {"total_mW": 0.98, "seq_mW": 0.49, "comb_mW": 0.49}
    res = power_pareto_judge(baseline, candidate, min_total_drop_pct=5.0)
    assert res["passed"] is False
    assert res["verdict"] == "PARETO"
    assert res["target_met"] is False
    assert res["drop_total_pct"] == pytest.approx(2.0)


def test_power_pareto_judge_reports_component_regression():
    baseline = {"total_mW": 1.0, "switch_mW": 1.0}
    candidate = {"total_mW": 0.75, "switch_mW": 1.1}
    res = power_pareto_judge(
        baseline, candidate, objective_names=("total_mW", "switch_mW"))
    assert res["passed"] is False
    assert res["verdict"] == "INCOMPARABLE"
    assert res["target_met"] is True


def test_power_activity_does_not_mutate_input_and_parses_rows(tmp_path, monkeypatch):
    netlist = tmp_path / "candidate.v"
    original = "module top(input clock); wire signed x; endmodule\n"
    netlist.write_text(original)
    vcd = tmp_path / "activity.vcd"
    lib = tmp_path / "corner.lib"
    sta = tmp_path / "sta"
    vcd.write_text("vcd")
    lib.write_text("liberty")
    sta.write_text("stub")

    report = """Annotated 10 pin activities.
Sequential           1e-4 2e-4 3e-10 3e-4  30.0%
Combinational        2e-4 3e-4 4e-10 5e-4  50.0%
Total                3e-4 5e-4 7e-10 8e-4  80.0%
"""

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, report, "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = power_activity_node(
        netlist_path=str(netlist), vcd_path=str(vcd), top_module="top",
        tb_scope="tb/dut", lib_path=str(lib), work_dir=str(tmp_path),
        sta_path=str(sta))
    assert result["passed"] is True
    assert result["total_mW"] == pytest.approx(0.8)
    assert netlist.read_text() == original


def test_power_activity_fails_closed_on_missing_rows(tmp_path, monkeypatch):
    netlist = tmp_path / "candidate.v"
    netlist.write_text("module top(input clock); endmodule\n")
    vcd = tmp_path / "activity.vcd"
    lib = tmp_path / "corner.lib"
    sta = tmp_path / "sta"
    vcd.write_text("vcd")
    lib.write_text("liberty")
    sta.write_text("stub")

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, "report_power\n", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(RetryableError, match="incomplete"):
        power_activity_node(
            netlist_path=str(netlist), vcd_path=str(vcd), top_module="top",
            tb_scope="tb/dut", lib_path=str(lib), work_dir=str(tmp_path),
            sta_path=str(sta))


def test_power_activity_gate_is_usable_by_chia_power_save(tmp_path, monkeypatch):
    (tmp_path / "candidate.v").write_text("candidate")
    (tmp_path / "activity.vcd").write_text("activity")
    calls = []

    def fake_dispatch(node, *args, name, **kwargs):
        calls.append(name)
        if node is nodes.power_activity_node:
            return GateOutcome(
                name, True, detail={"total_mW": 0.75, "switch_mW": 0.8,
                                    "seq_mW": 0.2})
        return GateOutcome(
            name, True, detail={"verdict": "PARETO",
                                "objectives": {"total_mW": {}}})

    monkeypatch.setattr(nodes, "dispatch", fake_dispatch)
    gate = make_power_activity_gate(
        {"total_mW": 1.0}, netlist_name="candidate.v",
        vcd_name="activity.vcd", top_module="top", tb_scope="tb/dut",
        lib_path="corner.lib")
    result = gate(tmp_path)
    assert result.passed is True
    assert result.detail["total_mW"] == pytest.approx(0.75)
    assert calls == ["power_activity", "power_pareto"]


def test_power_activity_gate_rejects_invalid_objectives(tmp_path, monkeypatch):
    (tmp_path / "candidate.v").write_text("candidate")
    (tmp_path / "activity.vcd").write_text("activity")

    def fake_dispatch(node, *args, name, **kwargs):
        if node is nodes.power_activity_node:
            return GateOutcome(name, True, detail={"total_mW": 0.75})
        return GateOutcome(name, False, note="nonfinite", detail={
            "verdict": "INVALID"})

    monkeypatch.setattr(nodes, "dispatch", fake_dispatch)
    gate = make_power_activity_gate(
        {"total_mW": 1.0}, netlist_name="candidate.v",
        vcd_name="activity.vcd", top_module="top", tb_scope="tb/dut",
        lib_path="corner.lib")
    result = gate(tmp_path)
    assert result.passed is False
    assert "invalid power objectives" in result.note


def test_missing_files_raise_retryable_error(tmp_path):
    with pytest.raises(RetryableError, match="Netlist file not found"):
        power_activity_node(
            netlist_path=str(tmp_path / "nonexistent.v"),
            vcd_path=str(tmp_path / "dummy.vcd"),
            top_module="dummy",
            tb_scope="tb/dut",
            lib_path=str(tmp_path / "dummy.lib"),
            work_dir=str(tmp_path),
        )


def test_live_power_node_integration():
    """Verify live power_activity_node against the synthesized MAC netlist and VCD if present."""
    mac_run = Path("/work/peweaver/runs/chia_power_reduction/mac")
    netlist = mac_run / "mac_base_sky130.v"
    vcd = mac_run / "activity_base.vcd"
    lib = Path("/work/peweaver/toolchains/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib")

    if not (netlist.is_file() and vcd.is_file() and lib.is_file()):
        pytest.skip("Physical artifacts not yet present on local system (VM integration test)")

    res = power_activity_node(
        netlist_path=str(netlist),
        vcd_path=str(vcd),
        top_module="shared_mac",
        tb_scope="mac_power_tb/dut",
        lib_path=str(lib),
        work_dir=str(mac_run),
        clk_name="clock",
        clk_period_ns=10.0,
    )

    assert res["passed"] is True
    assert res["annotated_pins"] > 1000
    assert res["total_mW"] > 0.1
    assert res["seq_mW"] > 0.05
    assert res["comb_mW"] > 0.1
