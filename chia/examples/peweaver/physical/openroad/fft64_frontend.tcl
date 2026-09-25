# PEWeaver FFT64 baseline physical flow — FRONTEND (Phase 3).
# Through global routing; saves the ODB checkpoint consumed by the backend.
# Driven by run-physical.sh with the same environment as the backend.

set_thread_count 12

read_liberty $::env(LIB_TT)
read_lef $::env(TECH_LEF)
read_lef $::env(CELL_LEF)
read_verilog $::env(NETLIST)
link_design $::env(TOP_MODULE)
read_sdc $::env(SDC)

# Exclude non-logic cells (probe/lpflow) from resizer/CTS buffer selection.
# List mirrors the ORFS sky130hd DONT_USE_CELLS pinned in synth/filter_liberty.py.
set_dont_use {

  sky130_fd_sc_hd__probe_p_8
  sky130_fd_sc_hd__probec_p_8
  sky130_fd_sc_hd__lpflow_bleeder_1
  sky130_fd_sc_hd__lpflow_clkbufkapwr_1
  sky130_fd_sc_hd__lpflow_clkbufkapwr_16
  sky130_fd_sc_hd__lpflow_clkbufkapwr_2
  sky130_fd_sc_hd__lpflow_clkbufkapwr_4
  sky130_fd_sc_hd__lpflow_clkbufkapwr_8
  sky130_fd_sc_hd__lpflow_clkinvkapwr_1
  sky130_fd_sc_hd__lpflow_clkinvkapwr_16
  sky130_fd_sc_hd__lpflow_clkinvkapwr_2
  sky130_fd_sc_hd__lpflow_clkinvkapwr_4
  sky130_fd_sc_hd__lpflow_clkinvkapwr_8
  sky130_fd_sc_hd__lpflow_decapkapwr_12
  sky130_fd_sc_hd__lpflow_decapkapwr_3
  sky130_fd_sc_hd__lpflow_decapkapwr_4
  sky130_fd_sc_hd__lpflow_decapkapwr_6
  sky130_fd_sc_hd__lpflow_decapkapwr_8
  sky130_fd_sc_hd__lpflow_inputiso0n_1
  sky130_fd_sc_hd__lpflow_inputiso0p_1
  sky130_fd_sc_hd__lpflow_inputiso1n_1
  sky130_fd_sc_hd__lpflow_inputiso1p_1
  sky130_fd_sc_hd__lpflow_inputisolatch_1
  sky130_fd_sc_hd__lpflow_isobufsrc_1
  sky130_fd_sc_hd__lpflow_isobufsrc_16
  sky130_fd_sc_hd__lpflow_isobufsrc_2
  sky130_fd_sc_hd__lpflow_isobufsrc_4
  sky130_fd_sc_hd__lpflow_isobufsrc_8
  sky130_fd_sc_hd__lpflow_isobufsrckapwr_16
  sky130_fd_sc_hd__lpflow_lsbuf_lh_hl_isowell_tap_1
  sky130_fd_sc_hd__lpflow_lsbuf_lh_hl_isowell_tap_2
  sky130_fd_sc_hd__lpflow_lsbuf_lh_hl_isowell_tap_4
  sky130_fd_sc_hd__lpflow_lsbuf_lh_isowell_4
  sky130_fd_sc_hd__lpflow_lsbuf_lh_isowell_tap_1
  sky130_fd_sc_hd__lpflow_lsbuf_lh_isowell_tap_2
  sky130_fd_sc_hd__lpflow_lsbuf_lh_isowell_tap_4
}

#---- Floorplan: utilization 40 %, square core, 5 um core-to-die spacing
initialize_floorplan -utilization 40 -aspect_ratio 1.0 -core_space 5.0 \
    -site unithd
source $::env(PDK_DIR)/make_tracks.tcl
place_pins -hor_layers met3 -ver_layers met2
source $::env(PDK_DIR)/tapcell.tcl

# Constant nets from the reset synchronizer -> tie cells (routable).
insert_tiecells sky130_fd_sc_hd__conb_1/LO
insert_tiecells sky130_fd_sc_hd__conb_1/HI

#---- Power distribution network (pinned ORFS sky130hd grid)
source $::env(PDK_DIR)/pdn.tcl
pdngen

#---- Placement with resizer repairs (layer RC from the pinned platform file)
source $::env(PDK_DIR)/setRC.tcl
global_placement -density 0.60
estimate_parasitics -placement
repair_design
detailed_placement
check_placement -verbose

#---- Clock tree synthesis and post-CTS repair
clock_tree_synthesis -root_buf sky130_fd_sc_hd__clkbuf_4 \
    -buf_list {sky130_fd_sc_hd__clkbuf_1 sky130_fd_sc_hd__clkbuf_2 \
               sky130_fd_sc_hd__clkbuf_4 sky130_fd_sc_hd__clkbuf_8} \
    -sink_clustering_enable
set_propagated_clock [all_clocks]
estimate_parasitics -placement
repair_clock_nets -max_wire_length 1000
repair_timing -setup
detailed_placement
check_placement -verbose

#---- Global routing (met1-met5, pinned ORFS adjustments)
source $::env(PDK_DIR)/fastroute.tcl
global_route

#---- Post-global-route timing repair iteration (ORFS-style): repair on
# routed-RC estimates, re-place, then re-run global routing so the
# checkpoint reflects the repaired netlist.
estimate_parasitics -global_routing
repair_timing -setup
detailed_placement
check_placement -verbose
global_route

#---- Checkpoint for the backend (detailed route, extraction, power)
write_db $::env(ODB_PATH)
puts "PEWEAVER_PHYSICAL_FRONTEND_DONE"
