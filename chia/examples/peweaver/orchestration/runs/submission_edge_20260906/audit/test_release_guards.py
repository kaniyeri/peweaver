#!/usr/bin/env python3
"""Adversarial smoke tests for release fail-closed guards."""

from __future__ import annotations

import importlib.util
import copy
import json
import math
from pathlib import Path


PHASE = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


replay = load_module("replay_guards", PHASE / "replay/build_replay_corpus.py")
canonical = load_module("canonical_guards", PHASE / "manifest/build_canonical_comparison.py")
release = load_module("release_consistency_guards", PHASE / "audit/verify_release_consistency.py")
figures = load_module("figure_guards", PHASE / "figures/generate_figures.py")


def run_guard_tests() -> None:
    assert replay.evaluate_fail_closed({"lint": "PASS"}, ["lint"]) == ("ADVANCE", None)
    assert replay.evaluate_fail_closed({"lint": "N/A"}, ["lint"]) == ("BLOCKED", "lint")
    assert replay.evaluate_fail_closed({"lint": "UNKNOWN"}, ["lint"]) == ("BLOCKED", "lint")
    assert replay.evaluate_fail_closed({"lint": "BROKEN"}, ["lint"]) == ("BLOCKED", "lint")
    assert replay.evaluate_fail_closed({"lint": "FAIL"}, ["lint"]) == ("REJECT", "lint")
    assert replay.evaluate_nested_configs({"evidence_status": "PARTIAL"})["config3_verdict"] == "NOT_EVALUATED"

    physical_path = PHASE.parents[2] / "physical/results/dual_baseline_sky130.json"
    result = json.loads(physical_path.read_text())
    source_path = PHASE.parents[2] / "physical/rtl/peweaver_ppa_dual_fft.v"
    source_hash = canonical.sha256_file(source_path)
    assert canonical.physical_metrics(result, "A", source_path, "rtl/peweaver_ppa_dual_fft.v", source_hash)["router_drc_lines"] == 0
    bad_bool = copy.deepcopy(result)
    bad_bool["results"]["pnr"]["timing_met"] = 1
    try:
        canonical.physical_metrics(bad_bool, "A", source_path, "rtl/peweaver_ppa_dual_fft.v", source_hash)
    except ValueError:
        pass
    else:
        raise AssertionError("integer timing status was accepted as Boolean")
    bad_drc = copy.deepcopy(result)
    bad_drc["drc_violation_lines"] = 0.0
    try:
        canonical.physical_metrics(bad_drc, "A", source_path, "rtl/peweaver_ppa_dual_fft.v", source_hash)
    except ValueError:
        pass
    else:
        raise AssertionError("float DRC count was accepted as integer")

    b_path = PHASE / "dual_b/results/physical_attempt2/dual_b_sky130.json"
    b_result = json.loads(b_path.read_text())
    b_source = PHASE.parents[2] / "physical/rtl/peweaver_ppa_dual_fft_icg.v"
    b_hash = canonical.sha256_file(b_source)
    assert canonical.physical_metrics(b_result, "B", b_source, "rtl/peweaver_ppa_dual_fft_icg.v", b_hash)["area_um2"] == 429655.0
    bad_dependency = copy.deepcopy(b_result)
    dependency_key = next(iter(bad_dependency["design"]["reference_source_hashes_sha256"]))
    bad_dependency["design"]["reference_source_hashes_sha256"][dependency_key] = "0" * 64
    try:
        canonical.physical_metrics(bad_dependency, "B", b_source, "rtl/peweaver_ppa_dual_fft_icg.v", b_hash)
    except ValueError:
        pass
    else:
        raise AssertionError("B dependent RTL hash mismatch was accepted")
    try:
        canonical.resolve_source("/etc/passwd")
    except ValueError:
        pass
    else:
        raise AssertionError("absolute source path escaped the workspace root")
    try:
        figures._finite(math.nan, "test")
    except ValueError:
        pass
    else:
        raise AssertionError("non-finite figure input was accepted")

    original_load = release.load
    assert release.verify(PHASE)["ok"], "unmodified release package did not pass semantic verification"

    def altered_load(path: Path):
        data = original_load(path)
        if path.name == "canonical_comparison.json":
            data["rows"][0]["p64_mw"] = 999999.0
        if path.name == "detection_summary.json":
            data["overall"].update({
                "evaluated_defects": 22,
                "unevaluated_defects": 0,
                "config1_detection_pct": 100.0,
                "config2_detection_pct": 100.0,
                "config3_detection_pct": 100.0,
            })
        return data

    release.load = altered_load
    assert not release.verify(PHASE)["ok"], "semantic verifier accepted fabricated canonical/replay values"
    release.load = original_load

    def duplicate_workload_load(path: Path):
        data = original_load(path)
        if path.name == "workload_metrics.json":
            data[-1] = copy.deepcopy(data[0])
        return data

    release.load = duplicate_workload_load
    assert not release.verify(PHASE)["ok"], "semantic verifier accepted a duplicate workload point"
    release.load = original_load

    def stale_manifest_load(path: Path):
        data = original_load(path)
        if path.name == "phase_manifest.json":
            data["authoritative_plan"] = "SUBMISSION_EDGE_HANDOFF_PLAN.md"
        return data

    release.load = stale_manifest_load
    assert not release.verify(PHASE)["ok"], "semantic verifier accepted a stale authoritative plan reference"
    release.load = original_load

    def missing_evidence_load(path: Path):
        data = original_load(path)
        if path.name == "candidate_by_gate_matrix.json":
            data[0]["evidence_refs"] = ["missing/evidence.json"]
        return data

    release.load = missing_evidence_load
    assert not release.verify(PHASE)["ok"], "semantic verifier accepted a missing verified evidence reference"
    release.load = original_load
    print("release guard adversarial tests passed")


def test_release_guards() -> None:
    run_guard_tests()


def main() -> None:
    run_guard_tests()


if __name__ == "__main__":
    main()
