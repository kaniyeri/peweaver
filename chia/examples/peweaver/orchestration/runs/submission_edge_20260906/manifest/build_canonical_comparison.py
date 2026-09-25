#!/usr/bin/env python3
"""Build the canonical S0/S1/A/B comparison from archived primary JSONs."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path


PHASE = Path(__file__).resolve().parents[0]
PEWEAVER = PHASE.parents[3]
WORKSPACE = PHASE.parents[6]
MANIFEST = PHASE / "phase_manifest.json"
FROZEN_CORNER = "tt_025C_1v80"
COMMON_REFERENCE_KEYS = {
    "../../third_party/r22sdf/Butterfly.v",
    "../../third_party/r22sdf/DelayBuffer.v",
    "../../third_party/r22sdf/FFT64.v",
    "../../third_party/r22sdf/Multiply.v",
    "../../third_party/r22sdf/SdfUnit.v",
    "../../third_party/r22sdf/SdfUnit2.v",
    "../../third_party/r22sdf/Twiddle64.v",
    "fft128/../../third_party/r22sdf/Butterfly.v",
    "fft128/../../third_party/r22sdf/DelayBuffer.v",
    "fft128/../../third_party/r22sdf/FFT128.v",
    "fft128/../../third_party/r22sdf/Multiply.v",
    "fft128/../../third_party/r22sdf/SdfUnit.v",
    "fft128/../../third_party/r22sdf/SdfUnit2.v",
    "fft128/../../third_party/r22sdf/Twiddle128.v",
    "fft128/peweaver_halo_fft128_reference.v",
    "peweaver_halo_fft64_reference.v",
}
EXPECTED_REFERENCE_KEYS = {
    "S0": COMMON_REFERENCE_KEYS | {"rtl/peweaver_ppa_shared_fft.v", "rtl/peweaver_shared_fft.v"},
    "A": COMMON_REFERENCE_KEYS | {"rtl/peweaver_ppa_dual_fft.v"},
    "B": COMMON_REFERENCE_KEYS | {"rtl/peweaver_ppa_dual_fft_icg.v"},
}
EXPECTED_FLOW_RTL_KEYS = {
    "S0": {"rtl/peweaver_ppa_shared_fft.v", "rtl/peweaver_shared_fft.v"},
    "A": {
        "rtl/dual/fft128_core.v", "rtl/dual/halo_fft128_wrapper.v",
        "rtl/dual/sdfunit128.v", "rtl/dual/twiddle128_core.v",
        "rtl/peweaver_ppa_dual_fft.v",
    },
    "B": {
        "rtl/dual/fft128_core.v", "rtl/dual/halo_fft128_wrapper.v",
        "rtl/dual/sdfunit128.v", "rtl/dual/twiddle128_core.v",
        "rtl/peweaver_ppa_dual_fft_icg.v", "rtl/sky130_icg_blackbox.v",
    },
}


def load(path: Path) -> dict:
    if not path.is_file():
        raise RuntimeError(f"missing canonical source: {path}")
    return json.loads(path.read_text())


def finite_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field} must be a finite number")
    return float(value)


def exact_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a Boolean")
    return value


def exact_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def resolve_source(path_value: str) -> Path:
    if not isinstance(path_value, str):
        raise ValueError("source path must be a string")
    path = (WORKSPACE / path_value).resolve()
    try:
        path.relative_to(WORKSPACE.resolve())
    except ValueError as exc:
        raise ValueError(f"source path escapes workspace: {path_value}") from exc
    if not path.is_file():
        raise ValueError(f"source file is missing: {path_value}")
    return path


def resolve_declared_reference_source(path_value: str, design: str) -> Path:
    """Resolve B's archived source map to the corresponding local source."""
    if path_value.startswith("../../third_party/r22sdf/") or path_value.startswith("fft128/../../third_party/r22sdf/"):
        return (PEWEAVER / "third_party/r22sdf" / Path(path_value).name).resolve()
    if path_value == "peweaver_halo_fft64_reference.v":
        return (PEWEAVER / "benchmarks/halo_fft64_reference/peweaver_halo_fft64_reference.v").resolve()
    if path_value == "fft128/peweaver_halo_fft128_reference.v":
        return (PEWEAVER / "benchmarks/halo_fft128_reference/peweaver_halo_fft128_reference.v").resolve()
    if path_value == "rtl/peweaver_shared_fft.v" and design == "S0":
        return (PEWEAVER / "orchestration/runs/merge_clean_1/peweaver_shared_fft.mergerun1.v").resolve()
    if path_value == "rtl/peweaver_ppa_shared_fft.v" and design == "S0":
        return (PHASE.parent / "audit/frozen_sources/peweaver_ppa_shared_fft.v").resolve()
    if path_value.startswith("rtl/"):
        physical_root = (PEWEAVER / "physical").resolve()
        path = (physical_root / path_value).resolve()
        try:
            path.relative_to(physical_root)
        except ValueError as exc:
            raise ValueError(f"declared reference source escapes physical tree: {path_value}") from exc
        return path
    raise ValueError(f"unsupported declared reference source for {design}: {path_value}")


def validate_declared_reference_sources(result: dict, design: str) -> None:
    references = result.get("design", {}).get("reference_source_hashes_sha256")
    if design not in EXPECTED_REFERENCE_KEYS:
        return
    if not isinstance(references, dict) or not references:
        raise ValueError(f"{design} result has no declared dependent source hashes")
    missing = EXPECTED_REFERENCE_KEYS[design] - set(references)
    if missing:
        raise ValueError(f"{design} result is missing declared dependent source hashes: {sorted(missing)}")
    for path_value, expected_hash in references.items():
        if not is_sha256(expected_hash):
            raise ValueError(f"{design} reference hash is not canonical: {path_value}")
        source_path = resolve_declared_reference_source(path_value, design)
        if not source_path.is_file():
            raise ValueError(f"{design} declared reference source is missing: {path_value}")
        actual_hash = sha256_file(source_path)
        if actual_hash != expected_hash:
            raise ValueError(f"{design} declared reference hash mismatch: {path_value}")


def validate_flow_rtl_sources(result: dict, design: str) -> None:
    flow_hashes = result.get("flow_input_hashes_sha256")
    if design not in EXPECTED_FLOW_RTL_KEYS:
        return
    if not isinstance(flow_hashes, dict):
        raise ValueError(f"{design} result has no flow input hash map")
    missing = EXPECTED_FLOW_RTL_KEYS[design] - set(flow_hashes)
    if missing:
        raise ValueError(f"{design} result is missing RTL flow input hashes: {sorted(missing)}")
    for path_value, expected_hash in flow_hashes.items():
        if not path_value.startswith("rtl/"):
            continue
        if not is_sha256(expected_hash):
            raise ValueError(f"{design} RTL flow hash is not canonical: {path_value}")
        source_path = resolve_declared_reference_source(path_value, design)
        if not source_path.is_file():
            raise ValueError(f"{design} RTL flow source is missing: {path_value}")
        if sha256_file(source_path) != expected_hash:
            raise ValueError(f"{design} RTL flow source hash mismatch: {path_value}")


def validate_source_identity(result: dict, design: str, source_path: Path, result_key: str, expected_hash: str | None = None) -> str:
    actual_hash = sha256_file(source_path)
    if expected_hash is not None and actual_hash != expected_hash:
        raise ValueError(f"{design} source hash mismatch: expected {expected_hash}, got {actual_hash}")
    flow_hash = result.get("flow_input_hashes_sha256", {}).get(result_key)
    if not is_sha256(flow_hash) or flow_hash != actual_hash:
        raise ValueError(f"{design} result hash mismatch for {result_key}: expected {actual_hash}, got {flow_hash}")
    return actual_hash


def physical_metrics(
    result: dict,
    design: str,
    source_path: Path,
    result_key: str,
    expected_hash: str | None = None,
) -> dict:
    try:
        metrics = result["results"]
        pnr = metrics["pnr"]
        power = metrics["power_mw"]
        energy = metrics["energy_per_fft_nj"]
    except (KeyError, TypeError) as exc:
        raise ValueError("physical result has incomplete results schema") from exc
    validate_source_identity(result, design, source_path, result_key, expected_hash)
    validate_declared_reference_sources(result, design)
    validate_flow_rtl_sources(result, design)
    activity = result.get("activity", {})
    if not isinstance(activity, dict):
        raise ValueError(f"{design} result has no activity object")
    activity64 = exact_int(activity.get("annotated_pins_streaming"), "activity.annotated_pins_streaming")
    activity128 = exact_int(activity.get("annotated_pins_streaming_128"), "activity.annotated_pins_streaming_128")
    if activity64 <= 0 or activity128 <= 0:
        raise ValueError(f"{design} result has no positive streaming activity")
    corner = result.get("pdk", {}).get("timing_corner")
    if corner != FROZEN_CORNER:
        raise ValueError(f"{design} result is not at frozen timing corner {FROZEN_CORNER}")
    area = finite_number(pnr["cell_area_um2"], "pnr.cell_area_um2")
    p64 = finite_number(power["streaming_window_64"]["total_mw"], "power.streaming_window_64.total_mw")
    p128 = finite_number(power["streaming_window_128"]["total_mw"], "power.streaming_window_128.total_mw")
    e64 = finite_number(energy["mode64"]["value"], "energy.mode64.value")
    e128 = finite_number(energy["mode128"]["value"], "energy.mode128.value")
    duration64 = exact_int(energy["mode64"]["duration_ps"], "energy.mode64.duration_ps")
    duration128 = exact_int(energy["mode128"]["duration_ps"], "energy.mode128.duration_ps")
    drc = exact_int(result["drc_violation_lines"], "drc_violation_lines")
    if area <= 0 or min(p64, p128, e64, e128) <= 0 or min(duration64, duration128) <= 0 or drc < 0:
        raise ValueError(f"{design} result contains an invalid non-positive metric")
    if abs(e64 - p64 * duration64 / 3_000_000.0) > 1e-6 or abs(e128 - p128 * duration128 / 3_000_000.0) > 1e-6:
        raise ValueError(f"{design} energy does not agree with power and measured duration")
    return {
        "area_um2": area,
        "p64_mw": p64,
        "p128_mw": p128,
        "e64_nj": e64,
        "e128_nj": e128,
        "timing_met": exact_bool(pnr["timing_met"], "pnr.timing_met"),
        "router_drc_lines": drc,
    }


def placed_area(result: dict, design: str, source_path: Path, result_key: str) -> float:
    try:
        pnr = result["results"]["pnr"]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"{design} result has incomplete placement schema") from exc
    validate_source_identity(result, design, source_path, result_key)
    area = finite_number(pnr["cell_area_um2"], f"{design}.pnr.cell_area_um2")
    if area <= 0:
        raise ValueError(f"{design} placed area must be positive")
    return area


def pct(value: float, baseline: float) -> float:
    if baseline == 0.0:
        raise ValueError("percentage baseline cannot be zero")
    return round(100.0 * (value / baseline - 1.0), 4)


def delta(value: float, baseline: float) -> float:
    return round(value - baseline, 8)


def build_output() -> dict:
    identities = load(MANIFEST)["design_identities"]
    required_designs = {"S0", "S1", "A", "B"}
    allowed_designs = required_designs | {"F"}
    if not required_designs.issubset(identities):
        raise ValueError(f"required design identities missing: {sorted(required_designs - set(identities))}")
    if set(identities) != allowed_designs:
        raise ValueError(f"unexpected design identities: {sorted(set(identities) - allowed_designs)}")
    for name, identity in identities.items():
        if not isinstance(identity, dict) or not is_sha256(identity.get("hash")):
            raise ValueError(f"{name} has no 64-character source hash")
    s0_source_path = resolve_source(identities["S0"]["rtl_path"])
    s0_result_path = PEWEAVER / "orchestration/runs/merge_clean_1/shared_mergerun1_sky130.json"
    s1_result_path = PEWEAVER / "orchestration/runs/ps_fft_campaign/artifacts/final_repeat.json"
    s1_source_path = PEWEAVER / "orchestration/runs/ps_fft_campaign/best/peweaver_shared_fft.v"
    a_result_path = PEWEAVER / "physical/results/dual_baseline_sky130.json"
    a_source_path = resolve_source(identities["A"]["rtl_path"])
    b_result_path = PHASE.parent / "dual_b/results/physical_attempt2/dual_b_sky130.json"
    b_source_path = resolve_source(identities["B"]["rtl_path"])
    fft64_result_path = PEWEAVER / "physical/results/fft64_baseline_sky130.json"
    fft128_result_path = PEWEAVER / "physical/results/fft128_baseline_sky130.json"

    s0 = physical_metrics(load(s0_result_path), "S0", s0_source_path, "rtl/peweaver_shared_fft.v", identities["S0"]["hash"])
    a = physical_metrics(load(a_result_path), "A", a_source_path, "rtl/peweaver_ppa_dual_fft.v", identities["A"]["hash"])
    b = physical_metrics(load(b_result_path), "B", b_source_path, "rtl/peweaver_ppa_dual_fft_icg.v", identities["B"]["hash"])
    fft64_area = placed_area(
        load(fft64_result_path), "FFT64", PEWEAVER / "physical/rtl/peweaver_ppa_fft64.v", "rtl/peweaver_ppa_fft64.v"
    )
    fft128_area = placed_area(
        load(fft128_result_path), "FFT128", PEWEAVER / "physical/rtl/peweaver_ppa_fft128.v", "rtl/peweaver_ppa_fft128.v"
    )
    s1_raw = load(s1_result_path)["physical_metrics"]
    s1_report = load(s1_result_path)
    if s1_report.get("verified") is not True or any(
        s1_report.get("checks", {}).get(name) is not True
        for name in ("candidate_hash", "cheap_accept", "physical_no_retry", "physical_passed", "objectives_finite", "constraints_hold", "metrics_agree")
    ):
        raise ValueError("S1 final_repeat is not fully verified")
    s1_hash = sha256_file(s1_source_path)
    if s1_hash != identities["S1"]["hash"] or s1_report.get("best_hash") != s1_hash:
        raise ValueError("S1 source hash is not bound to final_repeat.best_hash and phase manifest")
    s1 = {
        "area_um2": finite_number(s1_raw["area"], "S1.area"),
        "p64_mw": finite_number(s1_raw["p64"], "S1.p64"),
        "p128_mw": finite_number(s1_raw["p128"], "S1.p128"),
        "e64_nj": finite_number(s1_raw["e64"], "S1.e64"),
        "e128_nj": finite_number(s1_raw["e128"], "S1.e128"),
        "timing_met": None,
        "router_drc_lines": None,
    }
    if any(value <= 0 for key, value in s1.items() if key.endswith(("_um2", "_mw", "_nj"))):
        raise ValueError("S1 contains a non-positive PPA metric")

    rows = []
    for name, role, metrics, evidence in (
        ("S0", "accepted shared FFT", s0, str(s0_result_path)),
        ("S1", "PowerSave area Pareto point", s1, str(s1_result_path)),
        ("A", "ungated dual-core control", a, str(a_result_path)),
        ("B", "power-managed dual-core control", b, str(b_result_path)),
    ):
        row = {
            "design": name,
            "role": role,
            "source_hash": identities[name]["hash"],
            "evidence": str(Path(evidence).relative_to(PEWEAVER)),
            **metrics,
            "independent_streamed_drc": "NOT_VERIFIED" if name in {"S0", "A"} else "NOT_APPLICABLE",
            "independent_lvs": "NOT_RUN",
            "physical_detail_scope": "ppa_and_identity_validated; timing_and_drc_detail_not_archived" if name == "S1" else ("candidate_and_declared_dependency_identity_validated" if name == "S0" else "wrapper_and_declared_dependency_identity_validated"),
        }
        rows.append(row)

    by_name = {row["design"]: row for row in rows}
    standalone_sum = fft64_area + fft128_area
    comparisons = {
        "area_vs_standalone_sum_pct": {
            name: pct(row["area_um2"], standalone_sum) for name, row in by_name.items()
        },
        "area_vs_dual_a_pct": {
            name: pct(row["area_um2"], by_name["A"]["area_um2"])
            for name, row in by_name.items()
        },
        "power_vs_dual_a_pct": {
            name: {
                "mode64": pct(row["p64_mw"], by_name["A"]["p64_mw"]),
                "mode128": pct(row["p128_mw"], by_name["A"]["p128_mw"]),
            }
            for name, row in by_name.items()
        },
        "energy_vs_dual_a_pct": {
            name: {
                "mode64": pct(row["e64_nj"], by_name["A"]["e64_nj"]),
                "mode128": pct(row["e128_nj"], by_name["A"]["e128_nj"]),
            }
            for name, row in by_name.items()
        },
        "s1_vs_s0_raw_delta": {
            "mode64": {
                "power_mw": delta(by_name["S1"]["p64_mw"], by_name["S0"]["p64_mw"]),
                "energy_nj": delta(by_name["S1"]["e64_nj"], by_name["S0"]["e64_nj"]),
            },
            "mode128": {
                "power_mw": delta(by_name["S1"]["p128_mw"], by_name["S0"]["p128_mw"]),
                "energy_nj": delta(by_name["S1"]["e128_nj"], by_name["S0"]["e128_nj"]),
            },
        },
        "power_s0_vs_b_pct": {
            "mode64": pct(by_name["S0"]["p64_mw"], by_name["B"]["p64_mw"]),
            "mode128": pct(by_name["S0"]["p128_mw"], by_name["B"]["p128_mw"]),
        },
        "scope": "B is a non-merged power control; no idle-only B VCD exists.",
    }

    output = {
        "schema": "peweaver-canonical-comparison-1",
        "claim_boundary": "Single-run open-source physical estimates at sky130A tt_025C_1v80; router DRC is not independent streamed-layout signoff.",
        "standalone_placed_area_sum_um2": standalone_sum,
        "rows": rows,
        "comparisons": comparisons,
    }
    return output


def main() -> None:
    output = build_output()
    (PHASE / "canonical_comparison.json").write_text(json.dumps(output, indent=2) + "\n")
    with (PHASE / "canonical_comparison.csv").open("w", newline="") as stream:
        fields = ["design", "role", "source_hash", "evidence", "area_um2", "p64_mw",
                  "p128_mw", "e64_nj", "e128_nj", "timing_met", "router_drc_lines",
                  "independent_streamed_drc", "independent_lvs", "physical_detail_scope"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(output["rows"])
    print("wrote canonical_comparison.json and canonical_comparison.csv")


if __name__ == "__main__":
    main()
