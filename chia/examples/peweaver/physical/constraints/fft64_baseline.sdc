# PEWeaver FFT64 baseline constraints — frozen per physical/README.md.
# Clock period matches the directed/activity testbench clock (10 ns).
# Clock uncertainty guards against unmodeled clock-tree variation in the
# open-source flow (0.10 ns setup / 0.05 ns hold, per the frozen decisions).

create_clock -name core_clock -period 10.0000 [get_ports clock]
set_clock_uncertainty 0.1000 -setup [get_clocks core_clock]
set_clock_uncertainty 0.0500 -hold [get_clocks core_clock]

# Synchronous data I/O constraints (clock and asynchronous reset excluded).
set_input_delay 1.5000 -clock core_clock [get_ports {di_en di_re di_im}]
set_output_delay 1.5000 -clock core_clock [get_ports {do_en do_re do_im}]

# `reset` asynchronously asserts the two reset-synchronizer flops, so no
# clock-relative external arrival requirement exists at that boundary.  Waive
# only paths launched by the external port.  The synchronizer's registered,
# synchronous release and every downstream core recovery/removal arc remain
# timed and are reported separately by the backend.
set_false_path -from [get_ports reset]

# Explicit I/O environment: driven inputs, loaded outputs.
set_driving_cell -lib_cell sky130_fd_sc_hd__buf_4 [get_ports {di_en di_re di_im reset}]
set_load 0.5000 [get_ports {do_en do_re do_im}]

set_max_fanout 16 [current_design]
