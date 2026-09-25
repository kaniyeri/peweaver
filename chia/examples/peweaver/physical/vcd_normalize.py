#!/usr/bin/env python3
"""Normalize a gate-level activity VCD for OpenSTA power analysis.

Shifts all timestamps so the first recorded event is at #0 (eliminating
the silent prefix from deferred $dumpvars), and replaces the simulator's
wall-clock `$date` header with a canonical value. Validates that the clock
signal has correct 10 ns period rising edges and that the window is
nonempty. Fail-closed on any validation error.

Usage: vcd_normalize.py <input.vcd> <output.vcd> --clock <clock_name> [--period-ps 10000]
"""

import argparse
import re
import sys
from pathlib import Path


def die(msg):
    sys.exit(f"vcd_normalize.py: {msg}")


def canonicalize_and_shift(lines, shift):
    """Return normalized lines with a stable date header and timestamps."""
    out_lines = []
    in_date = False
    date_seen = False
    for line in lines:
        s = line.strip()
        if s == "$date":
            if date_seen:
                die("VCD contains multiple $date header blocks")
            date_seen = True
            in_date = True
            out_lines.extend(["$date", "  normalized by vcd_normalize.py", "$end"])
            continue
        if in_date:
            if s == "$end":
                in_date = False
            continue
        if s.startswith("#"):
            out_lines.append(f"#{int(s[1:]) - shift}")
        else:
            out_lines.append(line)
    if in_date:
        die("unterminated $date header block")
    return out_lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--clock", required=True, help="clock signal name (VCD hierarchy path suffix)")
    ap.add_argument("--period-ps", type=int, default=10000)
    args = ap.parse_args()

    if not args.input.is_file():
        die(f"input file missing: {args.input}")

    lines = args.input.read_text(errors="replace").splitlines()

    # ---- parse header: find the clock signal ID ----
    clock_ids = set()
    scope = []
    in_defs = True
    for line in lines:
        s = line.strip()
        if s.startswith("$scope"):
            scope.append(s.split()[2])
        elif s.startswith("$upscope"):
            if scope:
                scope.pop()
        elif s.startswith("$var"):
            m = re.match(r"\$var\s+\S+\s+1\s+(\S+)\s+(\S+)", s)
            if m:
                path = ".".join(scope + [m.group(2)])
                if path.endswith(args.clock) or path == args.clock:
                    clock_ids.add(m.group(1))
        elif s.startswith("$enddefinitions"):
            in_defs = False
            break

    if not clock_ids:
        die(f"clock signal '{args.clock}' not found in VCD header")

    # ---- scan body: collect timestamps and clock values ----
    clock_edges = []  # (time_ps, value) for rising edges
    first_ts = None
    all_ts = []
    t = 0
    for line in lines:
        s = line.strip()
        if s.startswith("#"):
            t = int(s[1:])
            if first_ts is None:
                first_ts = t
            all_ts.append(t)
            continue
        if in_defs:
            continue
        if s and s[0] in "01" and len(s) >= 2:
            sid = s[1:]
            if sid in clock_ids:
                if s[0] == "1":
                    clock_edges.append(t)

    if first_ts is None or first_ts != all_ts[0] if all_ts else True:
        if not all_ts:
            die("VCD contains no timestamped events")

    if len(clock_edges) < 4:
        die(f"insufficient clock rising edges: {len(clock_edges)} (need >= 4)")

    # ---- validate clock period ----
    periods = [clock_edges[i+1] - clock_edges[i] for i in range(len(clock_edges) - 1)]
    bad = [(i, p) for i, p in enumerate(periods) if p != args.period_ps]
    if bad:
        die(f"clock period violations: {len(bad)}/{len(periods)} edges deviate from "
            f"{args.period_ps} ps (first: edge {bad[0][0]} has {bad[0][1]} ps)")

    # ---- compute the shift: first event timestamp ----
    shift = first_ts
    # ---- write normalized VCD (including stable date header) ----
    out_lines = canonicalize_and_shift(lines, shift)
    args.output.write_text("\n".join(out_lines) + "\n")

    window_ps = (all_ts[-1] - all_ts[0])
    print(f"vcd_normalize.py: shifted {len(all_ts)} timestamps by {shift} ps; "
          f"window {window_ps/1e6:.3f} us; {len(clock_edges)} clock edges at "
          f"{args.period_ps} ps period; canonicalized $date — validated OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
