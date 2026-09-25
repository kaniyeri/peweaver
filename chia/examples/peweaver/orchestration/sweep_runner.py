#!/usr/bin/env python3
"""Overnight (multi-day) scheduler for the shared-FFT model sweep.

Design: each model is measured both as planner (with a fixed reference
implementer) and as implementer (with a fixed reference planner); two clean
replicates per unique pairing.  GPT-route pairings wait for the configured
usage-window reset.  Idempotent, resumable, index written after every run.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import signal
import subprocess
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
DRIVER = HERE / "sweep_fft_driver.py"
RUNS_BASE = Path("/work/peweaver/runs")
OSS = "/work/peweaver/toolchains/oss-cad-suite/bin"

REFERENCE = "gemini/gemini-3.8-flash"

MODELS = [
    ("terra", "openai/gpt-5.6-terra"),
    ("sol", "openai/gpt-5.6-sol"),
    ("claude", "openrouter/anthropic/claude-sonnet-4.6"),
    ("gemini", REFERENCE),
    ("deepseek", "opencode-go/deepseek-v4.1-flash"),
    ("glm", "opencode-go/glm-5.3-flash"),
    ("kimi", "openrouter/moonshotai/kimi-k2.7-code"),
    ("minimax", "opencode-go/minimax-m3"),
]
REPS = 2
TURNS_CAP = 16
RUN_TIMEOUT = 12_600  # 3.5 h per run
MAX_ATTEMPTS = 2


def is_gpt(model: str) -> bool:
    return model.startswith("openai/")


def build_queue(prefix: str = "msweep") -> list[dict]:
    cells: dict[tuple[str, str], dict] = {}
    for short, model in MODELS:
        for label, planner, worker in ((f"adv-{short}", model, REFERENCE),
                                       (f"impl-{short}", REFERENCE, model)):
            key = (planner, worker)
            if key in cells:
                continue
            name = "ref-gemini" if (planner == REFERENCE and worker == REFERENCE) else label
            cells[key] = {"cell": name, "planner": planner, "worker": worker}
    ordered = sorted(cells.values(),
                     key=lambda c: (is_gpt(c["planner"]) or is_gpt(c["worker"]),
                                    c["cell"]))
    queue = []
    for rep in range(1, REPS + 1):
        for cell in ordered:
            queue.append({**cell, "rep": rep,
                          "run_id": f"{prefix}-{cell['cell']}-r{rep}"})
    return queue


def gpt_not_before(hhmm: str) -> float:
    if not hhmm:
        return 0.0
    hour, minute = (int(part) for part in hhmm.split(":"))
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target < now:
        return 0.0  # the window already opened today; no gate
    return target.timestamp()


def env_for_driver() -> dict:
    env = dict(os.environ)
    env["PATH"] = OSS + ":" + env.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    env["PEWEAVER_YOSYS"] = f"{OSS}/yosys"
    env["PEWEAVER_VERILATOR"] = f"{OSS}/verilator"
    env["PEWEAVER_IVERILOG"] = f"{OSS}/iverilog"
    repo_root = str(HERE.parents[2])
    env["PYTHONPATH"] = ":".join(
        [repo_root, str(HERE), env.get("PYTHONPATH", "")]).strip(":")
    return env


def run_one(item: dict) -> dict:
    run_root = RUNS_BASE / item["run_id"]
    artifacts = run_root / "artifacts"
    summary_path = artifacts / "sweep_run_summary.json"
    started = time.time()
    if summary_path.is_file():
        return {**item, "status": "skipped", "started": started,
                "ended": started, "seconds": 0.0, "exit_code": None}
    artifacts.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-B", str(DRIVER),
           "--run-id", item["run_id"],
           "--planner-model", item["planner"],
           "--worker-model", item["worker"],
           "--turns", str(TURNS_CAP)]
    if item.get("driver_extra"):
        cmd += shlex.split(item["driver_extra"])
    if (artifacts / "state.json").is_file():
        cmd.append("--resume")
    status, code = "done", None
    with (artifacts / "driver_stdout.log").open("ab") as log:
        log.write(f"\n===== {datetime.now().isoformat()} {item['run_id']} =====\n"
                  .encode())
        log.flush()
        proc = subprocess.Popen(cmd, cwd=str(HERE), env=env_for_driver(),
                                stdout=log, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL,
                                start_new_session=True)
        try:
            code = proc.wait(timeout=RUN_TIMEOUT)
        except subprocess.TimeoutExpired:
            status = "timeout"
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                proc.kill()
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                pass
    ended = time.time()
    return {**item, "status": status, "exit_code": code,
            "started": started, "ended": ended,
            "seconds": round(ended - started, 1)}


def save_index(index_path: Path, results: dict[str, dict]) -> None:
    index_path.write_text(json.dumps(
        {"updated": time.time(), "runs": sorted(results.values(),
                                                key=lambda r: r["run_id"])},
        indent=1))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--gpt-after", default="02:35",
                        help="local HH:MM before which openai/* runs wait")
    parser.add_argument("--stop-after", default="09:30",
                        help="local HH:MM after which no new run is started")
    parser.add_argument("--only", default="",
                        help="comma-separated run_id substrings")
    parser.add_argument("--prefix", default="msweep",
                        help="run-id prefix (also selects the index file)")
    parser.add_argument("--driver-extra", default="",
                        help="extra args appended to every driver call")
    args = parser.parse_args()
    os.environ["PATH"] = OSS + ":" + os.environ.get("PATH", "")

    queue = build_queue(args.prefix)
    if args.driver_extra:
        for item in queue:
            item["driver_extra"] = args.driver_extra
    if args.only:
        needles = [n for n in args.only.split(",") if n]
        queue = [q for q in queue if any(n in q["run_id"] for n in needles)]
    index_path = RUNS_BASE / f"{args.prefix}_index.json"
    results: dict[str, dict] = {}
    done_ids: set[str] = set()
    if index_path.is_file():
        for row in json.loads(index_path.read_text()).get("runs", []):
            results[row["run_id"]] = row
            attempts = row.get("attempts", 1)
            if row.get("status") in {"done", "skipped"} or attempts >= MAX_ATTEMPTS:
                done_ids.add(row["run_id"])
    gpt_after_time = gpt_not_before(args.gpt_after)
    hour, minute = (int(p) for p in args.stop_after.split(":"))
    stop_after_dt = datetime.now().replace(hour=hour, minute=minute,
                                           second=0, microsecond=0)
    if stop_after_dt.timestamp() < time.time():
        stop_after_dt += timedelta(days=1)
    stop_after = stop_after_dt.timestamp()

    pending = [q for q in queue if q["run_id"] not in done_ids]
    print(f"sweep queue: {len(pending)} pending / {len(queue)} total; "
          f"gpt window: {datetime.fromtimestamp(gpt_after_time):%H:%M}",
          flush=True)
    running: dict = {}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        while pending or running:
            now = time.time()
            while pending and len(running) < args.workers and now < stop_after:
                eligible = next(
                    (q for q in pending
                     if not (is_gpt(q["planner"]) or is_gpt(q["worker"]))
                     or now >= gpt_after_time), None)
                if eligible is None:
                    break
                pending.remove(eligible)
                running[pool.submit(run_one, eligible)] = eligible
                print(f"[start] {eligible['run_id']} "
                      f"({eligible['planner']} -> {eligible['worker']})",
                      flush=True)
            if not running:
                if not pending:
                    break
                if time.time() >= stop_after:
                    print("[stop] deadline reached; remainder stays queued",
                          flush=True)
                    break
                if all((is_gpt(q["planner"]) or is_gpt(q["worker"]))
                       and time.time() < gpt_after_time for q in pending):
                    wait_s = min(300, max(30, gpt_after_time - time.time() + 5))
                    print(f"[wait] gpt window opens in {wait_s:.0f}s",
                          flush=True)
                    time.sleep(wait_s)
                    continue
                time.sleep(30)
                continue
            done, _ = wait(running, timeout=60, return_when=FIRST_COMPLETED)
            for fut in done:
                item = running.pop(fut)
                try:
                    row = fut.result()
                except Exception as exc:  # pragma: no cover
                    row = {**item, "status": "crashed", "error": str(exc),
                           "seconds": 0.0}
                row["attempts"] = results.get(row["run_id"], {}).get(
                    "attempts", 0) + 1
                results[row["run_id"]] = row
                print(f"[{row['status']}] {row['run_id']} "
                      f"in {row.get('seconds', 0):.0f}s", flush=True)
                save_index(index_path, results)
    save_index(index_path, results)
    print(json.dumps({"completed": len(results), "pending": len(pending)}),
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
