#!/usr/bin/env python3
"""Analyse the settle matrix (msweep3) per cell, with quality + usage."""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

RUNS_BASE = Path("/work/peweaver/runs")

CELLS = {
    "g2g": ("gemini", "gemini-native"),
    "s2g": ("sol", "gemini-native"),
    "c2g": ("claude", "gemini-native"),
    "d2g": ("deepseek", "gemini-native"),
    "g2s": ("gemini", "sol"),
    "s2s": ("sol", "sol"),
    "c2s": ("claude", "sol"),
    "d2s": ("deepseek", "sol"),
    "g2gor": ("gemini", "gemini-openrouter"),
    "s2gor": ("sol", "gemini-openrouter"),
}


def usage_for(run_root: Path) -> dict:
    inp = out = cost = 0
    files = list((run_root / "artifacts").glob("*.usage.jsonl"))
    for path in files:
        for line in path.read_text().splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            inp += record.get("input_tokens") or 0
            out += record.get("output_tokens") or 0
            cost += record.get("cost_usd") or 0.0
    return {"input_tokens": inp, "output_tokens": out, "cost_usd": round(cost, 4)}


def run_row(run_root: Path) -> dict | None:
    summary_path = run_root / "artifacts" / "sweep_run_summary.json"
    if not summary_path.is_file():
        return None
    summary = json.loads(summary_path.read_text())
    accept_turn = None
    area = holdout = None
    for path in sorted((run_root / "artifacts").glob("check_turn*.json")):
        try:
            check = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        if check.get("verdict") == "ACCEPT" and accept_turn is None:
            accept_turn = int(path.stem.split("turn")[-1])
            detail = check.get("detail") or {}
            area = (detail.get("area") or {}).get("reduction_pct")
            holdout = (detail.get("holdout") or {}).get("note")
    row = {"accepted": bool(summary.get("accepted")),
           "turns": summary.get("turns_used"),
           "accept_turn": accept_turn, "area_pct": area, "holdout": holdout,
           "seconds": summary.get("seconds")}
    row.update(usage_for(run_root))
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", default="msweep3")
    args = parser.parse_args()
    by_cell: dict[str, list[dict]] = defaultdict(list)
    for directory in sorted(RUNS_BASE.glob(f"{args.prefix}-*")):
        if not directory.is_dir():
            continue
        parts = directory.name.split("-")
        cell = parts[1] if len(parts) > 1 else "?"
        row = run_row(directory)
        if row is not None:
            row["run"] = directory.name
            by_cell[cell].append(row)

    print(f"{'cell':8} {'planner':9} {'worker':16} n acc  turns          "
          f"area%        out_tok  $")
    for cell, (planner, worker) in CELLS.items():
        rows = by_cell.get(cell, [])
        if not rows:
            continue
        accepts = [r for r in rows if r["accepted"]]
        turns = [r["accept_turn"] for r in accepts if r["accept_turn"]]
        areas = [f"{r['area_pct']:.1f}" for r in accepts if r["area_pct"]]
        out_tok = sum(r["output_tokens"] for r in rows)
        cost = sum(r["cost_usd"] for r in rows)
        print(f"{cell:8} {planner:9} {worker:16} {len(rows)} {len(accepts)}  "
              f"{str(turns):14} {str(areas):12} {out_tok:8} {cost:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
