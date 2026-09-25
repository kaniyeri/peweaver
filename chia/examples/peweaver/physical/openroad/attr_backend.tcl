# PEWeaver FFT64 baseline physical flow — BACKEND (Phase 3).
# Resumes from the frontend ODB checkpoint: detailed routing, OpenRCX
# extraction, trace-based power, and reports. Driven by run-physical.sh.

set_thread_count 12

read_db $::env(ODB_PATH)
read_liberty $::env(LIB_TT)
read_sdc $::env(SDC)

# Restore propagated-clock analysis: read_db does not preserve the SDC
# clock-propagation mode, and ideal-clock timing is not an acceptable
# baseline (frozen decisions require propagated clocks + SDC uncertainty).
set_propagated_clock [all_clocks]

#---- Detailed routing (met1-met5)
detailed_route -output_drc $::env(OUT_DIR)/drc${::env(RPT_TAG)}.rpt \
    -bottom_routing_layer met1 -top_routing_layer met5 -verbose 0

#---- Parasitic extraction with the pinned OpenRCX rules; SPEF round-trip
define_process_corner -ext_model_index 0 X
extract_parasitics -ext_model_file $::env(PDK_DIR)/rcx_patterns.rules
write_spef $::env(SPEF_OUT)
read_spef $::env(SPEF_OUT)

#---- Trace-based power: two annotated activity windows --------------------
#  * VCD_STREAM   : the three-frame continuous-streaming burst only
#                   (active-streaming average power — primary comparison
#                   number)
#  * VCD_SCENARIO : the full reset/idle/streaming scenario (secondary,
#                   whole-window average)
# Both VCDs come from the gate-level simulation of the mapped netlist, so
# the "Annotated N pin activities" line in the log reflects real mapped
# netlist coverage.
set out $::env(OUT_DIR)
read_power_activities -scope $::env(VCD_SCOPE) -vcd $::env(VCD_STREAM)
report_power -digits 6 > $out/power_streaming${::env(RPT_TAG)}.rpt
# ATTRIBUTION-ONLY: region power sweep via report_power -instances.
# ATTR_REGION_TCL defines REGION_INSTS(region) lists from the
# name-preserving netlist; the streaming-window annotation persists across
# the region calls. Region reports are attribution evidence, never
# signoff power, and never compared against frozen PPA numbers.
if {[info exists ::env(ATTR_REGION_TCL)] && $::env(ATTR_REGION_TCL) ne ""
    && [info exists ::env(ATTR_OUT_DIR)] && $::env(ATTR_OUT_DIR) ne ""} {
    source $::env(ATTR_REGION_TCL)
    foreach region [array names REGION_INSTS] {
        set insts $REGION_INSTS($region)
        report_power -instances $insts -digits 6 \
            > $::env(ATTR_OUT_DIR)/attr_power_${region}.rpt
    }
}
if {[info exists ::env(VCD_STREAM_128)] && $::env(VCD_STREAM_128) ne ""} {
    read_power_activities -scope $::env(VCD_SCOPE) -vcd $::env(VCD_STREAM_128)
    report_power -digits 6 > $out/power_streaming_128${::env(RPT_TAG)}.rpt
}
read_power_activities -scope $::env(VCD_SCOPE) -vcd $::env(VCD_SCENARIO)
report_power -digits 6 > $out/power_scenario${::env(RPT_TAG)}.rpt

#---- Reports and machine-readable metrics
report_design_area
report_checks -path_delay max -group_count 5 > $out/sta_max_paths${::env(RPT_TAG)}.rpt
report_checks -path_delay min -group_count 5 > $out/sta_min_paths${::env(RPT_TAG)}.rpt
# Separate synchronous data timing from the synchronously generated reset
# release.  The asynchronous external reset port is waived in the SDC only
# at the two-flop synchronizer boundary; downstream recovery/removal remains
# a real timed path group.
report_checks -path_delay max -path_group core_clock -group_count 5 \
    -sort_by_slack -digits 6 > $out/sta_setup_paths${::env(RPT_TAG)}.rpt
report_checks -path_delay min -path_group core_clock -group_count 5 \
    -sort_by_slack -digits 6 > $out/sta_hold_paths${::env(RPT_TAG)}.rpt
report_checks -path_delay max -path_group asynchronous -group_count 5 \
    -sort_by_slack -digits 6 > $out/sta_recovery_paths${::env(RPT_TAG)}.rpt
report_checks -path_delay min -path_group asynchronous -group_count 5 \
    -sort_by_slack -digits 6 > $out/sta_removal_paths${::env(RPT_TAG)}.rpt
report_wns > $out/wns${::env(RPT_TAG)}.rpt
report_tns > $out/tns${::env(RPT_TAG)}.rpt
write_def $::env(DEF_OUT)

# Structured key metrics (parsed and cross-checked by assemble_results.py).
set block [ord::get_db_block]
set insts [llength [$block getInsts]]
set wns_max [sta::worst_slack -max]
set tns_max [sta::total_negative_slack -max]
set wns_min [sta::worst_slack -min]

set fh [open $out/metrics${::env(RPT_TAG)}.txt w]
puts $fh "instance_count $insts"
puts $fh "worst_slack_max_ns $wns_max"
puts $fh "total_negative_slack_max_ns $tns_max"
puts $fh "worst_slack_min_ns $wns_min"
close $fh

puts "PEWEAVER_PHYSICAL_FLOW_DONE"
