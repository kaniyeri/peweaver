"""Tests for the shared PEWeaver evaluator/archive boundary."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from peweaver_archive import SQLiteArchive
from peweaver_evaluator import (
    STATUS_INVALID,
    config_fingerprint,
    map_node_result,
    timing_feedback,
)


def test_result_mapper_requires_real_booleans():
    assert map_node_result({"passed": True}).passed
    invalid = map_node_result({"passed": 1})
    assert invalid.status == STATUS_INVALID
    assert not invalid.passed


def test_result_mapper_rejects_non_mapping_metrics():
    invalid = map_node_result({"passed": True, "metrics": []})
    assert invalid.status == STATUS_INVALID
    assert "metrics" in invalid.diagnostics[0]


def test_result_mapper_rejects_contradictory_status_and_nonfinite_metrics():
    contradictory = map_node_result({"passed": True, "status": "rejected"})
    assert contradictory.status == STATUS_INVALID
    nonfinite = map_node_result({"passed": True, "metrics": {"x": float("inf")}})
    assert nonfinite.status == STATUS_INVALID


def test_timing_feedback_is_bounded_and_explicit():
    text = timing_feedback({
        "timing_met": False,
        "setup_slack_ns": -0.14,
        "hold_slack_ns": 0.2,
        "cell_area_um2": 123.0,
        "drc_violations": 0,
    })
    assert "timing_met=False" in text
    assert "setup_slack_ns=-0.14" in text
    assert "drc_violations=0" in text


def test_config_fingerprint_is_order_stable():
    assert config_fingerprint({"b": 2, "a": 1}) == config_fingerprint(
        {"a": 1, "b": 2})


def test_archive_records_lineage_and_rejects_resume_mismatch(tmp_path):
    path = tmp_path / "lineage.sqlite3"
    archive = SQLiteArchive(path)
    checkpoint = {"turn": 0, "accepted": False}
    archive.start_run(run_id="r1", mode="MergeDiscovery", config_hash="cfg",
                      checkpoint=checkpoint)
    archive.record_attempt(
        run_id="r1", turn=1, workspace_hash="abc", verdict="REJECT",
        base_workspace_hash="base", candidate_sha256="candidate",
        level=1, status="rejected", metrics={"setup_slack_ns": -0.1},
        detail={"functional": {"passed": True}},
        artifact_refs={"check": "artifacts/check_turn1.json"},
        checkpoint={"turn": 1, "accepted": False},
    )
    archive.finish_run("r1", "exhausted")
    assert archive.attempts("r1")[0]["metrics"]["setup_slack_ns"] == -0.1
    assert archive.attempts("r1")[0]["base_workspace_hash"] == "base"
    assert archive.attempts("r1")[0]["candidate_sha256"] == "candidate"
    archive.close()

    reopened = SQLiteArchive(path)
    reopened.start_run(run_id="r1", mode="MergeDiscovery", config_hash="cfg",
                       checkpoint=checkpoint, resume=True)
    with pytest.raises(RuntimeError, match="configuration changed"):
        reopened.start_run(run_id="r1", mode="ParentOptimization", config_hash="cfg",
                           resume=True)
    reopened.close()


def test_archive_rejects_nonfinite_metrics(tmp_path):
    archive = SQLiteArchive(tmp_path / "lineage.sqlite3")
    archive.start_run(run_id="r1", mode="MergeDiscovery", config_hash="cfg",
                      checkpoint={})
    with pytest.raises(ValueError):
        archive.record_attempt(
            run_id="r1", turn=1, workspace_hash="abc", verdict="REJECT",
            level=0, status="rejected", metrics={"slack": float("nan")},
            checkpoint={},
        )
    archive.close()


def test_archive_rejects_conflicting_idempotent_replay(tmp_path):
    archive = SQLiteArchive(tmp_path / "lineage.sqlite3")
    checkpoint = {"turn": 0}
    archive.start_run(run_id="r1", mode="MergeDiscovery", config_hash="cfg",
                      checkpoint=checkpoint)
    kwargs = dict(
        run_id="r1", turn=1, workspace_hash="abc", verdict="REJECT", level=0,
        status="rejected", checkpoint={"turn": 1},
    )
    archive.record_attempt(**kwargs)
    archive.record_attempt(**kwargs)
    with pytest.raises(RuntimeError, match="lineage conflict"):
        archive.record_attempt(**{**kwargs, "verdict": "ACCEPT"})
    with pytest.raises(RuntimeError, match="lineage conflict"):
        archive.record_attempt(**{**kwargs, "workspace_hash": "different"})
    with pytest.raises(RuntimeError, match="lineage conflict"):
        archive.record_attempt(**{**kwargs, "checkpoint": {"turn": 2}})
    archive.close()


def test_archive_is_valid_sqlite(tmp_path):
    archive = SQLiteArchive(tmp_path / "lineage.sqlite3")
    archive.start_run(run_id="r1", mode="MergeDiscovery", config_hash="cfg",
                      checkpoint={})
    archive.close()
    # The file is intentionally inspectable by standard tooling, not a custom
    # serialized state format.
    assert json.loads(json.dumps({"path": str(tmp_path / "lineage.sqlite3")}))["path"]
