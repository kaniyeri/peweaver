#!/usr/bin/env python3
"""GDS stream-out with full sky130 layer resolution + round-trip audit (WP4).

Reads routed DEF with technology/cell LEFs and a purpose-explicit sky130
layer map derived from the PDK's sky130A.lyp; writes merged GDS; re-imports
the written file and verifies the complete metal stack is present before
reporting success. Fail-closed: any zero-count required layer is an error.
"""
import hashlib, json, sys
from pathlib import Path
import klayout.db as pya

TECH_LEF = "/work/peweaver/toolchains/.volare/sky130A/libs.ref/sky130_fd_sc_hd/techlef/sky130_fd_sc_hd__nom.tlef"
CELL_LEF = "/work/peweaver/toolchains/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lef/sky130_fd_sc_hd.lef"
CELL_GDS = "/work/peweaver/toolchains/.volare/sky130A/libs.ref/sky130_fd_sc_hd/gds/sky130_fd_sc_hd.gds"
MAP_FILE = "/tmp/sky130_gds_layermap.map"
STACK = [("li1",67,20),("mcon",67,44),("met1",68,20),("via",68,44),
         ("met2",69,20),("via2",69,44),("met3",70,20),("via3",70,44),
         ("met4",71,20),("via4",71,44),("met5",72,20)]

def count(lay, top, lnum, dtyp):
    L = lay.layer(lnum, dtyp); n = 0
    it = top.begin_shapes_rec(L)
    while not it.at_end(): n += 1; it.next()
    return n

def streamout(def_file, topname, out_gds):
    opt = pya.LoadLayoutOptions()
    cfg = opt.lefdef_config
    cfg.lef_files = [TECH_LEF, CELL_LEF]
    cfg.read_lef_with_def = True
    cfg.map_file = MAP_FILE
    cfg.produce_via_geometry = True
    cfg.produce_routing = True
    cfg.produce_special_routing = True
    cfg.produce_cell_outlines = True
    lay = pya.Layout()
    lay.read(CELL_GDS)
    lay.read(def_file, opt)
    lay.write(out_gds)
    # fail-closed round-trip audit
    chk = pya.Layout(); chk.read(out_gds)
    top = chk.cell(topname)
    if top is None: raise RuntimeError(f"top cell {topname} missing in {out_gds}")
    stack = {n: count(chk, top, l, d) for n, l, d in STACK}
    zero = [k for k, v in stack.items() if v == 0]
    if zero: raise RuntimeError(f"round-trip audit failed: empty layers {zero}")
    data = open(out_gds, "rb").read()
    return {"out_gds": out_gds, "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data), "width_um": round(top.bbox().width()*chk.dbu,3),
            "height_um": round(top.bbox().height()*chk.dbu,3),
            "instances": top.child_instances(), "stack_shapes": stack,
            "status": "STREAMOUT_ROUNDTRIP_AUDITED"}

if __name__ == "__main__":
    jobs = json.load(open(sys.argv[1]))
    out = {}
    for tag, j in jobs.items():
        out[tag] = streamout(j["def"], j["top"], j["out"])
        print(tag, json.dumps(out[tag]))
    json.dump(out, open(sys.argv[2], "w"), indent=2)
