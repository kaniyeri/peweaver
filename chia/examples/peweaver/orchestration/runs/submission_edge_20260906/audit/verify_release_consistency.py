#!/usr/bin/env python3
"""Fail-closed semantic verifier for the submission-edge release package."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


VALID_EVIDENCE = {"VERIFIED", "PARTIAL", "UNVERIFIED"}
VALID_VERDICTS = {"ADVANCE", "REJECT", "BLOCKED", "NOT_EVALUATED"}
VALID_GATE_STATUSES = {"PASS", "FAIL", "BLOCKED", "UNKNOWN", "N/A"}


def load(path: Path) -> Any:
    if not path.is_file():
        raise ValueError(f"missing required file: {path}")
    return json.loads(path.read_text())


def finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be finite numeric")
    return float(value)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load verifier source: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def csv_row_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def expected_workload_records(workload_module) -> list[dict[str, Any]]:
    """Independently calculate the published workload projection."""
    records = []
    alphas = [0.05, 0.10, 0.25, 0.50, 0.75, 1.00]
    betas = [0.0, 0.5, 1.0]
    for idle_model in workload_module.IDLE_MODELS:
        for beta in betas:
            label = "Mode 64 (100%)" if beta == 1.0 else ("Mode 128 (100%)" if beta == 0.0 else "Mixed 50/50")
            for alpha in alphas:
                e_s0 = beta * workload_module.S0_E64_NJ + (1.0 - beta) * workload_module.S0_E128_NJ
                e_a = beta * workload_module.A_E64_NJ + (1.0 - beta) * workload_module.A_E128_NJ
                t_active = beta * workload_module.T_TRANSFORM_64_S + (1.0 - beta) * workload_module.T_TRANSFORM_128_S
                t_total = t_active / alpha
                t_idle = t_total - t_active
                e_s0_total = e_s0 + workload_module.IDLE_MODELS[idle_model]["s0"] * t_idle * 1e9
                e_a_total = e_a + workload_module.IDLE_MODELS[idle_model]["a"] * t_idle * 1e9
                p_s0 = e_s0_total * 1e-9 / t_total * 1e3
                p_a = e_a_total * 1e-9 / t_total * 1e3
                savings = round(100.0 * (1.0 - e_s0_total / e_a_total), 2)
                power_savings = round(100.0 * (1.0 - p_s0 / p_a), 2)
                records.append({
                    "active_duty_cycle": alpha,
                    "mode64_occupancy": beta,
                    "idle_model": idle_model,
                    "s0_energy_active_nj": round(e_s0, 3),
                    "a_energy_active_nj": round(e_a, 3),
                    "s0_energy_total_nj": round(e_s0_total, 3),
                    "a_energy_total_nj": round(e_a_total, 3),
                    "s0_avg_power_mw": round(p_s0, 3),
                    "a_avg_power_mw": round(p_a, 3),
                    "energy_savings_pct": savings,
                    "power_savings_pct": power_savings,
                    "winner": "S0 (Shared)" if savings > 0 else "A (Dual)",
                    "schedule_name": label,
                })
    return records


def nice_axis(values: list[float], target_ticks: int = 7) -> tuple[float, list[float]]:
    maximum = max(values, default=1.0)
    raw_step = maximum / target_ticks
    magnitude = 10 ** math.floor(math.log10(raw_step))
    normalized = raw_step / magnitude
    step = (1.0 if normalized <= 1.0 else 2.0 if normalized <= 2.0 else 5.0 if normalized <= 5.0 else 10.0) * magnitude
    axis_max = math.ceil(maximum / step) * step
    return axis_max, [round(step * index, 10) for index in range(int(round(axis_max / step)) + 1)]


def expected_replay_rows(replay_module) -> list[dict[str, Any]]:
    corpus = replay_module.build_corpus()
    replay_module.attach_evidence(corpus)
    rows = []
    for item in corpus:
        rows.append({
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
            **replay_module.evaluate_nested_configs(item),
        })
    return rows


def replay_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    strata: dict[str, dict[str, int]] = {}
    for row in rows:
        stratum = row["stratum"]
        stats = strata.setdefault(stratum, {
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
        })
        stats["total"] += 1
        is_defect = row["expected_label"] == "FAIL"
        evaluated = row["config1_verdict"] != "NOT_EVALUATED"
        if is_defect:
            stats["defects"] += 1
            if evaluated:
                stats["evaluated_defects"] += 1
                for index, key in enumerate(("c1_caught", "c2_caught", "c3_caught"), 1):
                    if row[f"config{index}_verdict"] != "ADVANCE":
                        stats[key] += 1
            else:
                stats["unevaluated_defects"] += 1
        else:
            stats["legal"] += 1
            if evaluated:
                stats["evaluated_legal"] += 1
                for index, key in enumerate(("c1_false_reject", "c2_false_reject", "c3_false_reject"), 1):
                    if row[f"config{index}_verdict"] != "ADVANCE":
                        stats[key] += 1
            else:
                stats["unevaluated_legal"] += 1

    total_defects = sum(value["defects"] for value in strata.values())
    total_legal = sum(value["legal"] for value in strata.values())
    evaluated_defects = sum(value["evaluated_defects"] for value in strata.values())

    def detection(key: str) -> float | None:
        if evaluated_defects == 0:
            return None
        return round(100.0 * sum(value[key] for value in strata.values()) / evaluated_defects, 2)

    return {
        "corpus_total": len(rows),
        "strata_breakdown": strata,
        "overall": {
            "total_defects": total_defects,
            "total_legal": total_legal,
            "evaluated_defects": evaluated_defects,
            "evaluated_legal": sum(value["evaluated_legal"] for value in strata.values()),
            "unevaluated_defects": sum(value["unevaluated_defects"] for value in strata.values()),
            "unevaluated_legal": sum(value["unevaluated_legal"] for value in strata.values()),
            "config1_detection_pct": detection("c1_caught"),
            "config2_detection_pct": detection("c2_caught"),
            "config3_detection_pct": detection("c3_caught"),
            "false_rejections_config3": sum(value["c3_false_reject"] for value in strata.values()),
        },
    }


def verify(phase: Path, index_kind: str = "full") -> dict[str, Any]:
    if index_kind not in {"full", "slim"}:
        raise ValueError(f"unsupported artifact index: {index_kind}")
    errors: list[str] = []

    def check(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    try:
        manifest = load(phase / "manifest/phase_manifest.json")
        canonical = load(phase / "manifest/canonical_comparison.json")
        canonical_csv = phase / "manifest/canonical_comparison.csv"
        corpus_manifest = load(phase / "replay/corpus_manifest.json")
        matrix = load(phase / "replay/candidate_by_gate_matrix.json")
        replay_summary_actual = load(phase / "replay/detection_summary.json")
        workload = load(phase / "workloads/workload_metrics.json")
        index_file = "artifact_index_slim.json" if index_kind == "slim" else "artifact_index.json"
        artifact_index = load(phase / "audit" / index_file)
        workload_csv = phase / "workloads/workload_metrics.csv"
        measured_control_csv = phase / "workloads/measured_control_comparison.csv"
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return {"ok": False, "errors": [str(exc)], "phase": str(phase)}

    object_values = {
        "phase manifest": manifest,
        "canonical comparison": canonical,
        "corpus manifest": corpus_manifest,
        "replay summary": replay_summary_actual,
        "artifact index": artifact_index,
    }
    for label, value in object_values.items():
        check(isinstance(value, dict), f"{label} must be an object")
    check(isinstance(matrix, list), "replay matrix must be a list")
    check(isinstance(workload, list), "workload JSON must be a list")
    if errors:
        return {"ok": False, "errors": errors, "phase": str(phase)}

    canonical_expected = None
    try:
        canonical_module = load_module("release_canonical_builder", phase / "manifest/build_canonical_comparison.py")
        canonical_expected = canonical_module.build_output()
        check(canonical == canonical_expected, "canonical JSON does not match independently rebuilt source output")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(f"canonical source rebuild failed: {exc}")

    actual_rows = canonical.get("rows", [])
    check(isinstance(actual_rows, list), "canonical rows must be a list")
    if not isinstance(actual_rows, list):
        actual_rows = []
    actual_designs = []
    for row in actual_rows:
        if not isinstance(row, dict) or not isinstance(row.get("design"), str):
            check(False, "canonical rows must contain string design IDs")
            continue
        actual_designs.append(row["design"])
    check(len(actual_rows) == len(set(actual_designs)), "canonical rows contain duplicate design IDs")
    check(set(actual_designs) == {"S0", "S1", "A", "B"}, "canonical comparison must contain exactly S0/S1/A/B")
    check(manifest.get("outcome_fields_present") is True, "phase manifest must mark outcome fields")
    check(
        manifest.get("manifest_role") == "post-outcome scope and identity snapshot; not a pre-outcome preregistration",
        "phase manifest must disclose that it is post-outcome",
    )
    check(
        manifest.get("authoritative_plan") == "ASTRA_RELEASE_REPAIR_PLAN.md",
        "phase manifest must point to the active release repair plan",
    )
    check(manifest.get("schema") == "peweaver-submission-edge-phase-manifest-1", "phase manifest schema is invalid")

    if canonical_csv.is_file():
        with canonical_csv.open(newline="") as stream:
            csv_rows = list(csv.DictReader(stream))
        expected_rows = canonical_expected.get("rows", []) if isinstance(canonical_expected, dict) else []
        expected_fields = [
            "design", "role", "source_hash", "evidence", "area_um2", "p64_mw", "p128_mw",
            "e64_nj", "e128_nj", "timing_met", "router_drc_lines", "independent_streamed_drc",
            "independent_lvs", "physical_detail_scope",
        ]
        check(list(csv_rows[0]) == expected_fields if csv_rows else not expected_rows, "canonical CSV columns are not canonical")
        check(len(csv_rows) == len(expected_rows), "canonical CSV row count disagrees with canonical JSON")
        fields = list(csv_rows[0]) if csv_rows else []
        for expected, actual in zip(expected_rows, csv_rows):
            for field in fields:
                check(actual.get(field) == csv_row_value(expected.get(field)), f"canonical CSV mismatch at {expected.get('design')}.{field}")
    else:
        errors.append("missing canonical CSV")

    try:
        replay_module = load_module("release_replay_builder", phase / "replay/build_replay_corpus.py")
        expected_rows = expected_replay_rows(replay_module)
        expected_summary = replay_summary(expected_rows)
        check(matrix == expected_rows, "replay matrix does not match independently rebuilt evidence rows")
        check(replay_summary_actual == expected_summary, "replay summary does not match recomputed matrix statistics")
        source_corpus = replay_module.build_corpus()
        replay_module.attach_evidence(source_corpus)
        check(corpus_manifest.get("candidates") == source_corpus, "corpus manifest does not match independently rebuilt source corpus")
        check(isinstance(corpus_manifest.get("total_candidates"), int) and not isinstance(corpus_manifest.get("total_candidates"), bool), "corpus manifest total must be an integer")
        check(corpus_manifest.get("total_candidates") == len(source_corpus), "corpus manifest total is stale")
        expected_strata = {}
        for item in source_corpus:
            expected_strata[item["stratum"]] = expected_strata.get(item["stratum"], 0) + 1
        check(isinstance(corpus_manifest.get("strata_counts"), dict), "corpus manifest strata counts must be an object")
        check(corpus_manifest.get("strata_counts") == expected_strata, "corpus manifest stratum counts are stale")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(f"replay source rebuild failed: {exc}")

    ids = []
    for row in matrix:
        if isinstance(row, dict) and isinstance(row.get("id"), str):
            ids.append(row["id"])
        elif isinstance(row, dict):
            check(False, "replay matrix IDs must be strings")
    check(len(ids) == len(set(ids)), "replay matrix contains duplicate candidate IDs")
    valid_domains = {"FFT", "MAC", "FIR", "Cross-domain"}
    for row in matrix:
        if not isinstance(row, dict):
            check(False, "replay matrix rows must be objects")
            continue
        check(isinstance(row.get("domain"), str) and row.get("domain") in valid_domains, f"{row.get('id')}: invalid domain")
        check(isinstance(row.get("expected_label"), str) and row.get("expected_label") in {"PASS", "FAIL"}, f"{row.get('id')}: invalid expected label")
        check(row.get("evidence_status") in VALID_EVIDENCE, f"{row.get('id')}: invalid evidence status")
        gates = row.get("gates")
        check(isinstance(gates, dict), f"{row.get('id')}: gates must be an object")
        if isinstance(gates, dict):
            for gate, status in gates.items():
                check(status in VALID_GATE_STATUSES, f"{row.get('id')}.{gate}: invalid gate status")
        for index in (1, 2, 3):
            verdict = row.get(f"config{index}_verdict")
            check(verdict in VALID_VERDICTS, f"{row.get('id')}.config{index}: invalid verdict")
        if row.get("evidence_status") != "VERIFIED":
            check(all(row.get(f"config{i}_verdict") == "NOT_EVALUATED" for i in (1, 2, 3)), f"{row.get('id')}: incomplete evidence received nested verdict")
        else:
            check(all(row.get(f"config{i}_verdict") != "NOT_EVALUATED" for i in (1, 2, 3)), f"{row.get('id')}: verified evidence did not receive nested verdicts")
            refs = row.get("evidence_refs")
            check(isinstance(refs, list) and bool(refs), f"{row.get('id')}: verified row has no evidence references")
            if isinstance(refs, list):
                for ref in refs:
                    if not isinstance(ref, str):
                        check(False, f"{row.get('id')}: evidence reference is not a string")
                        continue
                    evidence_path = (phase.parent / ref).resolve()
                    try:
                        evidence_path.relative_to(phase.parent.resolve())
                    except ValueError:
                        check(False, f"{row.get('id')}: evidence reference escapes runs root: {ref}")
                        continue
                    check(evidence_path.is_file(), f"{row.get('id')}: missing evidence reference: {ref}")
                    try:
                        inventory_path = evidence_path.resolve().relative_to(phase.parents[5].resolve()).as_posix()
                    except ValueError:
                        check(False, f"{row.get('id')}: evidence reference escapes workspace: {ref}")
                        continue
                    inventory_records = [
                        record for records in artifact_index.values() if isinstance(records, dict)
                        for record in records.values() if isinstance(record, dict) and record.get("path") == inventory_path
                    ]
                    check(bool(inventory_records), f"{row.get('id')}: verified evidence is absent from artifact index: {ref}")
                    if inventory_records:
                        record = inventory_records[0]
                        actual_bytes = evidence_path.stat().st_size
                        actual_hash = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
                        check(record.get("size_bytes") == actual_bytes, f"{row.get('id')}: indexed evidence size mismatch: {ref}")
                        check(record.get("sha256") == actual_hash, f"{row.get('id')}: indexed evidence hash mismatch: {ref}")

    expected_workload: list[dict[str, Any]] = []
    try:
        workload_module = load_module("release_workload_model", phase / "workloads/workload_matrix.py")
        expected_workload = expected_workload_records(workload_module)
        check(workload == expected_workload, "workload JSON does not match independently rebuilt model output")
        canonical_rows = {row.get("design"): row for row in canonical.get("rows", [])}
        for design, energy_key, power_key in (
            ("S0", "S0_E64_NJ", "p64_mw"),
            ("S0", "S0_E128_NJ", "p128_mw"),
            ("A", "A_E64_NJ", "p64_mw"),
            ("A", "A_E128_NJ", "p128_mw"),
        ):
            value = getattr(workload_module, energy_key)
            expected = canonical_rows[design]["e64_nj" if "64" in energy_key else "e128_nj"]
            check(abs(value - expected) < 1e-9, f"workload constant {energy_key} disagrees with canonical source")
        tuples = [(row.get("idle_model"), row.get("active_duty_cycle"), row.get("mode64_occupancy")) for row in workload]
        expected_tuples = [(row["idle_model"], row["active_duty_cycle"], row["mode64_occupancy"]) for row in expected_workload]
        check(len(tuples) == len(set(tuples)), "workload matrix contains duplicate operating points")
        check(set(tuples) == set(expected_tuples), "workload matrix is missing or adding operating points")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(f"workload source rebuild failed: {exc}")

    if workload_csv.is_file() and isinstance(workload, list):
        with workload_csv.open(newline="") as stream:
            csv_rows = list(csv.DictReader(stream))
        expected_fields = [
            "schedule_name", "active_duty_cycle", "mode64_occupancy", "s0_energy_total_nj",
            "a_energy_total_nj", "s0_avg_power_mw", "a_avg_power_mw", "energy_savings_pct",
            "winner", "idle_model",
        ]
        check(list(csv_rows[0]) == expected_fields if csv_rows else not workload, "workload CSV columns are not canonical")
        check(len(csv_rows) == len(workload), "workload CSV row count disagrees with JSON")
        for expected, actual in zip(workload, csv_rows):
            for field in actual:
                check(actual.get(field) == csv_row_value(expected.get(field)), f"workload CSV mismatch at {expected.get('schedule_name')}.{field}")
    else:
        errors.append("missing workload CSV")

    if measured_control_csv.is_file() and "workload_module" in locals():
        with measured_control_csv.open(newline="") as stream:
            control_rows = list(csv.DictReader(stream))
        control_fields = [
            "design", "role", "mode", "energy_per_fft_nj", "streaming_power_mw",
            "placed_cell_area_um2", "timing_met", "drc_lines",
        ]
        check(list(control_rows[0]) == control_fields if control_rows else False, "measured control CSV columns are not canonical")
        expected_controls = []
        for design, role, area, rows in (
            ("S0", "shared", workload_module._s0_row["area_um2"], ((64, workload_module.S0_E64_NJ, workload_module.S0_P64_MW), (128, workload_module.S0_E128_NJ, workload_module.S0_P128_MW))),
            ("A", "ungated dual control", workload_module._a_row["area_um2"], ((64, workload_module.A_E64_NJ, workload_module.A_P64_MW), (128, workload_module.A_E128_NJ, workload_module.A_P128_MW))),
            ("B", "power-managed dual control", workload_module.B_AREA_UM2, ((64, workload_module.B_E64_NJ, workload_module.B_P64_MW), (128, workload_module.B_E128_NJ, workload_module.B_P128_MW))),
        ):
            for mode, energy_value, power_value in rows:
                expected_controls.append({
                    "design": design,
                    "role": role,
                    "mode": mode,
                    "energy_per_fft_nj": round(energy_value, 7),
                    "streaming_power_mw": round(power_value, 7),
                    "placed_cell_area_um2": area,
                    "timing_met": True,
                    "drc_lines": 0,
                })
        check(len(control_rows) == len(expected_controls), "measured control CSV row count is stale")
        for expected, actual in zip(expected_controls, control_rows):
            for field in control_fields:
                check(actual.get(field) == csv_row_value(expected.get(field)), f"measured control CSV mismatch at {expected.get('design')}.{field}")
    else:
        errors.append("missing measured control CSV")

    for relative in (
        "README.md",
        "PAPER_NARRATIVE_OUTLINE.md",
        "manifest/phase_manifest.json",
        "manifest/canonical_comparison.json",
        "manifest/canonical_comparison.csv",
        "replay/corpus_manifest.json",
        "replay/candidate_by_gate_matrix.json",
        "replay/candidate_by_gate_matrix.md",
        "replay/detection_summary.json",
        "replay/contract_to_evidence_index.json",
        "replay/final_s0_hidden_holdout/hidden_holdout_report.json",
        "replay/final_s0_hidden_holdout/run.log",
        "workloads/workload_metrics.json",
        "workloads/workload_metrics.csv",
        "workloads/measured_control_comparison.csv",
        "workloads/breakeven_analysis.md",
        "figures/fig1_workload_breakeven.svg",
        "figures/fig2_evaluator_replay.svg",
        "figures/fig3_thermal_envelope.svg",
        "figures/fig4_paired_thermal_comparison.svg",
        "figures/fig5_layout_footprint_comparison.svg",
        "audit/verify_artifact_index.py",
        "audit/verify_release_consistency.py",
        "audit/test_release_guards.py",
        "audit/RELEASE_REPAIR_REPORT.md",
        "ASTRA_RELEASE_REPAIR_PLAN.md",
        "replay/s0_physical_repeat_20260909/physical_artifacts/ARCHIVE_NOTE.md",
        "replay/s0_physical_repeat_20260909/s0_physical_repeat_audit.json",
        "replay/s0_physical_repeat_20260909/physical_artifacts/results/shared_baseline_sky130.json",
        "replay/s0_physical_repeat_20260909/physical_artifacts/results/def/shared_baseline.def",
        "replay/s0_physical_repeat_20260909/physical_artifacts/results/spef/shared_baseline.spef",
        "mac_hidden_judge/m2_fixed/hidden_judge_report.json",
        "mac_hidden_judge/m3_fixed/hidden_judge_report.json",
    ):
        check((phase / relative).is_file(), f"missing release output: {relative}")

    for svg in sorted((phase / "figures").glob("*.svg")):
        try:
            ET.parse(svg)
            text = svg.read_text()
            check(text.count("</svg>") == 1, f"{svg.name}: expected one closing SVG tag")
            check(not re.search(r"(?i)\b(?:nan|inf(?:inity)?)\b", text), f"{svg.name}: non-finite SVG coordinate or label")
            if svg.name == "fig1_workload_breakeven.svg":
                circles = [float(value) for value in re.findall(r'<circle[^>]+cy="([0-9.]+)"', text)]
                check(circles and all(70.0 <= value <= 330.0 for value in circles), "fig1 contains a clipped data or legend point")
                m64 = [row for row in expected_workload if row.get("mode64_occupancy") == 1.0 and row.get("idle_model") == "nominal"]
                axis_max, _ = nice_axis([value for row in m64 for value in (row["s0_energy_total_nj"], row["a_energy_total_nj"])])
                check(f">{axis_max:g}</text>" in text, "fig1 axis scale is not derived from its data")
                def plotted_points(color: str) -> list[tuple[float, float]]:
                    points = []
                    for tag in re.findall(r"<circle[^>]+>", text):
                        if f'fill="{color}"' not in tag:
                            continue
                        match = re.search(r'cx="([0-9.]+)"[^>]+cy="([0-9.]+)"', tag)
                        if match:
                            points.append((float(match.group(1)), float(match.group(2))))
                    return points
                red_points = plotted_points("#ef4444")
                green_points = plotted_points("#059669")
                for row in m64:
                    x = 80.0 + row["active_duty_cycle"] * 520.0
                    expected_s0_y = 330.0 - row["s0_energy_total_nj"] / axis_max * 260.0
                    expected_a_y = 330.0 - row["a_energy_total_nj"] / axis_max * 260.0
                    check(any(abs(px - x) < 0.2 and abs(py - expected_s0_y) < 0.2 for px, py in green_points), "fig1 S0 point disagrees with workload data")
                    check(any(abs(px - x) < 0.2 and abs(py - expected_a_y) < 0.2 for px, py in red_points), "fig1 A point disagrees with workload data")
                savings = [row["energy_savings_pct"] for row in m64]
                check(f"{min(savings):.2f}%" in text and f"{max(savings):.2f}%" in text, "fig1 savings callout is stale")
            if svg.name == "fig2_evaluator_replay.svg":
                overall = replay_summary_actual.get("overall", {})
                total = overall.get("total_defects")
                evaluated = overall.get("evaluated_defects")
                check(f"Overall ({total})" in text, "fig2 overall denominator is not derived from replay summary")
                check(f"{evaluated}/{total} defect rows evidence-complete" in text, "fig2 evidence footer is stale")
        except (OSError, ET.ParseError) as exc:
            errors.append(f"invalid SVG {svg.name}: {exc}")

    return {"ok": not errors, "errors": errors, "phase": str(phase)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--index", choices=("full", "slim"), default="full",
                        help="use the original full index or the redacted public-pack index")
    args = parser.parse_args(argv)
    result = verify(args.phase.resolve(), index_kind=args.index)
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
