#!/usr/bin/env bash
# PEWeaver Phase 3 physical flow driver (PHYSICAL_PPA_PLAN.md).
# Stages (each fails closed):
#   0. verify pinned tools and PDK against physical/tool-lock.json
#   1. Yosys synthesis to sky130_fd_sc_hd (tt_025C_1v80)
#   2. Verilator activity simulation -> VCD trace
#   3. OpenROAD floorplan/place/CTS/route/extract/STA/power
#   4. machine-readable result assembly (results/<design>_baseline_sky130.json)
set -Eeuo pipefail

script_path="${BASH_SOURCE[0]}"
phys_dir="$(cd -- "$(dirname -- "$script_path")" && pwd -P)"
repo_root="$(cd -- "${phys_dir}/.." && pwd -P)"   # examples/peweaver
cd -- "${phys_dir}"

#---------------------------------------------------------------------- tools
resolve_tool() { # $1=env var name $2=tool name
    local override="${!1:-}"
    if [[ -n "${override}" ]]; then
        echo "${override}"
        return
    fi
    # repo_root=examples/peweaver -> chialoop/toolchains is two levels up
    local suite="${repo_root}/../../../toolchains/oss-cad-suite/bin/$2"
    if [[ -x "${suite}" ]]; then
        echo "${suite}"
        return
    fi
    command -v "$2"
}

YOSYS="$(resolve_tool PEWEAVER_YOSYS yosys yosys)"
VERILATOR="$(resolve_tool PEWEAVER_VERILATOR verilator verilator)"
OPENROAD="$(resolve_tool PEWEAVER_OPENROAD openroad openroad)"
[[ -x "${YOSYS}" ]] || { echo "run-physical.sh: yosys not found" >&2; exit 2; }
[[ -x "${VERILATOR}" ]] || { echo "run-physical.sh: verilator not found" >&2; exit 2; }
[[ -x "${OPENROAD}" ]] || { echo "run-physical.sh: openroad not found (install the pinned Precision Innovations build, see tool-lock.json)" >&2; exit 2; }
export YOSYS VERILATOR OPENROAD

VOLARE_VENV="${PEWEAVER_VOLARE_VENV:-${repo_root}/../../../toolchains/physical-venv}"
VOLARE="${VOLARE_VENV}/bin/volare"
[[ -x "${VOLARE}" ]] || { echo "run-physical.sh: volare not found at ${VOLARE}" >&2; exit 2; }
PDK_ROOT="${PEWEAVER_PDK_ROOT:-${HOME}/.volare}"
export PDK_ROOT

PY="${PEWEAVER_PYTHON:-python3}"
"${PY}" --version >/dev/null || exit 2

#---------------------------------------------------------------------- stage 0
echo "run-physical.sh: verifying tool/PDK pins against tool-lock.json"
"${PY}" - <<'EOF'
import json, os, subprocess, sys

lock = json.load(open("tool-lock.json"))
def die(msg): sys.exit(f"run-physical.sh: pin verification failed: {msg}")

def check(label, actual, expected):
    if expected not in actual:
        die(f"{label}: '{expected}' not in '{actual.strip()}'")

def tool_version(argv):
    r = subprocess.run(argv, capture_output=True, text=True)
    return (r.stdout or "") + (r.stderr or "")

check("openroad", tool_version([os.environ["OPENROAD"], "-version"]),
      lock["tools"]["openroad"]["version"])
check("yosys", tool_version([os.environ["YOSYS"], "-V"]),
      lock["tools"]["yosys"]["version"])
check("verilator", tool_version([os.environ["VERILATOR"], "--version"]),
      lock["tools"]["verilator"]["version"])
print("run-physical.sh: tool binaries match tool-lock.json")
EOF

enabled_version="$(${VOLARE} output --pdk sky130 2>/dev/null || true)"
[[ "${enabled_version}" == "$(python3 -c "import json;print(json.load(open('tool-lock.json'))['pdk']['volare_version'])")" ]] \
    || { echo "run-physical.sh: enabled volare sky130 version '${enabled_version}' does not match tool-lock.json" >&2; exit 2; }
echo "run-physical.sh: pins verified (openroad/yosys/verilator/volare)"

#---------------------------------------------------------------------- paths
PDK="${PDK_ROOT}/sky130A"
HD="${PDK}/libs.ref/sky130_fd_sc_hd"
LIB_TT="${HD}/lib/sky130_fd_sc_hd__tt_025C_1v80.lib"
TECH_LEF="${HD}/techlef/sky130_fd_sc_hd__nom.tlef"
CELL_LEF="${HD}/lef/sky130_fd_sc_hd.lef"
for f in "${LIB_TT}" "${TECH_LEF}" "${CELL_LEF}"; do
    [[ -f "${f}" ]] || { echo "run-physical.sh: missing PDK file ${f}" >&2; exit 2; }
done
ABS_PHYS="$(pwd -P)"
DESIGN="${PEWEAVER_DESIGN:-fft64}"
# Optional additive overrides (default = frozen behavior; attribution-only
# flows set these explicitly and are labelled separately, never compared
# against frozen results):
PEWEAVER_RESULTS_DIR="${PEWEAVER_RESULTS_DIR:-results}"
PEWEAVER_SYNTH_TPL="${PEWEAVER_SYNTH_TPL:-}"
PEWEAVER_BACKEND_TPL="${PEWEAVER_BACKEND_TPL:-}"
PEWEAVER_FRONTEND_TPL="${PEWEAVER_FRONTEND_TPL:-}"
RESULTS="${ABS_PHYS}/${PEWEAVER_RESULTS_DIR}"
OUT_DIR="${RESULTS}/reports"
mkdir -p "${RESULTS}"/{logs,reports,netlists,activity,spef,def} "${RESULTS}/work"
# The leakage spot-check is a design-independent frozen input to result
# assembly. Keep it in the source snapshot so a fresh evaluator does not rely
# on historical physical/results artifacts.
LEAKAGE_RECORD="${ABS_PHYS}/leakage_check/nand2_leakage_check.json"
if [[ -f "${LEAKAGE_RECORD}" ]]; then
    mkdir -p "${RESULTS}/leakage_check"
    cp -f "${LEAKAGE_RECORD}" "${RESULTS}/leakage_check/nand2_leakage_check.json"
else
    echo "run-physical.sh: missing required leakage record at ${LEAKAGE_RECORD}" >&2
    exit 2
fi
case "${DESIGN}" in
    fft64)
        FIXTURE="${repo_root}/benchmarks/halo_fft64_reference"
        SYNTH_TPL="synth/fft64_synth.ys"
        NETLIST="${RESULTS}/netlists/fft64_ppa_synth.v"
        SDC="${ABS_PHYS}/constraints/fft64_baseline.sdc"
        ACT_TB="${ABS_PHYS}/activity/fft64_activity_tb.sv"
        RTL_WRAPPER="${ABS_PHYS}/rtl/peweaver_ppa_fft64.v"
        TB_TOP="peweaver_fft64_activity_tb"
        LOG_TAG=""
        RPT_TAG=""
        VCD_TAG=""
        CORE_RTL=("FFT64.v" "SdfUnit.v" "SdfUnit2.v" "Butterfly.v" "DelayBuffer.v" "Multiply.v" "Twiddle64.v")
        ACTIVITY_SOURCES=("${RTL_WRAPPER}" "${FIXTURE}/peweaver_halo_fft64_reference.v" ${CORE_RTL[@]/#/"${repo_root}/third_party/r22sdf/"})
        SHARED_SOURCES=""
        GLS_VVP="${RESULTS}/work/fft64_gls.vvp"
        RESULT_JSON="fft64_baseline_sky130.json"
        ;;
    fft128)
        FIXTURE="${repo_root}/benchmarks/halo_fft128_reference"
        SYNTH_TPL="synth/fft128_synth.ys"
        NETLIST="${RESULTS}/netlists/fft128_ppa_synth.v"
        SDC="${ABS_PHYS}/constraints/fft128_baseline.sdc"
        ACT_TB="${ABS_PHYS}/activity/fft128_activity_tb.sv"
        RTL_WRAPPER="${ABS_PHYS}/rtl/peweaver_ppa_fft128.v"
        TB_TOP="peweaver_fft128_activity_tb"
        LOG_TAG="_fft128"
        RPT_TAG="_fft128"
        VCD_TAG="_fft128"
        CORE_RTL=("FFT128.v" "SdfUnit.v" "SdfUnit2.v" "Butterfly.v" "DelayBuffer.v" "Multiply.v" "Twiddle128.v")
        ACTIVITY_SOURCES=("${RTL_WRAPPER}" "${FIXTURE}/peweaver_halo_fft128_reference.v" ${CORE_RTL[@]/#/"${repo_root}/third_party/r22sdf/"})
        SHARED_SOURCES=""
        GLS_VVP="${RESULTS}/work/fft128_gls.vvp"
        RESULT_JSON="fft128_baseline_sky130.json"
        ;;
    shared)
        FIXTURE="${repo_root}/benchmarks/halo_fft64_reference"
        SYNTH_TPL="synth/shared_synth.ys"
        NETLIST="${RESULTS}/netlists/shared_ppa_synth.v"
        SDC="${ABS_PHYS}/constraints/shared_baseline.sdc"
        ACT_TB="${ABS_PHYS}/activity/shared_activity_tb.sv"
        RTL_WRAPPER="${ABS_PHYS}/rtl/peweaver_ppa_shared_fft.v"
        TB_TOP="peweaver_shared_activity_tb"
        LOG_TAG="_shared"
        RPT_TAG="_shared"
        VCD_TAG="_shared"
        ACTIVITY_SOURCES=("${RTL_WRAPPER}" "${ABS_PHYS}/rtl/peweaver_shared_fft.v")
        GLS_VVP="${RESULTS}/work/shared_gls.vvp"
        RESULT_JSON="shared_baseline_sky130.json"
        ;;
    dual)
        FIXTURE="${repo_root}/benchmarks/halo_fft64_reference"
        SYNTH_TPL="synth/dual_synth.ys"
        NETLIST="${RESULTS}/netlists/dual_ppa_synth.v"
        SDC="${ABS_PHYS}/constraints/dual_baseline.sdc"
        ACT_TB="${ABS_PHYS}/activity/dual_activity_tb.sv"
        RTL_WRAPPER="${ABS_PHYS}/rtl/peweaver_ppa_dual_fft.v"
        TB_TOP="peweaver_dual_activity_tb"
        LOG_TAG="_dual"
        RPT_TAG="_dual"
        VCD_TAG="_dual"
        ACTIVITY_SOURCES=("${RTL_WRAPPER}" \
            "${ABS_PHYS}/rtl/peweaver_ppa_fft64.v" \
            "${ABS_PHYS}/rtl/peweaver_ppa_fft128.v" \
            "${repo_root}/benchmarks/halo_fft64_reference/peweaver_halo_fft64_reference.v" \
            "${ABS_PHYS}/rtl/dual/halo_fft128_wrapper.v" \
            "${repo_root}/third_party/r22sdf/FFT64.v" \
            "${repo_root}/third_party/r22sdf/SdfUnit.v" \
            "${repo_root}/third_party/r22sdf/SdfUnit2.v" \
            "${repo_root}/third_party/r22sdf/Butterfly.v" \
            "${repo_root}/third_party/r22sdf/DelayBuffer.v" \
            "${repo_root}/third_party/r22sdf/Multiply.v" \
            "${repo_root}/third_party/r22sdf/Twiddle64.v" \
            "${ABS_PHYS}/rtl/dual/fft128_core.v" \
            "${ABS_PHYS}/rtl/dual/sdfunit128.v" \
            "${ABS_PHYS}/rtl/dual/twiddle128_core.v")
        SHARED_SOURCES=""
        SHARED_SOURCES=""
        GLS_VVP="${RESULTS}/work/dual_gls.vvp"
        RESULT_JSON="dual_baseline_sky130.json"
        ;;
    dual_b)
        FIXTURE="${repo_root}/benchmarks/halo_fft64_reference"
        SYNTH_TPL="synth/dual_b_synth.ys"
        NETLIST="${RESULTS}/netlists/dual_b_ppa_synth.v"
        SDC="${ABS_PHYS}/constraints/dual_b_baseline.sdc"
        ACT_TB="${ABS_PHYS}/activity/dual_b_activity_tb.sv"
        RTL_WRAPPER="${ABS_PHYS}/rtl/peweaver_ppa_dual_fft_icg.v"
        TB_TOP="peweaver_dual_b_activity_tb"
        LOG_TAG="_dual_b"
        RPT_TAG="_dual_b"
        VCD_TAG="_dual_b"
        ACTIVITY_SOURCES=("${RTL_WRAPPER}" \
            "${ABS_PHYS}/rtl/sky130_icg_blackbox.v" \
            "${ABS_PHYS}/rtl/peweaver_ppa_fft64.v" \
            "${ABS_PHYS}/rtl/peweaver_ppa_fft128.v" \
            "${repo_root}/benchmarks/halo_fft64_reference/peweaver_halo_fft64_reference.v" \
            "${ABS_PHYS}/rtl/dual/halo_fft128_wrapper.v" \
            "${repo_root}/third_party/r22sdf/FFT64.v" \
            "${repo_root}/third_party/r22sdf/SdfUnit.v" \
            "${repo_root}/third_party/r22sdf/SdfUnit2.v" \
            "${repo_root}/third_party/r22sdf/Butterfly.v" \
            "${repo_root}/third_party/r22sdf/DelayBuffer.v" \
            "${repo_root}/third_party/r22sdf/Multiply.v" \
            "${repo_root}/third_party/r22sdf/Twiddle64.v" \
            "${ABS_PHYS}/rtl/dual/fft128_core.v" \
            "${ABS_PHYS}/rtl/dual/sdfunit128.v" \
            "${ABS_PHYS}/rtl/dual/twiddle128_core.v")
        SHARED_SOURCES=""
        GLS_VVP="${RESULTS}/work/dual_b_gls.vvp"
        RESULT_JSON="dual_b_sky130.json"
        ;;
    *) echo "run-physical.sh: unknown PEWEAVER_DESIGN '${DESIGN}'" >&2; exit 2;;
esac
if [[ -n "${PEWEAVER_SYNTH_TPL}" ]]; then
    SYNTH_TPL="${PEWEAVER_SYNTH_TPL}"
    echo "run-physical.sh: ATTRIBUTION OVERRIDE synthesis template -> ${SYNTH_TPL}"
fi

#---------------------------------------------------------------------- stage 1
echo "run-physical.sh: stage 1 synthesis (yosys -> sky130_fd_sc_hd)"
"${PY}" synth/filter_liberty.py "${LIB_TT}" "${RESULTS}/work/lib_${DESIGN}_tt_synth.lib" \
    | tee "${RESULTS}/logs/filter_liberty${LOG_TAG}.log"
sed "s|@LIB_TT@|${RESULTS}/work/lib_${DESIGN}_tt_synth.lib|g" "${SYNTH_TPL}" \
    > "${RESULTS}/work/${DESIGN}_synth_run.ys"
# Route the template's relative results/ output paths to the active
# results directory (safe: "results_repeat/" does not contain "results/")
sed -i "s|\bresults/|${PEWEAVER_RESULTS_DIR}/|g" "${RESULTS}/work/${DESIGN}_synth_run.ys"
"${YOSYS}" -l "${RESULTS}/logs/yosys${LOG_TAG}.log" "${RESULTS}/work/${DESIGN}_synth_run.ys"
[[ -f "${NETLIST}" ]] || { echo "run-physical.sh: synthesis did not produce a netlist" >&2; exit 1; }
cp "${RESULTS}/work/${DESIGN}_synth_run.ys" "${RESULTS}/logs/${DESIGN}_synth_run.ys"

#---------------------------------------------------------------------- stage 2
echo "run-physical.sh: stage 2 activity + golden (RTL reference, then gate-level)"
# RTL reference run: full scenario VCD (also proves the wrapper RTL contract).
# Unique Mdir per run (timestamp suffix prevents stale cache reuse)
RUN_ID="$(date +%Y%m%d_%H%M%S)_$$"
RTL_MDIR="${RESULTS}/work/verilator_rtl${VCD_TAG}_${RUN_ID}"
rm -rf "${RTL_MDIR}"

"${VERILATOR}" --binary --timing --trace --x-assign 0 --x-initial 0 \
    --top-module "${TB_TOP}" \
    --Mdir "${RTL_MDIR}" -Wno-fatal \
    "${ACTIVITY_SOURCES[@]}" \
    "${ACT_TB}" \
    > "${RESULTS}/logs/verilator_rtl${LOG_TAG}_compile.log" 2>&1

# Fail closed: verify the compile produced a binary
RTL_BIN="${RTL_MDIR}/V${TB_TOP}"
[[ -x "${RTL_BIN}" ]] || { echo "run-physical.sh: RTL activity binary missing after compile" >&2; cat "${RESULTS}/logs/verilator_rtl${LOG_TAG}_compile.log" >&2; exit 1; }

# Fail closed: verify the compile log mentions at least one module
if grep -qE "(^|[^0-9])0 modules" "${RESULTS}/logs/verilator_rtl${LOG_TAG}_compile.log" 2>/dev/null; then
    echo "run-physical.sh: FAIL — Verilator compiled 0 modules" >&2
    exit 1
fi
( cd "${FIXTURE}" && "${RTL_BIN}" "+VCD=${RESULTS}/activity/rtl_scenario${VCD_TAG}.vcd" \
    > "${RESULTS}/logs/verilator_rtl${LOG_TAG}_run.log" 2>&1 )
check_activity_log() {
    local log="$1" label="$2"
    grep -q "PEWEAVER_ACTIVITY_DONE" "${log}" \
        || { echo "run-physical.sh: ${label} did not complete successfully" >&2; cat "${log}" >&2; exit 1; }
    if grep -q "PEWEAVER_ACTIVITY_ERROR" "${log}"; then
        echo "run-physical.sh: ${label} reported errors" >&2; cat "${log}" >&2; exit 1
    fi
}
check_activity_log "${RESULTS}/logs/verilator_rtl${LOG_TAG}_run.log" "RTL activity run"

# Gate-level (mapped netlist) run: golden proof of the physical netlist plus
# the two activity traces used for power. GLS uses Icarus Verilog with the
# sky130 FUNCTIONAL models and unit gate delays (the standard OpenLane-style
# GLS recipe; Verilator mishandles the sequential UDP flops).
IV="$(resolve_tool PEWEAVER_IVERILOG iverilog)"
VVP="$(resolve_tool PEWEAVER_VVP vvp)"
[[ -x "${IV}" ]] || { echo "run-physical.sh: iverilog not found" >&2; exit 1; }
[[ -x "${VVP}" ]] || { echo "run-physical.sh: vvp not found" >&2; exit 1; }
echo "run-physical.sh: compiling gate-level simulation model (iverilog, always rebuild)"
( cd "${FIXTURE}" && "${IV}" -g2012 -D FUNCTIONAL -D UNIT_DELAY=#1 \
    -s "${TB_TOP}" -o "${GLS_VVP}" \
    "${NETLIST}" \
    "${PDK_ROOT}/sky130A/libs.ref/sky130_fd_sc_hd/verilog/primitives.v" \
    "${PDK_ROOT}/sky130A/libs.ref/sky130_fd_sc_hd/verilog/sky130_fd_sc_hd.v" \
    "${ACT_TB}" \
    > "${RESULTS}/logs/iverilog_gls${LOG_TAG}_compile.log" 2>&1 )
[[ -s "${GLS_VVP}" ]] || { echo "run-physical.sh: GLS simulation model missing" >&2; exit 1; }
( cd "${FIXTURE}" && "${VVP}" "${GLS_VVP}" \
    "+VCD=${RESULTS}/activity/gls_scenario${VCD_TAG}.vcd" \
    > "${RESULTS}/logs/iverilog_gls_scenario${LOG_TAG}_run.log" 2>&1 )
check_activity_log "${RESULTS}/logs/iverilog_gls_scenario${LOG_TAG}_run.log" "GLS scenario run"
( cd "${FIXTURE}" && "${VVP}" "${GLS_VVP}" \
    "+VCD=${RESULTS}/activity/gls_stream${VCD_TAG}.vcd" "+STREAM_ONLY" "+STREAM_MODE=64" \
    > "${RESULTS}/logs/iverilog_gls_stream${LOG_TAG}_run.log" 2>&1 )
check_activity_log "${RESULTS}/logs/iverilog_gls_stream${LOG_TAG}_run.log" "GLS streaming run"
if [[ "${DESIGN}" == "shared" || "${DESIGN}" == "dual" || "${DESIGN}" == "dual_b" ]]; then
    ( cd "${FIXTURE}" && "${VVP}" "${GLS_VVP}" \
        "+VCD=${RESULTS}/activity/gls_stream_128${VCD_TAG}.vcd" "+STREAM_ONLY" "+STREAM_MODE=128" \
        > "${RESULTS}/logs/iverilog_gls_stream_128${LOG_TAG}_run.log" 2>&1 )
    check_activity_log "${RESULTS}/logs/iverilog_gls_stream_128${LOG_TAG}_run.log" "GLS 128-mode streaming run"
fi
[[ -s "${RESULTS}/activity/gls_scenario${VCD_TAG}.vcd" ]] || { echo "run-physical.sh: GLS scenario VCD missing" >&2; exit 1; }
[[ -s "${RESULTS}/activity/gls_stream${VCD_TAG}.vcd" ]] || { echo "run-physical.sh: GLS streaming VCD missing" >&2; exit 1; }
if [[ "${DESIGN}" == "shared" || "${DESIGN}" == "dual" || "${DESIGN}" == "dual_b" ]]; then
    [[ -s "${RESULTS}/activity/gls_stream_128${VCD_TAG}.vcd" ]] || { echo "run-physical.sh: GLS 128-mode streaming VCD missing" >&2; exit 1; }
fi

# Normalize both VCDs: shift timestamps so the first event is at #0,
# canonicalize simulator wall-clock headers, and validate the clock period.
echo "run-physical.sh: normalizing scenario VCD"
"${PY}" "${ABS_PHYS}/vcd_normalize.py" \
    "${RESULTS}/activity/gls_scenario${VCD_TAG}.vcd" \
    "${RESULTS}/activity/gls_scenario${VCD_TAG}_norm.vcd" \
    --clock "peweaver_${DESIGN}_activity_tb.dut.clock" \
    --period-ps 10000
[[ -s "${RESULTS}/activity/gls_scenario${VCD_TAG}_norm.vcd" ]] || \
    { echo "run-physical.sh: normalized scenario VCD missing" >&2; exit 1; }
echo "run-physical.sh: normalizing streaming VCD"
"${PY}" "${ABS_PHYS}/vcd_normalize.py" \
    "${RESULTS}/activity/gls_stream${VCD_TAG}.vcd" \
    "${RESULTS}/activity/gls_stream${VCD_TAG}_norm.vcd" \
    --clock "peweaver_${DESIGN}_activity_tb.dut.clock" \
    --period-ps 10000
[[ -s "${RESULTS}/activity/gls_stream${VCD_TAG}_norm.vcd" ]] || \
    { echo "run-physical.sh: normalized streaming VCD missing" >&2; exit 1; }
if [[ "${DESIGN}" == "shared" || "${DESIGN}" == "dual" || "${DESIGN}" == "dual_b" ]]; then
    echo "run-physical.sh: normalizing 128-mode streaming VCD"
    "${PY}" "${ABS_PHYS}/vcd_normalize.py" \
        "${RESULTS}/activity/gls_stream_128${VCD_TAG}.vcd" \
        "${RESULTS}/activity/gls_stream_128${VCD_TAG}_norm.vcd" \
        --clock "peweaver_${DESIGN}_activity_tb.dut.clock" \
        --period-ps 10000
    [[ -s "${RESULTS}/activity/gls_stream_128${VCD_TAG}_norm.vcd" ]] || \
        { echo "run-physical.sh: normalized shared 128-mode streaming VCD missing" >&2; exit 1; }
fi
echo "run-physical.sh: scenario and streaming VCDs normalized and validated"

#---------------------------------------------------------------------- stage 3
echo "run-physical.sh: stage 3a OpenROAD frontend (floorplan/place/CTS/global route)"
export LIB_TT TECH_LEF CELL_LEF NETLIST OUT_DIR
export SDC RPT_TAG
export PDK_DIR="${ABS_PHYS}/pdk/sky130hd"
export ODB_PATH="${RESULTS}/work/${DESIGN}_frontend.odb"
export SPEF_OUT="${RESULTS}/spef/${DESIGN}_baseline.spef"
export DEF_OUT="${RESULTS}/def/${DESIGN}_baseline.def"
export TAP_CELL_NAME="sky130_fd_sc_hd__tapvpwrvgnd_1"
export MIN_ROUTING_LAYER="met1" MAX_ROUTING_LAYER="met5"
export MIN_CLK_ROUTING_LAYER="met3" MAX_CLK_ROUTING_LAYER="met5"
export VCD_SCENARIO="${RESULTS}/activity/gls_scenario${VCD_TAG}_norm.vcd"
export VCD_STREAM="${RESULTS}/activity/gls_stream${VCD_TAG}_norm.vcd"
if [[ "${DESIGN}" == "shared" || "${DESIGN}" == "dual" || "${DESIGN}" == "dual_b" ]]; then
    export VCD_STREAM_128="${RESULTS}/activity/gls_stream_128${VCD_TAG}_norm.vcd"
else
    unset VCD_STREAM_128 || true
fi
if [[ "${DESIGN}" == "shared" ]]; then
    export TOP_MODULE="peweaver_ppa_shared_fft"
elif [[ "${DESIGN}" == "dual" ]]; then
    export TOP_MODULE="peweaver_ppa_dual_fft"
elif [[ "${DESIGN}" == "dual_b" ]]; then
    export TOP_MODULE="peweaver_ppa_dual_fft_icg"
else
    export TOP_MODULE="peweaver_ppa_${DESIGN}"
fi
export VCD_SCOPE="peweaver_${DESIGN}_activity_tb/dut"
FRONTEND_TPL="openroad/fft64_frontend.tcl"
if [[ "${DESIGN}" == "dual" || "${DESIGN}" == "dual_b" ]]; then
    FRONTEND_TPL="openroad/dual_d050_frontend.tcl"
fi
if [[ -n "${PEWEAVER_FRONTEND_TPL}" ]]; then
    FRONTEND_TPL="${PEWEAVER_FRONTEND_TPL}"
    echo "run-physical.sh: ATTRIBUTION OVERRIDE frontend template -> ${FRONTEND_TPL}"
fi
"${OPENROAD}" -no_init -exit "${FRONTEND_TPL}" 2>&1 | tee "${RESULTS}/logs/openroad_frontend${LOG_TAG}.log"
grep -q "PEWEAVER_PHYSICAL_FRONTEND_DONE" "${RESULTS}/logs/openroad_frontend${LOG_TAG}.log" \
    || { echo "run-physical.sh: OpenROAD frontend did not complete" >&2; exit 1; }
[[ -f "${RESULTS}/work/${DESIGN}_frontend.odb" ]] || { echo "run-physical.sh: frontend ODB checkpoint missing" >&2; exit 1; }

echo "run-physical.sh: stage 3b OpenROAD backend (detailed route/extract/STA/power)"
BACKEND_TPL="openroad/fft64_backend.tcl"
if [[ -n "${PEWEAVER_BACKEND_TPL}" ]]; then
    BACKEND_TPL="${PEWEAVER_BACKEND_TPL}"
    echo "run-physical.sh: ATTRIBUTION OVERRIDE backend template -> ${BACKEND_TPL}"
fi
"${OPENROAD}" -no_init -exit "${BACKEND_TPL}" 2>&1 | tee "${RESULTS}/logs/openroad_backend${LOG_TAG}.log"
grep -q "PEWEAVER_PHYSICAL_FLOW_DONE" "${RESULTS}/logs/openroad_backend${LOG_TAG}.log" \
    || { echo "run-physical.sh: OpenROAD backend did not complete" >&2; exit 1; }
if grep -q "STA-1452" "${RESULTS}/logs/openroad_backend${LOG_TAG}.log"; then
    echo "run-physical.sh: FAIL — backend log contains STA-1452 (clock period mismatch)" >&2
    grep "STA-1452" "${RESULTS}/logs/openroad_backend${LOG_TAG}.log" >&2
    exit 1
fi
[[ -f "${OUT_DIR}/power_streaming${RPT_TAG}.rpt" ]] || { echo "run-physical.sh: streaming power report missing" >&2; exit 1; }
[[ -f "${OUT_DIR}/power_scenario${RPT_TAG}.rpt" ]] || { echo "run-physical.sh: scenario power report missing" >&2; exit 1; }
if [[ "${DESIGN}" == "shared" || "${DESIGN}" == "dual" || "${DESIGN}" == "dual_b" ]]; then
    [[ -f "${OUT_DIR}/power_streaming_128${RPT_TAG}.rpt" ]] || { echo "run-physical.sh: shared 128-mode streaming power report missing" >&2; exit 1; }
fi

#---------------------------------------------------------------------- stage 4
if [[ "${PEWEAVER_RESULTS_DIR}" != "results" ]]; then
    echo "run-physical.sh: ATTRIBUTION flow — skipping frozen result assembly"
else
    echo "run-physical.sh: stage 4 result assembly"
    "${PY}" "${ABS_PHYS}/assemble_results.py" --design "${DESIGN}" \
        --synth-template "${SYNTH_TPL}" \
        --frontend-template "${FRONTEND_TPL}" \
        --backend-template "${BACKEND_TPL}"
fi
echo "run-physical.sh: DONE — results/${RESULT_JSON}"
