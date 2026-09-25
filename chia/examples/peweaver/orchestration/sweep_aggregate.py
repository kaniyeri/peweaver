#!/usr/bin/env python3
"""Aggregate the shared-FFT model sweep into per-run and per-model tables.

Reads the runner index plus each run's artifacts (state.json, check_turn*.json,
sweep_run_summary.json) and emits:
  - msweep_results.csv      one row per run
  - msweep_results.json     per-run rows + per-model/role marginals
  - msweep_summary.md       compact markdown summary
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path

RUNS_BASE = Path("/work/peweaver/runs")
REFERENCE = "gemini/gemini-3.8-flash"
GATE_ORDER = ["lint", "functional", "area", "holdout"]


def first_failed_gate(check: dict) -> str | None:
    detail = check.get("detail") or {}
    for gate in GATE_ORDER:
        entry = detail.get(gate)
        if isinstance(entry, dict) and entry.get("passed") is False:
            return gate
    return None


def load_run(run_id: str, row: dict) -> dict:
    root = RUNS_BASE / run_id
    artifacts = root / "artifacts"
    state_path = artifacts / "state.json"
    summary_path = artifacts / "sweep_run_summary.json"
    state = json.loads(state_path.read_text()) if state_path.is_file() else {}
    summary = json.loads(summary_path.read_text()) if summary_path.is_file() else {}
    checks = {}
    for path in sorted(artifacts.glob("check_turn*.json")):
        turn = int(path.stem.split("turn")[-1])
        try:
            checks[turn] = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
    accept_turn = next((t for t, c in sorted(checks.items())
                        if c.get("verdict") == "ACCEPT"), None)
    failing: dict[str, int] = {}
    for check in checks.values():
        gate = first_failed_gate(check)
        if gate:
            failing[gate] = failing.get(gate, 0) + 1
    accepted_check = checks.get(accept_turn, {}) if accept_turn else {}
    area_detail = ((accepted_check.get("detail") or {}).get("area") or {})
    holdout_detail = ((accepted_check.get("detail") or {}).get("holdout") or {})
    cand_path = root / "best" / "peweaver_shared_fft.v"
    return {
        "run_id": run_id,
        "planner_model": row.get("planner") or summary.get("planner_model"),
        "worker_model": row.get("worker") or summary.get("worker_model"),
        "index_status": row.get("status"),
        "attempts": row.get("attempts"),
        "seconds": row.get("seconds") or summary.get("seconds"),
        "accepted": bool(summary.get("accepted", state.get("accepted", False))),
        "accept_turn": accept_turn,
        "turns_used": summary.get("turns_used") or state.get("turn"),
        "turns_cap": summary.get("turns_cap"),
        "best_level": summary.get("best_level", state.get("best_level")),
        "first_failed_histogram": failing,
        "area_cell_count": area_detail.get("cand_cell_count"),
        "area_reduction_pct": area_detail.get("reduction_pct"),
        "holdout_note": (holdout_detail.get("note") or "")[:120],
        "history_statuses": summary.get("history_statuses")
        or [h.get("status") for h in state.get("history", [])],
        "candidate_sha256": (__import__("hashlib").sha256(cand_path.read_bytes()).hexdigest()
                             if cand_path.is_file() else None),
    }


def marginal(rows: list[dict], role: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in rows:
        if role == "planner":
            if row["worker_model"] != REFERENCE or row["planner_model"] is None:
                continue
            model = row["planner_model"]
        else:
            if row["planner_model"] != REFERENCE or row["worker_model"] is None:
                continue
            model = row["worker_model"]
        entry = out.setdefault(model, {
            "n": 0, "accepted": 0, "censored": 0,
            "turns_accepted": [], "gate_failures": {},
        })
        entry["n"] += 1
        if row["accepted"]:
            entry["accepted"] += 1
            if row["accept_turn"]:
                entry["turns_accepted"].append(row["accept_turn"])
        else:
            entry["censored"] += 1
            statuses = row.get("history_statuses") or []
            if any(x == "implement_failed" for x in statuses):
                entry["no_usable_reply_runs"] = entry.get(
                    "no_usable_reply_runs", 0) + 1
            else:
                entry["gate_rejected_runs"] = entry.get(
                    "gate_rejected_runs", 0) + 1
        for gate, count in (row["first_failed_histogram"] or {}).items():
            entry["gate_failures"][gate] = entry["gate_failures"].get(gate, 0) + count
    for entry in out.values():
        turns = entry["turns_accepted"]
        entry["success_pct"] = round(100 * entry["accepted"] / entry["n"], 1) if entry["n"] else None
        entry["mean_turns_accepted"] = round(statistics.mean(turns), 2) if turns else None
        entry["median_turns_accepted"] = round(statistics.median(turns), 2) if turns else None
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path,
                        default=RUNS_BASE / "msweep_index.json")
    parser.add_argument("--out-dir", type=Path, default=RUNS_BASE)
    args = parser.parse_args()
    index = {}
    if args.index.is_file():
        index = {r["run_id"]: r
                 for r in json.loads(args.index.read_text()).get("runs", [])}
    else:
        print(f"warning: missing index {args.index}", file=sys.stderr)
    rows = []
    for directory in sorted(RUNS_BASE.glob("msweep*")):
        if not directory.is_dir():
            continue
        run_id = directory.name
        if "probe" in run_id or "smoke" in run_id:
            continue
        row = index.get(run_id, {"run_id": run_id, "status": "unindexed"})
        rows.append(load_run(run_id, row))
    rows.sort(key=lambda r: r["run_id"])
    planners = marginal(rows, "planner")
    implementers = marginal(rows, "implementer")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else []
    with (args.out_dir / "msweep_results.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            flat = dict(row)
            flat["first_failed_histogram"] = json.dumps(flat["first_failed_histogram"])
            flat["history_statuses"] = json.dumps(flat["history_statuses"] or [])
            writer.writerow(flat)
    output = {"runs": rows,
              "planner_marginals": planners,
              "implementer_marginals": implementers}
    (args.out_dir / "msweep_results.json").write_text(json.dumps(output, indent=1))

    lines = ["# Shared-FFT model sweep", "",
             f"Runs: {len(rows)}  Accepted: "
             f"{sum(1 for r in rows if r['accepted'])}", "",
             "## Model as planner (impl = gemini-3.8-flash)", "",
             "| model | n | accepted | success% | mean turns (accepted) |",
             "|---|---:|---:|---:|---:|"]
    for model, entry in sorted(planners.items()):
        lines.append(f"| {model} | {entry['n']} | {entry['accepted']} | "
                     f"{entry['success_pct']} | {entry['mean_turns_accepted']} |")
    lines += ["", "## Model as implementer (planner = gemini-3.8-flash)", "",
              "| model | n | accepted | success% | mean turns (accepted) |",
              "|---|---:|---:|---:|---:|"]
    for model, entry in sorted(implementers.items()):
        lines.append(f"| {model} | {entry['n']} | {entry['accepted']} | "
                     f"{entry['success_pct']} | {entry['mean_turns_accepted']} |")
    lines += ["", "## Per-run", "",
              "| run | planner | worker | status | accepted | turn | area red.% |",
              "|---|---|---|---|---:|---:|---:|"]
    for row in rows:
        lines.append(
            f"| {row['run_id']} | {row['planner_model']} | {row['worker_model']} | "
            f"{row['index_status']} | {row['accepted']} | {row['accept_turn']} | "
            f"{row['area_reduction_pct']} |")
    (args.out_dir / "msweep_summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
