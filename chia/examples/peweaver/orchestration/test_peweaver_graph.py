"""No-tool tests for the graph's physical-result provenance boundary."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import peweaver_chia_graph as graph


def _write_result(root: Path, candidate_hash: str) -> None:
    result_dir = root / "source" / "physical" / "results"
    result_dir.mkdir(parents=True)
    (result_dir / "shared_baseline_sky130.json").write_text(json.dumps({
        "schema": "peweaver-physical-result-2",
        "flow_input_hashes_sha256": {
            "rtl/peweaver_shared_fft.v": candidate_hash,
        },
        "results": {
            "pnr": {
                "cell_area_um2": 1.0,
                "instance_count": 1,
                "timing_met": True,
                "setup_slack_ns": 0.1,
                "hold_slack_ns": 0.1,
            },
            "power_mw": {},
        },
        "drc_violation_lines": 0,
    }))


def test_physical_gate_binds_result_to_candidate_hash(tmp_path, monkeypatch):
    candidate_hash = "a" * 64
    _write_result(tmp_path, candidate_hash)
    monkeypatch.setattr(graph, "_run_child", lambda *args, **kwargs: ("ok", "", 0))
    result = graph.physical_gate(str(tmp_path), candidate_hash)
    assert result["passed"] is True


def test_physical_gate_rejects_result_for_different_candidate(tmp_path, monkeypatch):
    _write_result(tmp_path, "a" * 64)
    monkeypatch.setattr(graph, "_run_child", lambda *args, **kwargs: ("ok", "", 0))
    result = graph.physical_gate(str(tmp_path), "b" * 64)
    assert result["passed"] is False
    assert "physical result candidate hash mismatch" in result["errors"]
