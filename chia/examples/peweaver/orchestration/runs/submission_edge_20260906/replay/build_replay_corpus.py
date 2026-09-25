#!/usr/bin/env python3
"""Build and evaluate the frozen Evaluator Replay Corpus (WP3).

Empirically parses primary artifacts and evaluates 31 candidates across
5 explicit strata against nested evaluator configurations:
  Config 1: Functional checks only (lint, randomized oracle, holdout)
  Config 2: Functional + Mapped Netlist GLS
  Config 3: Full gate ladder (domain-appropriate gates including STA, DRC, structure, formal, provenance)

Design rules:
  - Fail-closed: UNKNOWN or missing required evidence rejects/blocks advance.
  - Domain specificity: MAC and FIR ladders use formal and cell-floor gates, not physical P&R gates.
  - No fabricated measurements: timing failures report timing_met=False without invented slacks.
"""

from __future__ import annotations

import json
import hashlib
import math
import re
from pathlib import Path

REPLAY_DIR = Path(__file__).resolve().parent
RUNS_DIR = REPLAY_DIR.parents[1]  # chia/examples/peweaver/orchestration/runs
VALID_STATUSES = {"PASS", "FAIL", "BLOCKED", "UNKNOWN", "N/A"}


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def load_ps_turn_evidence(turn: int) -> dict:
    """Load actual check and physical JSON for a ps-fft-6 turn."""
    check_p = RUNS_DIR / "ps_fft_campaign" / "artifacts" / f"check_turn{turn}.json"
    phys_p = RUNS_DIR / "ps_fft_campaign" / "artifacts" / f"physical_turn{turn}.json"
    
    check_data = json.load(open(check_p)) if check_p.is_file() else None
    phys_data = json.load(open(phys_p)) if phys_p.is_file() else None
    return {"check": check_data, "physical": phys_data}


def load_mac_mutation_evidence() -> dict:
    """Load actual MAC mutation report."""
    mut_p = RUNS_DIR / "mac-mutants-1" / "mutation_report.json"
    return json.load(open(mut_p)) if mut_p.is_file() else {}


def _path(rel: str) -> Path:
    return RUNS_DIR / rel


def _physical_pass(path: Path) -> bool:
    if not path.is_file():
        return False
    data = json.loads(path.read_text())
    result = data.get("results", {})
    pnr = result.get("pnr", {})
    return (
        data.get("drc_violation_lines") == 0
        and pnr.get("timing_met") is True
        and pnr.get("total_negative_slack_max_ns") == 0.0
        and data.get("activity", {}).get("annotated_pins_streaming", 0) > 0
    )


def _physical_gls_pass(data: dict) -> bool:
    """Require explicit mapped-GLS artifacts and nonzero annotated activity."""
    activity = data.get("activity", {})
    artifacts = data.get("artifacts", {})
    required = ("gls_scenario_vcd", "gls_stream_vcd", "gls_stream_128_vcd", "gls_stream_run_log", "gls_stream_128_log")
    return (
        isinstance(activity.get("annotated_pins_streaming"), int)
        and not isinstance(activity.get("annotated_pins_streaming"), bool)
        and activity.get("annotated_pins_streaming", 0) > 0
        and isinstance(activity.get("annotated_pins_streaming_128"), int)
        and not isinstance(activity.get("annotated_pins_streaming_128"), bool)
        and activity.get("annotated_pins_streaming_128", 0) > 0
        and all(
            _is_sha256(artifacts.get(name, {}).get("sha256"))
            and isinstance(artifacts[name].get("bytes"), int)
            and not isinstance(artifacts[name].get("bytes"), bool)
            and artifacts[name]["bytes"] >= 0
            for name in required
        )
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repeat_physical_evidence_pass() -> bool:
    result_path = REPLAY_DIR / "s0_physical_repeat_20260909" / "physical_artifacts" / "results" / "shared_baseline_sky130.json"
    audit_path = REPLAY_DIR / "s0_physical_repeat_20260909" / "s0_physical_repeat_audit.json"
    if not result_path.is_file():
        return False
    data = json.loads(result_path.read_text())
    if not audit_path.is_file():
        return False
    audit = json.loads(audit_path.read_text())
    primary_path = _path("merge_clean_1/shared_mergerun1_sky130.json")
    published_result_path = REPLAY_DIR / "s0_physical_repeat_20260909" / "s0_physical_repeat_sky130.json"
    if not primary_path.is_file() or not published_result_path.is_file():
        return False
    primary = json.loads(primary_path.read_text())
    published = json.loads(published_result_path.read_text())
    if _sha256_file(published_result_path) != _sha256_file(result_path):
        return False
    pnr = data.get("results", {}).get("pnr", {})
    power = data.get("results", {}).get("power_mw", {})
    energy = data.get("results", {}).get("energy_per_fft_nj", {})
    primary_pnr = primary.get("results", {}).get("pnr", {})
    primary_power = primary.get("results", {}).get("power_mw", {})
    primary_energy = primary.get("results", {}).get("energy_per_fft_nj", {})
    audit_metrics = audit.get("metrics", {})
    def same_number(left: object, right: object) -> bool:
        return isinstance(left, (int, float)) and isinstance(right, (int, float)) and abs(left - right) <= 1e-9

    metrics_match = (
        same_number(audit_metrics.get("placed_cell_area_um2"), pnr.get("cell_area_um2"))
        and audit_metrics.get("timing_met") is pnr.get("timing_met")
        and same_number(audit_metrics.get("tns_ns"), pnr.get("total_negative_slack_max_ns"))
        and audit_metrics.get("router_drc_violation_lines") == data.get("drc_violation_lines")
        and same_number(audit_metrics.get("p64_mw"), power.get("streaming_window_64", {}).get("total_mw"))
        and same_number(audit_metrics.get("p128_mw"), power.get("streaming_window_128", {}).get("total_mw"))
        and same_number(audit_metrics.get("e64_nj"), energy.get("mode64", {}).get("value"))
        and same_number(audit_metrics.get("e128_nj"), energy.get("mode128", {}).get("value"))
    )
    def result_metrics_match(other: dict) -> bool:
        other_pnr = other.get("results", {}).get("pnr", {})
        other_power = other.get("results", {}).get("power_mw", {})
        other_energy = other.get("results", {}).get("energy_per_fft_nj", {})
        return (
            same_number(pnr.get("cell_area_um2"), other_pnr.get("cell_area_um2"))
            and pnr.get("timing_met") is other_pnr.get("timing_met")
            and same_number(pnr.get("total_negative_slack_max_ns"), other_pnr.get("total_negative_slack_max_ns"))
            and data.get("drc_violation_lines") == other.get("drc_violation_lines")
            and same_number(power.get("streaming_window_64", {}).get("total_mw"), other_power.get("streaming_window_64", {}).get("total_mw"))
            and same_number(power.get("streaming_window_128", {}).get("total_mw"), other_power.get("streaming_window_128", {}).get("total_mw"))
            and same_number(energy.get("mode64", {}).get("value"), other_energy.get("mode64", {}).get("value"))
            and same_number(energy.get("mode128", {}).get("value"), other_energy.get("mode128", {}).get("value"))
        )

    if (
        audit.get("repeat", {}).get("status") != "PASS"
        or audit.get("repeat", {}).get("result_sha256") != _sha256_file(result_path)
        or audit.get("candidate", {}).get("rtl_sha256") != data.get("design", {}).get("reference_source_hashes_sha256", {}).get("rtl/peweaver_shared_fft.v")
        or not metrics_match
        or not result_metrics_match(primary)
        or not result_metrics_match(published)
        or not all(audit.get("comparison_to_primary_s0", {}).get(name) is True for name in (
            "area_equal", "timing_equal", "tns_equal", "drc_equal", "p64_equal", "p128_equal", "e64_equal", "e128_equal"
        ))
    ):
        return False
    source_path = _path("merge_clean_1/peweaver_shared_fft.mergerun1.v")
    source_hash = _sha256_file(source_path) if source_path.is_file() else None
    wrapper_path = (
        REPLAY_DIR.parent / "audit/frozen_sources/peweaver_ppa_shared_fft.v")
    wrapper_hash = _sha256_file(wrapper_path) if wrapper_path.is_file() else None
    design = data.get("design", {})
    flow_hashes = data.get("flow_input_hashes_sha256", {})
    if source_hash is None or design.get("reference_source_hashes_sha256", {}).get("rtl/peweaver_shared_fft.v") != source_hash:
        return False
    if wrapper_hash is None or flow_hashes.get("rtl/peweaver_ppa_shared_fft.v") != wrapper_hash:
        return False
    if data.get("pdk", {}).get("timing_corner") != "tt_025C_1v80":
        return False
    activity = data.get("activity", {})
    metrics = data.get("results", {})
    pnr = metrics.get("pnr", {})
    power = metrics.get("power_mw", {})
    energy = metrics.get("energy_per_fft_nj", {})
    if any(
        not isinstance(activity.get(name), int)
        or isinstance(activity.get(name), bool)
        or activity.get(name, 0) <= 0
        for name in ("annotated_pins_streaming", "annotated_pins_streaming_128")
    ):
        return False
    if pnr.get("timing_met") is not True or pnr.get("total_negative_slack_max_ns") != 0.0 or data.get("drc_violation_lines") != 0:
        return False
    if any(power.get(name, {}).get("total_mw", 0) <= 0 for name in ("streaming_window_64", "streaming_window_128")):
        return False
    if any(energy.get(name, {}).get("value", 0) <= 0 for name in ("mode64", "mode128")):
        return False
    for mode, power_key in (("mode64", "streaming_window_64"), ("mode128", "streaming_window_128")):
        duration = energy.get(mode, {}).get("duration_ps")
        value = energy.get(mode, {}).get("value")
        total = power.get(power_key, {}).get("total_mw")
        if not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0:
            return False
        if not all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) for value in (value, total)):
            return False
        if abs(value - total * duration / 3_000_000.0) > 1e-6:
            return False
    artifact_root = REPLAY_DIR / "s0_physical_repeat_20260909" / "physical_artifacts" / "results"
    artifacts = data.get("artifacts", {})
    for name, record in artifacts.items():
        if not isinstance(record, dict) or not _is_sha256(record.get("sha256")):
            return False
        record = artifacts.get(name, {})
        remote = record.get("path", "")
        marker = "/examples/peweaver/physical/results/"
        if marker not in remote:
            return False
        relative = Path(remote.split(marker, 1)[1])
        local = (artifact_root / relative).resolve()
        try:
            local.relative_to(artifact_root.resolve())
        except ValueError:
            return False
        if not isinstance(record.get("bytes"), int) or isinstance(record.get("bytes"), bool) or record["bytes"] < 0:
            return False
        if not local.is_file() or local.stat().st_size != record.get("bytes"):
            return False
        if _sha256_file(local) != record.get("sha256"):
            return False
    return True


def _repeat_gls_evidence_pass() -> bool:
    """Check the archived GLS logs for completion and functional markers."""
    log_root = REPLAY_DIR / "s0_physical_repeat_20260909" / "physical_artifacts" / "results" / "logs"
    required_markers = {
        "iverilog_gls_scenario_shared_run.log": ("[PASS] mode64_single", "[PASS] mode128_single", "PEWEAVER_ACTIVITY_DONE"),
        "iverilog_gls_stream_shared_run.log": ("PEWEAVER_ACTIVITY_DONE",),
        "iverilog_gls_stream_128_shared_run.log": ("PEWEAVER_ACTIVITY_DONE",),
    }
    for name, markers in required_markers.items():
        path = log_root / name
        if not path.is_file():
            return False
        text = path.read_text()
        if any(marker not in text for marker in markers):
            return False
        if "PEWEAVER_ACTIVITY_ERROR" in text or re.search(r"(?m)^\s*(?:\[FAIL\]|FATAL(?:\b|:)|ERROR(?:\b|:))", text):
            return False
    return True


def _set_fft_s0_gates(item: dict, check: dict, physical: dict, holdout: dict, repeat_ok: bool) -> bool:
    """Populate S0 gates solely from the linked check, holdout, and P&R reports."""
    detail = check.get("detail", {})
    pnr = physical.get("results", {}).get("pnr", {})
    source = _path("merge_clean_1/peweaver_shared_fft.mergerun1.v")
    source_hash = _sha256_file(source) if source.is_file() else None
    flow_hashes = physical.get("flow_input_hashes_sha256", {})
    holdout_suite = holdout.get("suite", {})
    holdout_candidate = holdout.get("candidate")
    holdout_path_ok = isinstance(holdout_candidate, str) and Path(holdout_candidate).resolve() == source.resolve()
    holdout_structured = (
        isinstance(holdout_suite, dict)
        and isinstance(holdout_suite.get("passed"), bool)
        and isinstance(holdout_suite.get("cases"), int)
        and not isinstance(holdout_suite.get("cases"), bool)
        and holdout_suite.get("cases") == 36
        and isinstance(holdout_suite.get("failed"), list)
        and holdout_path_ok
    )
    provenance = (
        source_hash is not None
        and physical.get("design", {}).get("reference_source_hashes_sha256", {}).get("rtl/peweaver_shared_fft.v") == source_hash
        and flow_hashes.get("rtl/peweaver_shared_fft.v") == source_hash
        and isinstance(flow_hashes.get("run-physical.sh"), str)
        and len(flow_hashes["run-physical.sh"]) == 64
        and repeat_ok
    )
    def status(section: dict, key: str = "passed") -> str:
        value = section.get(key)
        return "PASS" if value is True else "FAIL" if value is False else "UNKNOWN"

    item["gates"] = {
        "lint": status(detail.get("lint", {})),
        "oracle": status(detail.get("functional", {})),
        "holdout": "PASS" if holdout_structured and holdout_suite.get("passed") is True and not holdout_suite.get("failed") else "FAIL" if holdout_structured else "UNKNOWN",
        "gls": "PASS" if _physical_gls_pass(physical) and _repeat_gls_evidence_pass() else "FAIL",
        "timing": "PASS" if pnr.get("timing_met") is True and pnr.get("total_negative_slack_max_ns") == 0.0 else "FAIL" if isinstance(pnr.get("timing_met"), bool) and isinstance(pnr.get("total_negative_slack_max_ns"), (int, float)) else "UNKNOWN",
        "drc": "PASS" if physical.get("drc_violation_lines") == 0 else "FAIL" if isinstance(physical.get("drc_violation_lines"), int) and not isinstance(physical.get("drc_violation_lines"), bool) else "UNKNOWN",
        "provenance": "PASS" if provenance else "FAIL",
    }
    item["evidence_observations"] = {
        "holdout_cases": holdout_suite.get("cases"),
        "holdout_candidate_sha256": source_hash,
        "exact_latency_contract": "checked by the controller holdout testbench; report records pass/fail only",
        "physical": "primary mapped-GLS/P&R report plus independent repeat are hash-bound and artifact-validated",
        "source_sha256": source_hash,
    }
    return holdout_structured and repeat_ok and all(status != "UNKNOWN" for status in item["gates"].values())


def _set_mac_check_gates(item: dict, check_path: Path, candidate_path: Path, manifest_path: Path) -> bool:
    if not check_path.is_file() or not candidate_path.is_file() or not manifest_path.is_file():
        return False
    data = json.loads(check_path.read_text())
    manifest = json.loads(manifest_path.read_text())
    detail = data.get("detail", {})
    required = ("lint", "functional", "corners", "structure", "area", "formal")
    if data.get("verdict") != "ACCEPT" or data.get("level") != 6:
        return False
    candidate_hash = _sha256_file(candidate_path)
    if manifest.get("shared_mac.v") != candidate_hash:
        return False
    mac_number = item["id"].rsplit("m", 1)[-1]
    hidden_ref = f"submission_edge_20260906/mac_hidden_judge/m{mac_number}_fixed/hidden_judge_report.json"
    hidden_path = _path(hidden_ref)
    if not hidden_path.is_file():
        return False
    hidden_root = hidden_path.parent
    for capture in (hidden_root / "hidden_seed/stim.txt", hidden_root / "hidden_seed/cap.txt", hidden_root / "hidden_corners/stim.txt", hidden_root / "hidden_corners/cap.txt"):
        if not capture.is_file() or capture.stat().st_size == 0:
            return False
    hidden = json.loads(hidden_path.read_text())
    if (
        hidden.get("verified") is not True
        or hidden.get("hidden_seed") != 0x7EEDBEEF
        or hidden.get("hidden_randomized", {}).get("passed") is not True
        or hidden.get("directed_corners", {}).get("passed") is not True
        or Path(hidden.get("candidate", "")).resolve() != candidate_path.resolve()
    ):
        return False
    if any(not isinstance(detail.get(name, {}).get("passed"), bool) for name in required):
        return False
    aliases = {
        "lint": "lint", "functional": "oracle", "corners": "corners",
        "structure": "structure", "area": "area", "formal": "formal",
    }
    for source, target in aliases.items():
        item["gates"][target] = "PASS" if detail[source]["passed"] else "FAIL"
    item["gates"]["provenance"] = "PASS" if manifest.get("shared_mac.v") == candidate_hash else "FAIL"
    item["evidence_observations"] = {
        name: detail[name].get("note", "") for name in required
    }
    item["evidence_observations"]["candidate_sha256"] = candidate_hash
    item["evidence_observations"]["hidden_judge"] = hidden_ref
    return True


def attach_evidence(corpus: list[dict]) -> None:
    """Attach evidence provenance and mark which rows support statistics.

    The historical corpus contains useful declarations that do not have a
    complete local gate report. They remain in the ledger, but cannot silently
    become evaluated results.
    """
    for item in corpus:
        item["evidence_status"] = "UNVERIFIED"
        item["evidence_refs"] = []
        item["evaluation_scope"] = "not_evaluated"

    by_id = {item["id"]: item for item in corpus}

    s0 = by_id["acc_fft_s0"]
    s0_refs = [
        "merge_clean_1/check_turn32.json",
        "merge_clean_1/shared_mergerun1_sky130.json",
        "submission_edge_20260906/replay/final_s0_hidden_holdout/hidden_holdout_report.json",
        "submission_edge_20260906/replay/final_s0_hidden_holdout/run.log",
    ]
    repeat_refs = [
        "submission_edge_20260906/replay/s0_physical_repeat_20260909/physical_artifacts/results/shared_baseline_sky130.json",
        "submission_edge_20260906/replay/s0_physical_repeat_20260909/s0_physical_repeat_sky130.json",
        "submission_edge_20260906/replay/s0_physical_repeat_20260909/s0_physical_repeat_audit.json",
    ]
    if all(_path(ref).is_file() for ref in s0_refs + repeat_refs) and _repeat_physical_evidence_pass():
        check = json.loads(_path(s0_refs[0]).read_text())
        physical = json.loads(_path(s0_refs[1]).read_text())
        holdout = json.loads(_path(s0_refs[2]).read_text())
        repeat_ok = _repeat_physical_evidence_pass()
        if _set_fft_s0_gates(s0, check, physical, holdout, repeat_ok):
            s0["evidence_status"] = "VERIFIED"
            s0["evaluation_scope"] = "observed_fft_ladder"
            s0["evidence_refs"] = s0_refs + repeat_refs

    s1 = by_id["acc_fft_s1"]
    s1_refs = [
        "ps_fft_campaign/artifacts/check_turn4.json",
        "ps_fft_campaign/artifacts/final_repeat.json",
    ]
    if all(_path(ref).is_file() for ref in s1_refs):
        s1["evidence_status"] = "PARTIAL"
        s1["evaluation_scope"] = "functional_and_physical_without_local_hidden_holdout"
        s1["evidence_refs"] = s1_refs

    for item in by_id.values():
        if item["id"].startswith("nat_ps_turn"):
            turn = item["id"].split("turn")[-1]
            refs = [
                f"ps_fft_campaign/artifacts/check_turn{turn}.json",
                f"ps_fft_campaign/artifacts/physical_turn{turn}.json",
            ]
            existing = [ref for ref in refs if _path(ref).is_file()]
            if existing:
                item["evidence_status"] = "PARTIAL"
                item["evaluation_scope"] = "archived_campaign_records_without_complete_nested_gate_reports"
                item["evidence_refs"] = existing

    for number in (2, 3):
        item = by_id[f"acc_mac_m{number}"]
        ref = f"mac-merge-{number}/artifacts/check_turn1.json"
        candidate_ref = f"mac-merge-{number}/best/shared_mac.v"
        manifest_ref = f"mac-merge-{number}/artifacts/manifest_turn1.json"
        if _set_mac_check_gates(item, _path(ref), _path(candidate_ref), _path(manifest_ref)):
            item["evidence_status"] = "VERIFIED"
            item["evaluation_scope"] = "full_mac_ladder"
            item["evidence_refs"] = [ref, candidate_ref, manifest_ref, f"submission_edge_20260906/mac_hidden_judge/m{number}_fixed/hidden_judge_report.json"]

    mutation_ref = "mac-mutants-1/mutation_report.json"
    if _path(mutation_ref).is_file():
        for item in by_id.values():
            if item["id"].startswith("mut_mac_"):
                item["evidence_status"] = "PARTIAL"
                item["evaluation_scope"] = "observed_mutation_gates_only"
                item["evidence_refs"] = [mutation_ref]

    for item in by_id.values():
        if item["evidence_status"] == "UNVERIFIED":
            item["evidence_refs"] = [item["primary_artifact"]]


def build_corpus() -> list[dict]:
    """Construct the 31-candidate corpus from primary records."""
    mac_evidence = load_mac_mutation_evidence()
    
    corpus = []
    
    # ------------------------------------------------------------------
    # Stratum 1: Natural candidate failures from live campaign (5)
    # ------------------------------------------------------------------
    # Turn 1
    t1 = load_ps_turn_evidence(1)
    corpus.append({
        "id": "nat_ps_turn1",
        "stratum": "natural_failure",
        "domain": "FFT",
        "description": "ps-fft-6 turn 1 candidate: physical timing closure failure",
        "expected_label": "FAIL",
        "primary_artifact": "ps_fft_campaign/artifacts/physical_turn1.json",
        "artifact_evidence": t1["physical"].get("note") if t1["physical"] else "timing_met=False drc=0",
        "gates": {
            "lint": "PASS", "oracle": "PASS", "holdout": "PASS",
            "gls": "PASS", "timing": "FAIL", "drc": "PASS",
            "provenance": "PASS"
        }
    })
    
    # Turn 2
    t2 = load_ps_turn_evidence(2)
    t2_note = t2["check"]["detail"]["functional"]["note"] if t2["check"] else "errors=3"
    corpus.append({
        "id": "nat_ps_turn2",
        "stratum": "natural_failure",
        "domain": "FFT",
        "description": "ps-fft-6 turn 2 candidate: functional verification failure (errors=3)",
        "expected_label": "FAIL",
        "primary_artifact": "ps_fft_campaign/artifacts/check_turn2.json",
        "artifact_evidence": t2_note.splitlines()[0],
        "gates": {
            "lint": "PASS", "oracle": "FAIL", "holdout": "BLOCKED",
            "gls": "BLOCKED", "timing": "BLOCKED", "drc": "BLOCKED",
            "provenance": "PASS"
        }
    })
    
    # Turn 5
    t5 = load_ps_turn_evidence(5)
    corpus.append({
        "id": "nat_ps_turn5",
        "stratum": "natural_failure",
        "domain": "FFT",
        "description": "ps-fft-6 turn 5 candidate: physical timing closure failure",
        "expected_label": "FAIL",
        "primary_artifact": "ps_fft_campaign/artifacts/physical_turn5.json",
        "artifact_evidence": t5["physical"].get("note") if t5["physical"] else "timing_met=False drc=0",
        "gates": {
            "lint": "PASS", "oracle": "PASS", "holdout": "PASS",
            "gls": "PASS", "timing": "FAIL", "drc": "PASS",
            "provenance": "PASS"
        }
    })
    
    # Turn 6
    t6 = load_ps_turn_evidence(6)
    t6_note = t6["physical"].get("note") if t6["physical"] else "result JSON missing; rc=1"
    corpus.append({
        "id": "nat_ps_turn6",
        "stratum": "natural_failure",
        "domain": "FFT",
        "description": "ps-fft-6 turn 6 candidate: result assembly failed closed on empty recovery reports",
        "expected_label": "FAIL",
        "primary_artifact": "ps_fft_campaign/artifacts/physical_turn6.json",
        "artifact_evidence": "assemble_results.py rejected empty reset-recovery reports (rc=1)",
        "gates": {
            "lint": "PASS", "oracle": "PASS", "holdout": "PASS",
            "gls": "PASS", "timing": "UNKNOWN", "drc": "UNKNOWN",
            "provenance": "FAIL"
        }
    })
    
    # Turn 7
    t7 = load_ps_turn_evidence(7)
    corpus.append({
        "id": "nat_ps_turn7",
        "stratum": "natural_failure",
        "domain": "FFT",
        "description": "ps-fft-6 turn 7 candidate: physical timing closure failure",
        "expected_label": "FAIL",
        "primary_artifact": "ps_fft_campaign/artifacts/physical_turn7.json",
        "artifact_evidence": t7["physical"].get("note") if t7["physical"] else "timing_met=False drc=0",
        "gates": {
            "lint": "PASS", "oracle": "PASS", "holdout": "PASS",
            "gls": "PASS", "timing": "FAIL", "drc": "PASS",
            "provenance": "PASS"
        }
    })
    
    # ------------------------------------------------------------------
    # Stratum 2: Accepted candidates and legal controls (9)
    # ------------------------------------------------------------------
    # FFT S0
    corpus.append({
        "id": "acc_fft_s0",
        "stratum": "accepted_legal",
        "domain": "FFT",
        "description": "Accepted shared FFT discovery candidate S0 (ce64c715...)",
        "expected_label": "PASS",
        "primary_artifact": "merge_clean_1/peweaver_shared_fft.mergerun1.v",
        "artifact_evidence": "Primary mapped-GLS/P&R result and independent repeat are hash-bound; timing met and router DRC 0",
        "gates": {
            "lint": "PASS", "oracle": "PASS", "holdout": "PASS",
            "gls": "PASS", "timing": "PASS", "drc": "PASS",
            "provenance": "PASS"
        }
    })
    
    # FFT S1
    corpus.append({
        "id": "acc_fft_s1",
        "stratum": "accepted_legal",
        "domain": "FFT",
        "description": "PowerSave promoted Pareto candidate S1 (f4d5ae2f...)",
        "expected_label": "PASS",
        "primary_artifact": "ps_fft_campaign/best/peweaver_shared_fft.v",
        "artifact_evidence": "Placed area 282,963 um^2; physical flow passed; DRC 0",
        "gates": {
            "lint": "PASS", "oracle": "PASS", "holdout": "PASS",
            "gls": "PASS", "timing": "PASS", "drc": "PASS",
            "provenance": "PASS"
        }
    })
    
    # FFT Repro 1-3
    for rep, turn_n in [(1, 10), (2, 2), (3, 13)]:
        corpus.append({
            "id": f"acc_fft_repro{rep}",
            "stratum": "accepted_legal",
            "domain": "FFT",
            "description": f"Preregistered clean-start FFT reproduction {rep} (turn {turn_n})",
            "expected_label": "PASS",
            "primary_artifact": f"merge-repro-{rep}/best/peweaver_shared_fft.v",
            "artifact_evidence": f"Accepted turn {turn_n}; 32-33% placed area reduction; timing closed",
            "gates": {
                "lint": "PASS", "oracle": "PASS", "holdout": "PASS",
                "gls": "PASS", "timing": "PASS", "drc": "PASS",
                "provenance": "PASS"
            }
        })
        
    # MAC M2 & M3
    for m_num, h_pfx in [(2, "3340103b"), (3, "7a9a2fb7")]:
        corpus.append({
            "id": f"acc_mac_m{m_num}",
            "stratum": "accepted_legal",
            "domain": "MAC",
            "description": f"Preregistered MAC clean start {m_num} ({h_pfx}...)",
            "expected_label": "PASS",
            "primary_artifact": f"mac-merge-{m_num}/best/shared_mac.v",
            "artifact_evidence": "Passed 6/6 gates; generic cell count 531 (-44.0%); BMC depth 12 verified",
            "gates": {
                "lint": "PASS", "oracle": "PASS", "corners": "PASS",
                "structure": "PASS", "area": "PASS", "formal": "PASS",
                "gls": "N/A", "timing": "N/A", "drc": "N/A", "provenance": "PASS"
            }
        })
        
    # FIR F1
    corpus.append({
        "id": "acc_fir_f1",
        "stratum": "accepted_legal",
        "domain": "FIR",
        "description": "Preregistered FIR clean start (009851fd...)",
        "expected_label": "PASS",
        "primary_artifact": "fir-merge-1/best/shared_fir.v",
        "artifact_evidence": "Passed 6/6 gates; 8 mults, 4484 generic cells (-11.6%); impulse exact",
        "gates": {
            "lint": "PASS", "oracle": "PASS", "corners": "PASS",
            "structure": "PASS", "area": "PASS", "hidden2": "PASS",
            "gls": "N/A", "timing": "N/A", "drc": "N/A", "provenance": "PASS"
        }
    })
    
    # Legal MAC commutation
    corpus.append({
        "id": "legal_mac_commutation",
        "stratum": "accepted_legal",
        "domain": "MAC",
        "description": "Legal operand commutation control: b*a instead of a*b",
        "expected_label": "PASS",
        "primary_artifact": "mac_mutants.py: unshared_recompute",
        "artifact_evidence": "mac-mutants-1: failed_gates=[], caught=False, as_expected=True",
        "gates": {
            "lint": "PASS", "oracle": "PASS", "corners": "PASS",
            "structure": "PASS", "area": "PASS", "formal": "PASS",
            "gls": "N/A", "timing": "N/A", "drc": "N/A", "provenance": "PASS"
        }
    })

    # ------------------------------------------------------------------
    # Stratum 3: Handwritten Architectural & Negative Controls (4)
    # ------------------------------------------------------------------
    corpus.append({
        "id": "ctrl_mac_two_mult",
        "stratum": "architectural_control",
        "domain": "MAC",
        "description": "MAC negative control: naive 2-multiplier multiplexer",
        "expected_label": "FAIL",
        "primary_artifact": "mac-selftest run logs",
        "artifact_evidence": "Rejected by structure gate: 2 multiplier cells > 1 allowed",
        "gates": {
            "lint": "PASS", "oracle": "PASS", "corners": "PASS",
            "structure": "FAIL", "area": "PASS", "formal": "PASS",
            "gls": "N/A", "timing": "N/A", "drc": "N/A", "provenance": "PASS"
        }
    })
    
    corpus.append({
        "id": "ctrl_mac_double_prod",
        "stratum": "architectural_control",
        "domain": "MAC",
        "description": "MAC negative control: double-product TDM cheater",
        "expected_label": "FAIL",
        "primary_artifact": "mac-selftest run logs",
        "artifact_evidence": "Rejected by functional oracle: arithmetic mismatch on interleaved cycles",
        "gates": {
            "lint": "PASS", "oracle": "FAIL", "corners": "FAIL",
            "structure": "PASS", "area": "PASS", "formal": "FAIL",
            "gls": "N/A", "timing": "N/A", "drc": "N/A", "provenance": "PASS"
        }
    })
    
    corpus.append({
        "id": "ctrl_fir_16_mult",
        "stratum": "architectural_control",
        "domain": "FIR",
        "description": "FIR negative control: naive 16-multiplier multiplexer",
        "expected_label": "FAIL",
        "primary_artifact": "fir-merge-selftest run logs",
        "artifact_evidence": "Rejected by generic area floor: 4.6% cell reduction < 10% required floor",
        "gates": {
            "lint": "PASS", "oracle": "PASS", "corners": "PASS",
            "structure": "PASS", "area": "FAIL", "hidden2": "PASS",
            "gls": "N/A", "timing": "N/A", "drc": "N/A", "provenance": "PASS"
        }
    })
    
    corpus.append({
        "id": "ctrl_fir_shared_delay",
        "stratum": "architectural_control",
        "domain": "FIR",
        "description": "FIR negative control: shared-delay-line state corruption cheater",
        "expected_label": "FAIL",
        "primary_artifact": "fir-merge-selftest run logs",
        "artifact_evidence": "Rejected by functional oracle: filter state contaminated across mode switches",
        "gates": {
            "lint": "PASS", "oracle": "FAIL", "corners": "FAIL",
            "structure": "PASS", "area": "PASS", "hidden2": "FAIL",
            "gls": "N/A", "timing": "N/A", "drc": "N/A", "provenance": "PASS"
        }
    })

    # ------------------------------------------------------------------
    # Stratum 4: Injected RTL Mutations (9)
    # ------------------------------------------------------------------
    # MAC mutants from mutation_report.json
    for mut_name in ["signedness", "acc_hold_mode1", "reset_ignored", "enable_ignored", "output_truncation"]:
        mut_d = mac_evidence.get(mut_name, {})
        corpus.append({
            "id": f"mut_mac_{mut_name}",
            "stratum": "rtl_mutation",
            "domain": "MAC",
            "description": f"MAC mutation: {mut_name.replace('_', ' ')}",
            "expected_label": "FAIL",
            "primary_artifact": f"mac-mutants-1/{mut_name}",
            "artifact_evidence": mut_d.get("notes", {}).get("functional", "Failed functional oracle, corners, and formal"),
            "gates": {
                "lint": "PASS", "oracle": "FAIL", "corners": "FAIL",
                "structure": "PASS", "area": "PASS", "formal": "FAIL",
                "gls": "N/A", "timing": "N/A", "drc": "N/A", "provenance": "PASS"
            }
        })
        
    # FFT mutants from hidden_holdout.py
    corpus.append({
        "id": "mut_fft_twiddle_re",
        "stratum": "rtl_mutation",
        "domain": "FFT",
        "description": "FFT mutant: LSB corrupted in stage-3 real twiddle coefficient",
        "expected_label": "FAIL",
        "primary_artifact": "hidden_holdout.py: twiddle_re5",
        "artifact_evidence": "Mismatches on non-zero twiddle frames; caught by hidden holdout",
        "gates": {
            "lint": "PASS", "oracle": "FAIL", "holdout": "FAIL",
            "gls": "FAIL", "timing": "UNKNOWN", "drc": "UNKNOWN",
            "provenance": "PASS"
        }
    })
    
    corpus.append({
        "id": "mut_fft_twiddle_im",
        "stratum": "rtl_mutation",
        "domain": "FFT",
        "description": "FFT mutant: LSB corrupted in stage-3 imaginary twiddle coefficient",
        "expected_label": "FAIL",
        "primary_artifact": "hidden_holdout.py: twiddle_im5",
        "artifact_evidence": "Mismatches on non-zero twiddle frames; caught by hidden holdout",
        "gates": {
            "lint": "PASS", "oracle": "FAIL", "holdout": "FAIL",
            "gls": "FAIL", "timing": "UNKNOWN", "drc": "UNKNOWN",
            "provenance": "PASS"
        }
    })
    
    corpus.append({
        "id": "mut_fft_scale_shift",
        "stratum": "rtl_mutation",
        "domain": "FFT",
        "description": "FFT mutant: internal arithmetic shifted >>> 14 instead of >>> 15",
        "expected_label": "FAIL",
        "primary_artifact": "hidden_holdout.py: scale_shift",
        "artifact_evidence": "Dynamic range gain error; caught by random oracle and holdout",
        "gates": {
            "lint": "PASS", "oracle": "FAIL", "holdout": "FAIL",
            "gls": "FAIL", "timing": "UNKNOWN", "drc": "UNKNOWN",
            "provenance": "PASS"
        }
    })
    
    corpus.append({
        "id": "mut_fft_counter_wrap",
        "stratum": "rtl_mutation",
        "domain": "FFT",
        "description": "FFT mutant: latency counter wraps early (starts at cycle 70 instead of 71)",
        "expected_label": "FAIL",
        "primary_artifact": "hidden_holdout.py: counter_wrap",
        "artifact_evidence": "First-valid latency assertion error (got 70, expected 71)",
        "gates": {
            "lint": "PASS", "oracle": "FAIL", "holdout": "FAIL",
            "gls": "FAIL", "timing": "UNKNOWN", "drc": "UNKNOWN",
            "provenance": "PASS"
        }
    })

    # ------------------------------------------------------------------
    # Stratum 5: Infrastructure & Provenance Faults (4)
    # ------------------------------------------------------------------
    corpus.append({
        "id": "flt_hash_mismatch",
        "stratum": "infra_provenance",
        "domain": "Cross-domain",
        "description": "Candidate file modified post-evaluation (hash mismatch against manifest)",
        "expected_label": "FAIL",
        "primary_artifact": "chia_merge.py resume verification guard",
        "artifact_evidence": "Resume refuses changed inputs/contract (SHA-256 mismatch)",
        "gates": {
            "lint": "PASS", "oracle": "PASS", "holdout": "PASS",
            "gls": "PASS", "timing": "PASS", "drc": "PASS",
            "provenance": "FAIL"
        }
    })
    
    corpus.append({
        "id": "flt_sta_1452",
        "stratum": "infra_provenance",
        "domain": "FFT",
        "description": "Clock period mismatch in OpenSTA (STA-1452 in backend log)",
        "expected_label": "FAIL",
        "primary_artifact": "run-physical.sh: STA-1452 fail-closed validator",
        "artifact_evidence": "Halt on STA-1452: clock period mismatch between VCD and SDC",
        "gates": {
            "lint": "PASS", "oracle": "PASS", "holdout": "PASS",
            "gls": "PASS", "timing": "FAIL", "drc": "PASS",
            "provenance": "FAIL"
        }
    })
    
    corpus.append({
        "id": "flt_zero_activity",
        "stratum": "infra_provenance",
        "domain": "FFT",
        "description": "Simulation produced 0 annotated pins / blank VCD file",
        "expected_label": "FAIL",
        "primary_artifact": "assemble_results.py: nonzero activity check",
        "artifact_evidence": "assemble_results.py die: VCD activity annotation must be nonzero",
        "gates": {
            "lint": "PASS", "oracle": "PASS", "holdout": "PASS",
            "gls": "PASS", "timing": "PASS", "drc": "PASS",
            "provenance": "FAIL"
        }
    })
    
    corpus.append({
        "id": "flt_stale_report",
        "stratum": "infra_provenance",
        "domain": "FFT",
        "description": "Stale physical report from prior run reused without fresh generation",
        "expected_label": "FAIL",
        "primary_artifact": "power_save_fft_driver.py: rmtree results guard",
        "artifact_evidence": "Driver rmtree(results/) before run; missing fresh artifact halts flow",
        "gates": {
            "lint": "PASS", "oracle": "PASS", "holdout": "PASS",
            "gls": "PASS", "timing": "UNKNOWN", "drc": "UNKNOWN",
            "provenance": "FAIL"
        }
    })
    
    return corpus


def evaluate_fail_closed(gates: dict, required_gates: list[str]) -> tuple[str, str | None]:
    """Evaluate candidate under a configuration using strict fail-closed semantics.
    
    Returns (verdict, earliest_catching_gate).
    Verdict:
      'ADVANCE'  - All required gates explicitly passed.
      'REJECT'   - At least one gate explicitly failed or was blocked.
      'BLOCKED'  - A required gate is unknown, invalid, or unavailable.
    """
    earliest_reject = None
    for g in required_gates:
        v = gates.get(g, "UNKNOWN")
        if v not in VALID_STATUSES:
            return "BLOCKED", g
        if v in ("FAIL", "BLOCKED"):
            earliest_reject = earliest_reject or g
            return "REJECT", earliest_reject
        if v in ("UNKNOWN", "N/A"):
            return "BLOCKED", g

    return "ADVANCE", None


def evaluate_nested_configs(item: dict) -> dict:
    """Evaluate candidate under three nested configurations."""
    if item.get("evidence_status") != "VERIFIED":
        return {
            "config1_verdict": "NOT_EVALUATED",
            "config1_catch": "evidence",
            "config2_verdict": "NOT_EVALUATED",
            "config2_catch": "evidence",
            "config3_verdict": "NOT_EVALUATED",
            "config3_catch": "evidence",
        }
    gates = item["gates"]
    domain = item["domain"]
    
    # Config 1: Functional checks only
    if domain == "FFT":
        c1_req = ["lint", "oracle", "holdout"]
    elif domain == "MAC":
        c1_req = ["lint", "oracle", "corners"]
    elif domain == "FIR":
        c1_req = ["lint", "oracle", "corners"]
    else:
        c1_req = ["lint", "oracle"]
    v1, catch1 = evaluate_fail_closed(gates, c1_req)
    
    # Config 2: Functional + Mapped Netlist GLS
    if domain == "FFT":
        c2_req = ["lint", "oracle", "holdout", "gls"]
    elif domain == "MAC":
        c2_req = ["lint", "oracle", "corners"]  # GLS not part of frozen MAC ladder
    elif domain == "FIR":
        c2_req = ["lint", "oracle", "corners"]  # GLS not part of frozen FIR ladder
    else:
        c2_req = ["lint", "oracle", "gls"]
    v2, catch2 = evaluate_fail_closed(gates, c2_req)
    
    # Config 3: Full gate ladder
    if domain == "FFT":
        c3_req = ["lint", "oracle", "holdout", "gls", "timing", "drc", "provenance"]
    elif domain == "MAC":
        c3_req = ["lint", "oracle", "corners", "structure", "area", "formal", "provenance"]
    elif domain == "FIR":
        c3_req = ["lint", "oracle", "corners", "structure", "area", "hidden2", "provenance"]
    else:
        c3_req = ["lint", "oracle", "gls", "timing", "drc", "provenance"]
    v3, catch3 = evaluate_fail_closed(gates, c3_req)
    
    return {
        "config1_verdict": v1,
        "config1_catch": catch1,
        "config2_verdict": v2,
        "config2_catch": catch2,
        "config3_verdict": v3,
        "config3_catch": catch3,
    }


def main():
    REPLAY_DIR.mkdir(parents=True, exist_ok=True)
    corpus = build_corpus()
    attach_evidence(corpus)
    
    matrix = []
    strata_stats = {}
    
    for item in corpus:
        res = evaluate_nested_configs(item)
        entry = {
            "id": item["id"],
            "stratum": item["stratum"],
            "domain": item["domain"],
            "description": item["description"],
            "expected_label": item["expected_label"],
            "primary_artifact": item["primary_artifact"],
            "artifact_evidence": item["artifact_evidence"],
            "evidence_status": item["evidence_status"],
            "evaluation_scope": item["evaluation_scope"],
            "evidence_refs": item["evidence_refs"],
            "gates": item["gates"],
            **res
        }
        matrix.append(entry)
        
        s = item["stratum"]
        if s not in strata_stats:
            strata_stats[s] = {
                "total": 0,
                "defects": 0,
                "legal": 0,
                "evaluated_defects": 0,
                "evaluated_legal": 0,
                "unevaluated_defects": 0,
                "unevaluated_legal": 0,
                "c1_caught": 0,
                "c2_caught": 0,
                "c3_caught": 0,
                "c1_false_reject": 0,
                "c2_false_reject": 0,
                "c3_false_reject": 0,
            }
        st = strata_stats[s]
        st["total"] += 1
        
        is_defect = (item["expected_label"] == "FAIL")
        evaluated = res["config1_verdict"] != "NOT_EVALUATED"
        if is_defect:
            st["defects"] += 1
            if evaluated:
                st["evaluated_defects"] += 1
                if res["config1_verdict"] != "ADVANCE": st["c1_caught"] += 1
                if res["config2_verdict"] != "ADVANCE": st["c2_caught"] += 1
                if res["config3_verdict"] != "ADVANCE": st["c3_caught"] += 1
            else:
                st["unevaluated_defects"] += 1
        else:
            st["legal"] += 1
            if evaluated:
                st["evaluated_legal"] += 1
                if res["config1_verdict"] != "ADVANCE": st["c1_false_reject"] += 1
                if res["config2_verdict"] != "ADVANCE": st["c2_false_reject"] += 1
                if res["config3_verdict"] != "ADVANCE": st["c3_false_reject"] += 1
            else:
                st["unevaluated_legal"] += 1

    # Save corpus manifest
    manifest = {
        "corpus_version": "2026-09-07_v2",
        "total_candidates": len(corpus),
        "strata_counts": {k: v["total"] for k, v in strata_stats.items()},
        "candidates": corpus
    }
    with open(REPLAY_DIR / "corpus_manifest.json", "w") as fp:
        json.dump(manifest, fp, indent=2)
        
    # Save matrix JSON
    with open(REPLAY_DIR / "candidate_by_gate_matrix.json", "w") as fp:
        json.dump(matrix, fp, indent=2)
        
    # Summary JSON
    tot_defects = sum(v["defects"] for v in strata_stats.values())
    tot_legal = sum(v["legal"] for v in strata_stats.values())
    tot_c1_caught = sum(v["c1_caught"] for v in strata_stats.values())
    tot_c2_caught = sum(v["c2_caught"] for v in strata_stats.values())
    tot_c3_caught = sum(v["c3_caught"] for v in strata_stats.values())
    evaluated_defects = sum(v["evaluated_defects"] for v in strata_stats.values())
    evaluated_legal = sum(v["evaluated_legal"] for v in strata_stats.values())
    unevaluated_defects = sum(v["unevaluated_defects"] for v in strata_stats.values())
    unevaluated_legal = sum(v["unevaluated_legal"] for v in strata_stats.values())

    def detection(caught: int) -> float | None:
        return round(100.0 * caught / evaluated_defects, 2) if evaluated_defects else None
    
    summary = {
        "corpus_total": len(corpus),
        "strata_breakdown": strata_stats,
        "overall": {
            "total_defects": tot_defects,
            "total_legal": tot_legal,
            "evaluated_defects": evaluated_defects,
            "evaluated_legal": evaluated_legal,
            "unevaluated_defects": unevaluated_defects,
            "unevaluated_legal": unevaluated_legal,
            "config1_detection_pct": detection(tot_c1_caught),
            "config2_detection_pct": detection(tot_c2_caught),
            "config3_detection_pct": detection(tot_c3_caught),
            "false_rejections_config3": sum(v["c3_false_reject"] for v in strata_stats.values()),
        }
    }
    with open(REPLAY_DIR / "detection_summary.json", "w") as fp:
        json.dump(summary, fp, indent=2)
        
    # Markdown Table
    md = [
        "# Evaluator Replay Matrix (Evidence-Scoped)",
        "",
        "Records 31 candidates across 5 explicit strata. Only rows with complete local gate evidence are evaluated; partial or missing evidence is reported as NOT_EVALUATED and excluded from detection denominators:",
        "- **Config 1:** Functional checks only (lint, random oracle, holdouts)",
        "- **Config 2:** Functional + Mapped GLS",
        "- **Config 3:** Full domain-specific gate ladder (FFT physical timing/DRC; MAC formal/structure; FIR structure/generic-cell area; provenance where applicable)",
        "",
        "| Candidate ID | Stratum | Domain | Expected | Evidence | Config 1 | Config 2 | Config 3 | Earliest Catch | Primary Artifact Evidence |",
        "|---|---|---|---|---|---|---|---|---|---|"
    ]
    for m in matrix:
        v1 = "ADVANCE" if m["config1_verdict"] == "ADVANCE" else f"**{m['config1_verdict']}** ({m['config1_catch']})"
        v2 = "ADVANCE" if m["config2_verdict"] == "ADVANCE" else f"**{m['config2_verdict']}** ({m['config2_catch']})"
        v3 = "ADVANCE" if m["config3_verdict"] == "ADVANCE" else f"**{m['config3_verdict']}** ({m['config3_catch']})"
        ec = m["config3_catch"] or "None (Advance)"
        md.append(f"| `{m['id']}` | {m['stratum']} | {m['domain']} | {m['expected_label']} | {m['evidence_status']} | {v1} | {v2} | {v3} | `{ec}` | {m['artifact_evidence'][:60]} |")
        
    md.extend([
        "",
        "## Detection Rate by Stratum",
        "",
        "| Stratum | Total | Defects | Evaluated Defects | Unevaluated Defects | Config 1 | Config 2 | Config 3 | Legal | False Rejections |",
        "|---|---|---|---|---|---|---|---|---|---|"
    ])
    for s_name, s_d in strata_stats.items():
        den = s_d["evaluated_defects"]
        c1 = f"{s_d['c1_caught']}/{den} ({100.0*s_d['c1_caught']/den:.1f}%)" if den else "N/A"
        c2 = f"{s_d['c2_caught']}/{den} ({100.0*s_d['c2_caught']/den:.1f}%)" if den else "N/A"
        c3 = f"{s_d['c3_caught']}/{den} ({100.0*s_d['c3_caught']/den:.1f}%)" if den else "N/A"
        fr = f"{s_d['c3_false_reject']}/{s_d['evaluated_legal']}" if s_d['evaluated_legal'] else "N/A"
        md.append(f"| **{s_name}** | {s_d['total']} | {s_d['defects']} | {s_d['evaluated_defects']} | {s_d['unevaluated_defects']} | {c1} | {c2} | {c3} | {s_d['evaluated_legal']} | {fr} |")
        
    ov = summary["overall"]
    c1_text = f"{ov['config1_detection_pct']}%" if ov["config1_detection_pct"] is not None else "N/A"
    c2_text = f"{ov['config2_detection_pct']}%" if ov["config2_detection_pct"] is not None else "N/A"
    c3_text = f"{ov['config3_detection_pct']}%" if ov["config3_detection_pct"] is not None else "N/A"
    md.extend([
        f"| **Overall Total** | **{len(corpus)}** | **{tot_defects}** | **{evaluated_defects}** | **{unevaluated_defects}** | **{c1_text}** | **{c2_text}** | **{c3_text}** | **{evaluated_legal}** | **{ov['false_rejections_config3']}/{evaluated_legal if evaluated_legal else 0}** |",
        "",
        "### Key Findings:",
        f"1. **Evidence scope:** {evaluated_defects} defect records and {evaluated_legal} legal records have complete local gate evidence; {unevaluated_defects} defect records and {unevaluated_legal} legal records remain outside the detection denominators.",
        "2. **Fail-closed behavior:** Any missing, invalid, UNKNOWN, or N/A status in a required gate blocks evaluation rather than advancing the candidate.",
        "3. **No synthetic completeness claim:** Source-code guard descriptions and partial mutation reports remain visible in the ledger but do not count as full nested evaluator executions.",
        ""
    ])
    
    with open(REPLAY_DIR / "candidate_by_gate_matrix.md", "w") as fp:
        fp.write("\n".join(md))
        
    print("Audited Replay Corpus generated successfully:")
    print(f"  Total Candidates: {len(corpus)}")
    print(f"  Defects: {tot_defects} | Legal Controls: {tot_legal}")
    print(f"  Evidence-complete defects: {evaluated_defects}/{tot_defects}; legal: {evaluated_legal}/{tot_legal}")
    print(f"  Detection among evidence-complete defects: Config 1 = {c1_text} | Config 2 = {c2_text} | Config 3 = {c3_text}")
    print(f"  False Rejections among evidence-complete legal rows: {ov['false_rejections_config3']}/{evaluated_legal}")

if __name__ == "__main__":
    main()
