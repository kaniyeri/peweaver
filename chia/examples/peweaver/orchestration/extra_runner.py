#!/usr/bin/env python3
"""Extra implementer runs for the AA-gray models (prefix msweep4).

Each model is tested as implementer with the gemini planner, 2 reps, the same
v2 harness and gate ladder. Reuses the sweep runner primitives.
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
MODELS = [
    ("dspro", "opencode-go/deepseek-v4-pro"),
    ("luna", "openai/gpt-5.6-luna"),
    ("grok", "opencode-go/grok-4.6"),
    ("kimik3", "opencode-go/kimi-k3"),
    ("muse", "opencode-go/muse-spark-1.3-contributor"),
    ("glmmax", "opencode-go/glm-5.3"),
]
REPS = 2


def parse_models(spec: str) -> list[tuple[str, str]]:
    out = []
    for part in spec.split(","):
        short, _, model = part.strip().partition("=")
        if not short or not model:
            raise SystemExit(f"bad --models entry: {part!r}")
        out.append((short, model))
    return out


def build_queue(prefix: str, models: list[tuple[str, str]] | None = None,
                reps: int = REPS) -> list[dict]:
    queue = []
    for short, model in (models or MODELS):
        for rep in range(1, reps + 1):
            queue.append({
                "cell": f"impl-{short}", "planner": GEMINI, "worker": model,
                "rep": rep, "run_id": f"{prefix}-impl-{short}-r{rep}",
                "driver_extra": "--harness-v2",
            })
    return queue


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", default="msweep4")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--stop-after", default="23:59")
    parser.add_argument("--models", default=None,
                        help="short=model_id,... overrides the built-in list")
    parser.add_argument("--reps", type=int, default=REPS)
    args = parser.parse_args()
    queue = build_queue(args.prefix,
                        parse_models(args.models) if args.models else None,
                        args.reps)
    index_path = RUNS_BASE / f"{args.prefix}_index.json"
    results: dict[str, dict] = {}
    if index_path.is_file():
        try:
            for row in json.loads(index_path.read_text()).get("runs", []):
                results[row["run_id"]] = row
        except json.JSONDecodeError:
            pass
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
    print(f"extra queue: {len(pending)} pending / {len(queue)} total", flush=True)
    running: dict = {}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        while pending or running:
            while pending and len(running) < args.workers and time.time() < stop_after:
                item = pending.pop(0)
                running[pool.submit(run_one, item)] = item
                print(f"[start] {item['run_id']} ({item['worker']})", flush=True)
            if not running:
                if not pending:
                    break
                time.sleep(30)
                continue
            finished, _ = wait(running, timeout=60, return_when=FIRST_COMPLETED)
            for fut in finished:
                item = running.pop(fut)
                try:
                    row = fut.result()
                except Exception as exc:  # pragma: no cover
                    row = {**item, "status": "crashed", "seconds": 0.0,
                           "error": str(exc)}
                row["attempts"] = results.get(row["run_id"], {}).get("attempts", 0) + 1
                results[row["run_id"]] = row
                print(f"[{row['status']}] {row['run_id']} in "
                      f"{row.get('seconds', 0):.0f}s", flush=True)
                save_index(index_path, results)
    save_index(index_path, results)
    print(json.dumps({"completed": len(results), "pending": len(pending)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
