#!/usr/bin/env python3
"""Capture and compare compact physical-flow reproducibility evidence.

This intentionally stores hashes and selected result metrics, not copies of
large VCD/SPEF/DEF artifacts.  SPEF comparison removes only its generated
``*DATE`` line; canonical VCDs are compared byte-for-byte.

Examples:
  reproducibility.py capture --design fft64 --output results/reproducibility/fft64_run1.json
  reproducibility.py compare --run1 results/reproducibility/fft64_run1.json \
      --run2 results/reproducibility/fft64_run2.json --output results/reproducibility/fft64_compare.json
"""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

PHYS = Path(__file__).resolve().parent
RESULTS = PHYS / "results"
EVIDENCE_SCHEMA = "peweaver-reproducibility-evidence-3"


def digest_bytes(data):
    return hashlib.sha256(data).hexdigest()


def digest_file(path):
    return digest_bytes(path.read_bytes())


def spef_without_date(path):
    return b"".join(line for line in path.read_bytes().splitlines(keepends=True)
                   if not line.startswith(b"*DATE "))


def result_for_design(design):
    return RESULTS / ("fft128_baseline_sky130.json" if design == "fft128"
                      else "fft64_baseline_sky130.json")


def evidence_path(path):
    """Render an evidence path relative to the physical tree when possible."""
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(PHYS))
    except ValueError:
        return str(resolved)


def capture(design, output):
    result_path = result_for_design(design)
    result = json.loads(result_path.read_text())
    suffix = "_fft128" if design == "fft128" else ""
    names = {
        "vcd_scenario": RESULTS / "activity" / f"gls_scenario{suffix}_norm.vcd",
        "vcd_stream": RESULTS / "activity" / f"gls_stream{suffix}_norm.vcd",
        "netlist": RESULTS / "netlists" / f"{design}_ppa_synth.v",
        "def": RESULTS / "def" / f"{design}_baseline.def",
        "spef": RESULTS / "spef" / f"{design}_baseline.spef",
        "metrics": RESULTS / "reports" / f"metrics{suffix}.txt",
        "drc": RESULTS / "reports" / f"drc{suffix}.rpt",
    }
    report_names = ["sta_max_paths", "sta_min_paths", "sta_setup_paths",
                    "sta_hold_paths", "sta_recovery_paths", "sta_removal_paths",
                    "power_streaming", "power_scenario"]
    for name in report_names:
        names[name] = RESULTS / "reports" / f"{name}{suffix}.rpt"
    artifacts = {}
    for name, path in names.items():
        if not path.is_file():
            raise SystemExit(f"missing artifact: {path}")
        raw = path.read_bytes()
        item = {"path": str(path.relative_to(PHYS)), "bytes": len(raw),
                "sha256": digest_bytes(raw)}
        if name == "spef":
            item["without_date_sha256"] = digest_bytes(spef_without_date(path))
        artifacts[name] = item
    # The assembled record hashes volatile tool logs under ``artifacts``.
    # Compare every other field so methodology/configuration changes cannot
    # hide behind coincidentally identical headline metrics.
    result_semantics = {
        key: value for key, value in result.items() if key != "artifacts"
    }
    record = {
        "schema": EVIDENCE_SCHEMA,
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "design": design,
        "recorder_sha256": digest_file(Path(__file__).resolve()),
        "result_sha256": digest_file(result_path),
        "result_semantics": result_semantics,
        "artifacts": artifacts,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")


def compare(run1, run2, output):
    a, b = json.loads(run1.read_text()), json.loads(run2.read_text())
    if a.get("schema") != EVIDENCE_SCHEMA or b.get("schema") != EVIDENCE_SCHEMA:
        raise SystemExit(f"both run manifests must use {EVIDENCE_SCHEMA}")
    if a["design"] != b["design"]:
        raise SystemExit("run manifests describe different designs")
    equal = {}
    for name in sorted(set(a["artifacts"]) | set(b["artifacts"])):
        x, y = a["artifacts"].get(name), b["artifacts"].get(name)
        if x is None or y is None:
            equal[name] = False
        elif name == "spef":
            equal[name] = x.get("without_date_sha256") == y.get("without_date_sha256")
        else:
            equal[name] = x.get("sha256") == y.get("sha256")
    result_equal = a.get("result_semantics") == b.get("result_semantics")
    recorder_equal = a.get("recorder_sha256") == b.get("recorder_sha256")
    record = {
        "schema": "peweaver-reproducibility-comparison-1",
        "design": a["design"],
        "run1": evidence_path(run1),
        "run2": evidence_path(run2),
        "canonical_rules": {
            "vcd": "compare normalized VCD raw sha256 byte-for-byte",
            "spef": "compare without_date_sha256 (remove only *DATE line)",
            "other_artifacts": "compare raw sha256",
            "result": ("compare all result fields except artifacts; artifact "
                       "hashes include volatile tool logs"),
            "recorder": "both captures must use the same reproducibility.py sha256",
        },
        "artifacts_equal": equal,
        "all_artifacts_equal": all(equal.values()),
        "result_semantics_equal": result_equal,
        "recorder_equal": recorder_equal,
        "result_sha256": {"run1": a.get("result_sha256"), "run2": b.get("result_sha256")},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(json.dumps(record, indent=2, sort_keys=True))
    if not (record["all_artifacts_equal"] and result_equal and recorder_equal):
        raise SystemExit("reproducibility comparison failed")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)
    cp = sub.add_parser("capture")
    cp.add_argument("--design", choices=("fft64", "fft128"), required=True)
    cp.add_argument("--output", type=Path, required=True)
    xp = sub.add_parser("compare")
    xp.add_argument("--run1", type=Path, required=True)
    xp.add_argument("--run2", type=Path, required=True)
    xp.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    if args.command == "capture":
        capture(args.design, args.output)
    else:
        compare(args.run1, args.run2, args.output)


if __name__ == "__main__":
    main()
