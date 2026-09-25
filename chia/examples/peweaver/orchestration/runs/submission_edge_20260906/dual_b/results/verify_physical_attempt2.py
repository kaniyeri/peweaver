#!/usr/bin/env python3
"""Independently verify the archived Variant B physical result.

This verifier does not rerun EDA. It checks that the assembled result is
internally consistent with its archived artifacts and that the required
completion markers and hard physical gates are present.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent / "physical_attempt2"
RESULT = ROOT / "dual_b_sky130.json"


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def local_artifact(path: str) -> Path:
    parts = Path(path).parts
    try:
        result_index = parts.index("results")
    except ValueError:
        fail(f"artifact path has no results component: {path}")
    return ROOT.joinpath(*parts[result_index + 1 :])


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    if not RESULT.is_file():
        fail(f"missing result {RESULT}")
    result = json.loads(RESULT.read_text())
    if result.get("schema") != "peweaver-physical-result-2":
        fail(f"unexpected schema: {result.get('schema')}")
    if result.get("design", {}).get("top") != "peweaver_ppa_dual_fft_icg":
        fail("result top is not Variant B")

    pnr = result.get("results", {}).get("pnr", {})
    if pnr.get("timing_met") is not True:
        fail(f"timing_met is not true: {pnr.get('timing_met')}")
    if float(pnr.get("total_negative_slack_max_ns", 1.0)) != 0.0:
        fail(f"TNS is not zero: {pnr.get('total_negative_slack_max_ns')}")
    if int(result.get("drc_violation_lines", -1)) != 0:
        fail(f"DRC violation lines are not zero: {result.get('drc_violation_lines')}")

    activity = result.get("activity", {})
    for field in ("annotated_pins_scenario", "annotated_pins_streaming", "annotated_pins_streaming_128"):
        if int(activity.get(field, 0)) <= 0:
            fail(f"missing activity annotation: {field}")

    checked = 0
    for name, record in result.get("artifacts", {}).items():
        path = local_artifact(record["path"])
        if not path.is_file():
            fail(f"missing artifact {name}: {path}")
        if path.stat().st_size != int(record["bytes"]):
            fail(f"size mismatch {name}: {path.stat().st_size} != {record['bytes']}")
        actual = sha256(path)
        if actual != record["sha256"]:
            fail(f"hash mismatch {name}: {actual} != {record['sha256']}")
        checked += 1

    backend_log = local_artifact(result["artifacts"]["openroad_backend_log"]["path"])
    frontend_log = local_artifact(result["artifacts"]["openroad_frontend_log"]["path"])
    stdout_log = ROOT / "logs" / "dual_b_attempt2_stdout.log"
    for log, marker in ((frontend_log, "PEWEAVER_PHYSICAL_FRONTEND_DONE"),
                        (backend_log, "PEWEAVER_PHYSICAL_FLOW_DONE"),
                        (stdout_log, "run-physical.sh: DONE")):
        if not log.is_file() or marker not in log.read_text(errors="replace"):
            fail(f"missing completion marker {marker} in {log}")
    for log in (frontend_log, backend_log, stdout_log):
        if "STA-1452" in log.read_text(errors="replace"):
            fail(f"STA-1452 present in {log}")

    print(json.dumps({
        "status": "PASS",
        "result": str(RESULT),
        "checked_artifacts": checked,
        "timing_met": pnr["timing_met"],
        "setup_slack_ns": pnr["setup_slack_ns"],
        "hold_slack_ns": pnr["hold_slack_ns"],
        "total_negative_slack_max_ns": pnr["total_negative_slack_max_ns"],
        "drc_violation_lines": result["drc_violation_lines"],
        "activity_annotations": {
            "scenario": activity["annotated_pins_scenario"],
            "streaming_64": activity["annotated_pins_streaming"],
            "streaming_128": activity["annotated_pins_streaming_128"],
        },
    }, indent=2))


if __name__ == "__main__":
    main()
