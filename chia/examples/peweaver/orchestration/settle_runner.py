#!/usr/bin/env python3
"""Settle-series runner: focused planner x implementer matrix for the
gemini-vs-sol implementer question, with a transport control.

Cells (prefix msweep3, driver flag --harness-v2):
  core:      planners {gemini, sol, claude, deepseek} x implementers
             {gemini-native, sol} x 4 replicates
  transport: worker gemini via OpenRouter (same opencode path as sol) under
             planners {gemini, sol} x 3 replicates
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sweep_runner import RUNS_BASE, run_one, save_index  # noqa: E402

GEMINI = "gemini/gemini-3.8-flash"
SOL = "openai/gpt-5.6-sol"
CLAUDE = "openrouter/anthropic/claude-sonnet-4.6"
DEEPSEEK = "opencode-go/deepseek-v4.1-flash"
GEMINI_OR = "openrouter/google/gemini-3.8-flash"

CELLS = [
    ("g2g", GEMINI, GEMINI, 4),
    ("s2g", SOL, GEMINI, 4),
    ("c2g", CLAUDE, GEMINI, 4),
    ("d2g", DEEPSEEK, GEMINI, 4),
    ("g2s", GEMINI, SOL, 4),
    ("s2s", SOL, SOL, 4),
    ("c2s", CLAUDE, SOL, 4),
    ("d2s", DEEPSEEK, SOL, 4),
    ("g2gor", GEMINI, GEMINI_OR, 3),
    ("s2gor", SOL, GEMINI_OR, 3),
]


def build_queue(prefix: str = "msweep3") -> list[dict]:
    queue = []
    for label, planner, worker, reps in CELLS:
        for rep in range(1, reps + 1):
            queue.append({
                "cell": label, "planner": planner, "worker": worker,
                "rep": rep, "run_id": f"{prefix}-{label}-r{rep}",
                "driver_extra": "--harness-v2",
            })
    return queue


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--stop-after", default="23:59",
                        help="local HH:MM after which no new run starts")
    parser.add_argument("--prefix", default="msweep3")
    args = parser.parse_args()

    queue = build_queue(args.prefix)
    index_path = RUNS_BASE / f"{args.prefix}_index.json"
    results: dict[str, dict] = {}
    if index_path.is_file():
        for row in json.loads(index_path.read_text()).get("runs", []):
            results[row["run_id"]] = row
    done = {row["run_id"] for row in results.values()
            if row.get("status") in {"done", "skipped"}
            or row.get("attempts", 1) >= 2}
    pending = [q for q in queue if q["run_id"] not in done]
    hour, minute = (int(p) for p in args.stop_after.split(":"))
    stop_after = datetime.now().replace(hour=hour, minute=minute,
                                        second=0, microsecond=0)
    if stop_after.timestamp() < time.time():
        stop_after += timedelta(days=1)
    stop_after = stop_after.timestamp()

    print(f"settle queue: {len(pending)} pending / {len(queue)} total "
          f"({len(CELLS)} cells)", flush=True)
    running: dict = {}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        while pending or running:
            while pending and len(running) < args.workers \
                    and time.time() < stop_after:
                item = pending.pop(0)
                running[pool.submit(run_one, item)] = item
                print(f"[start] {item['run_id']} "
                      f"({item['planner']} -> {item['worker']})", flush=True)
            if not running:
                if not pending:
                    break
                if time.time() >= stop_after:
                    print("[stop] deadline reached", flush=True)
                    break
                time.sleep(30)
                continue
            finished, _ = wait(running, timeout=60,
                               return_when=FIRST_COMPLETED)
            for fut in finished:
                item = running.pop(fut)
                try:
                    row = fut.result()
                except Exception as exc:  # pragma: no cover
                    row = {**item, "status": "crashed", "seconds": 0.0,
                           "error": str(exc)}
                row["attempts"] = results.get(row["run_id"], {}).get(
                    "attempts", 0) + 1
                results[row["run_id"]] = row
                print(f"[{row['status']}] {row['run_id']} in "
                      f"{row.get('seconds', 0):.0f}s", flush=True)
                save_index(index_path, results)
    save_index(index_path, results)
    print(json.dumps({"completed": len(results), "pending": len(pending)}),
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
