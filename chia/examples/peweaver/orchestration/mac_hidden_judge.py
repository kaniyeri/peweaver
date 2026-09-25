#!/usr/bin/env python3
"""Controller-only second-seed hidden judge for accepted MAC candidates.

The acceptance ladder's randomized judge uses a fixed public seed
(0x5ACED1CE, in-repo). This judge re-evaluates an accepted candidate on a
DIFFERENT seed plus the directed corners, after the model turn, with the
seeds held outside the model-visible contract. Run only post-acceptance:

    python orchestration/mac_hidden_judge.py --candidate <path.v> --work <dir>

Exit 0 = bit-exact on both hidden sets; nonzero = mismatch (hard failure).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mac_merge_driver import (CANDIDATE, _directed_stim, _oracle_stream,
                              make_mac_judge)

HIDDEN_SEED = 0x7EEDBEEF  # controller-only; never present in prompts


def hidden_stim(cycles: int = 1500) -> list:
    rng = random.Random(HIDDEN_SEED)
    stim = []
    mode = 0
    pending = False
    prev_en = 0
    for k in range(cycles):
        if rng.random() < 0.012:
            pending = True
        en = 0 if rng.random() < 0.09 else 1
        rst = 1 if k in (0, 1) else (1 if k in (403, 404, 806, 807) else 0)
        # consume a pending mode change only on a legal edge: en==0 now
        # (contract: the edge where the new mode appears must have en=0)
        if pending and en == 0 and not rst:
            mode ^= 1
            pending = False
        stim.append((mode, en, rng.randrange(256), rng.randrange(256), rst))
    stim.append((0, 0, 0, 0, 1))
    stim.append((0, 1, 0x7F, 0x02, 0))
    return stim


def judge_stream(candidate: Path, stim: list, tag: str) -> dict:
    """Reuse the compiled-judge path with a custom stimulus via the TB."""
    import shutil
    import subprocess
    import os

    verilator = shutil.which("verilator") or os.environ.get("PEWEAVER_VERILATOR")
    tb = Path(__file__).resolve().parents[1] / "merge_benchmarks" / \
        "mac_reference" / "mac_holdout_tb.sv"
    work = Path(tag)
    work.mkdir(parents=True, exist_ok=True)
    stim_path = work / "stim.txt"
    stim_path.write_text("".join(
        f"{(m & 1) | ((e & 1) << 1):02x} {a:02x} {b:02x} {r:02x}\n"
        for m, e, a, b, r in stim))
    cap_path = work / "cap.txt"
    build = work / "obj"
    r = subprocess.run(
        [verilator, "--binary", "--timing", "--x-assign", "0",
         "--x-initial", "0", "-Wno-fatal", "--top-module", "mac_holdout_tb",
         "--Mdir", str(build), str(candidate), str(tb)],
        cwd=str(work), capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        return {"passed": False, "note": "compile failed: " +
                ((r.stdout or "") + (r.stderr or ""))[-200:]}
    run = subprocess.run(
        [str(build / "Vmac_holdout_tb"), f"+STIM={stim_path}",
         f"+OUT={cap_path}", f"+CYCLES={len(stim)}"],
        cwd=str(work), capture_output=True, text=True, timeout=600)
    log = (run.stdout or "") + (run.stderr or "")
    if "MAC_DONE" not in log:
        return {"passed": False, "note": log[-200:]}
    got = [int(w, 16) for w in cap_path.read_text().split()]
    expected = _oracle_stream(stim)
    if len(got) != len(expected):
        return {"passed": False,
                "note": f"captured {len(got)}, expected {len(expected)}"}
    mism = sum(1 for g, e in zip(got, expected) if g != e)
    if mism:
        return {"passed": False, "note": f"{mism}/{len(expected)} mismatches"}
    return {"passed": True, "note": f"bit-exact over {len(expected)} cycles"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--candidate", required=True, type=Path)
    ap.add_argument("--work", required=True, type=Path)
    args = ap.parse_args()

    if not args.candidate.is_file():
        print(json.dumps({"error": "candidate missing"}))
        return 2

    # Verilator runs from each temporary work directory; resolve the
    # controller-supplied candidate before changing cwd.
    candidate = args.candidate.resolve()
    work = args.work.resolve()

    hidden = hidden_stim()
    report = {
        "candidate": str(candidate),
        "judge": "second-seed hidden (0x7EEDBEEF) + directed corners",
        "hidden_seed": HIDDEN_SEED,
    }
    r1 = judge_stream(candidate, hidden, work / "hidden_seed")
    report["hidden_randomized"] = r1
    # directed corners with the SAME oracle (fixed stimulus, seed-free)
    r2 = judge_stream(candidate, _directed_stim(), work / "hidden_corners")
    report["directed_corners"] = r2
    report["verified"] = bool(r1["passed"] and r2["passed"])
    work.mkdir(parents=True, exist_ok=True)
    (work / "hidden_judge_report.json").write_text(
        json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))
    return 0 if report["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
