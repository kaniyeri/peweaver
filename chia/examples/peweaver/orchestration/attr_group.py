#!/usr/bin/env python3
"""Group per-instance power by design region for the attribution flow.

Inputs:
  --netlist   the name-preserving attribution netlist (shared_attr_synth.v)
  --power     OpenSTA report_power -per_instance output (W)
  --out       JSON summary path

Method: parse the netlist to map each cell instance to its DRIVEN public
net (RTL names survive this synthesis); fall back to the clock-tree bucket
by cell-name class (clkbuf/clkgate). Region = configurable prefix buckets
over the driven net's RTL name. Sums internal/switching/leakage/total per
region and reconciles against the report grand total. Attribution evidence
only — never a signoff decomposition.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

REGION_RULES = [
    (r"^s1_", "stage1"),
    (r"^s2_", "stage2"),
    (r"^s3_", "stage3"),
    (r"tw", "twiddle"),
    (r"^di_|^do_|^mode", "io"),
    (r"^clock", "clock_root"),
]
CLOCK_CELL = re.compile(r"clkbuf|clkdly|clkgate|dlclk", re.I)


def parse_netlist(netlist: Path) -> tuple[dict[str, str], set[str]]:
    """Return {hierarchical instance path: driven public net} and the
    public net-name set. Module-aware: instances inside a sub-module are
    prefixed with the parent's instantiation name (one level)."""
    text = netlist.read_text()
    public = set()
    for m in re.finditer(r"^\s*wire\s+(?:signed\s+)?(?:\[[^\]]+\]\s*)?(\\?[^\s;]+)", text, re.M):
        name = m.group(1)
        if not re.fullmatch(r"_\d+_", name):
            public.add(name)
    # split into module blocks; find each module's name and the
    # instantiation edges to derive one level of hierarchy prefix
    mod_blocks = re.split(r"\bendmodule\b", text)
    inst_prefix: dict[str, str] = {}  # (module, local inst) -> path prefix
    child_edge: dict[str, str] = {}   # child module -> parent inst name
    for blk in mod_blocks:
        hm = re.search(r"\bmodule\s+(\\?\w+)", blk)
        if not hm:
            continue
        mod = hm.group(1)
        for cm in re.finditer(
                r"\b(?!sky130_fd_sc_hd__)\w+\s+(\\?\S+)\s*\(([^;]*)\);",
                blk, re.S):
            child, pinst = cm.group(1), cm.group(2)
            if child.startswith("sky130"):
                continue
            child_edge[child] = pinst
    def prefix_for(mod: str) -> str:
        # one-level: if this module is instantiated by the TOP, prefix with
        # the top's instance name for it
        top = "peweaver_ppa_shared_fft"
        if mod == top:
            return ""
        if mod in child_edge:
            return child_edge[mod] + "/"
        return ""
    inst_to_net: dict[str, str] = {}
    for blk in mod_blocks:
        hm = re.search(r"\bmodule\s+(\\?\w+)", blk)
        if not hm:
            continue
        mod = hm.group(1)
        pref = prefix_for(mod)
        for m in re.finditer(
                r"(sky130_fd_sc_hd__\w+)\s+(\\?\S+)\s*\(([^;]*?)\);", blk, re.S):
            cell, inst, conns = m.group(1), m.group(2), m.group(3)
            path = pref + inst.replace("\\", "")
            if CLOCK_CELL.search(cell):
                inst_to_net[path] = "__clock_tree__"
                continue
            nets = re.findall(r"\.\w+\(\s*(\\?[^()\s]+(?:\s+\[[^\]]*\])?)\s*\)", conns)
            driven = None
            for n in nets:
                n0 = n.split()[0]
                if n0 in public:
                    driven = n0
                    break
            if driven is None and nets:
                driven = nets[0].split()[0]
            inst_to_net[path] = driven or "__unmapped__"
    return inst_to_net, public


def region_of(net: str) -> str:
    if net in ("__clock_tree__", "__unmapped__"):
        return net.strip("_") or "unmapped"
    # normalize yosys escaped hierarchical names: strip leading backslash
    # and the one-level instance prefix (u_core.)
    n = net.lstrip("\\")
    if n.startswith("u_core."):
        n = n[len("u_core."):]
    for pat, region in REGION_RULES:
        if re.search(pat, n):
            return region
    return "control_glue"


def parse_power(power: Path) -> tuple[dict[str, dict], float]:
    """Parse report_power -per_instance rows: inst internal switching
    leakage total [percent]. Returns per-instance totals in W and the
    grand total (last 'Total' row if present)."""
    rows: dict[str, dict] = {}
    grand = None
    for line in power.read_text().splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0] != "Group":
            try:
                vals = [float(x) for x in parts[1:5]]
            except ValueError:
                continue
            if parts[0] == "Total":
                grand = vals[3]
                continue
            rows[parts[0]] = {"internal": vals[0], "switching": vals[1],
                              "leakage": vals[2], "total": vals[3]}
    return rows, grand if grand is not None else sum(
        v["total"] for v in rows.values())


def emit_region_tcl(netlist: Path, out_tcl: Path) -> dict:
    """Write a TCL file defining REGION_INSTS(region) -> instance list, for
    report_power -instances region sweeps inside the backend session."""
    inst_to_net, _ = parse_netlist(netlist)
    regions: dict[str, list] = defaultdict(list)
    for path, net in inst_to_net.items():
        regions[region_of(net)].append(path)
    lines = ["# generated by attr_group.py --emit-tcl (attribution only)"]
    counts = {}
    for region, insts in sorted(regions.items()):
        counts[region] = len(insts)
        names = " ".join("{" + i + "}" for i in insts)
        lines.append(f"set REGION_INSTS({region}) [list {names}]")
    out_tcl.write_text("\n".join(lines) + "\n")
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--netlist", required=True, type=Path)
    ap.add_argument("--power", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--emit-tcl", type=Path, default=None,
                    help="write region->instance map TCL for the backend")
    args = ap.parse_args()

    if args.emit_tcl is not None:
        counts = emit_region_tcl(args.netlist, args.emit_tcl)
        print(json.dumps({"regions": counts}, indent=1))
        return 0

    inst_to_net, _ = parse_netlist(args.netlist)
    rows, grand = parse_power(args.power)

    regions: dict[str, dict[str, float]] = defaultdict(
        lambda: {"internal": 0.0, "switching": 0.0, "leakage": 0.0,
                 "total": 0.0, "instances": 0})
    unmatched = 0
    for inst, vals in rows.items():
        net = inst_to_net.get(inst)
        if net is None:
            unmatched += 1
            net_region = "unmapped"
        else:
            net_region = region_of(net)
        r = regions[net_region]
        for k in ("internal", "switching", "leakage", "total"):
            r[k] += vals[k]
        r["instances"] += 1

    accounted = sum(r["total"] for r in regions.values())
    summary = {
        "schema": "peweaver-attribution-1",
        "note": ("attribution evidence only: name-preserving synthesis, "
                 "region grouping by driven RTL net; NOT signoff power and "
                 "never compared against frozen PPA"),
        "grand_total_report_W": grand,
        "accounted_total_W": accounted,
        "reconciliation_pct": (100.0 * accounted / grand if grand else None),
        "instances_parsed": len(rows),
        "instances_unmatched": unmatched,
        "regions": dict(regions),
    }
    args.out.write_text(json.dumps(summary, indent=1))
    print(json.dumps({k: v for k, v in summary.items() if k != "regions"},
                     indent=1))
    for name, r in sorted(regions.items(), key=lambda kv: -kv[1]["total"]):
        share = 100.0 * r["total"] / accounted if accounted else 0
        print(f"  {name:14s} {r['total']*1e3:9.4f} mW  {share:5.1f}%  "
              f"({r['instances']} inst)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
