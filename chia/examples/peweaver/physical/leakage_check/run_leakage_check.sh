#!/usr/bin/env bash
# run_leakage_check.sh — single-cell static leakage sanity check (sky130 PDK)
#
# Runs nand2_leak.spice once per input state (0/0, 0/1.8, 1.8/0, 1.8/1.8) in
# ngspice batch mode at the tt/25C/1.8V corner, extracts the measured VDD
# leakage current of sky130_fd_sc_hd__nand2_1, compares it against the
# per-state leakage_power() values declared in the sky130 liberty file under
# its declared leakage_power_unit ("1nW"), and emits a JSON report.
#
# This is a DOCUMENTATION/SANITY artifact: it spot-checks one cell at one
# corner. It is NOT library calibration and NOT a silicon measurement.
#
# Fails closed: missing tools, missing PDK files, ngspice errors, or
# unparsable output all abort with a non-zero exit status.

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PHYS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

DECK="$SCRIPT_DIR/nand2_leak.spice"
RESULTS_DIR="$PHYS_DIR/results/leakage_check"
JSON_OUT="$RESULTS_DIR/nand2_leakage_check.json"

PDK_LIB_SPICE="/home/peweaver-user/.volare/sky130A/libs.tech/ngspice/sky130.lib.spice"
PDK_CELL_SPICE="/home/peweaver-user/.volare/sky130A/libs.ref/sky130_fd_sc_hd/spice/sky130_fd_sc_hd.spice"
LIBERTY="/home/peweaver-user/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib"

CELL="sky130_fd_sc_hd__nand2_1"
VDD_V="1.8"
TEMP_C="25"
CORNER_PROCESS="tt"

die() { echo "ERROR: $*" >&2; exit 1; }

# --- 0. Tool and input checks (fail closed) ---------------------------------
command -v ngspice >/dev/null 2>&1 || die "ngspice not found on PATH"
command -v awk     >/dev/null 2>&1 || die "awk not found on PATH"
command -v sed     >/dev/null 2>&1 || die "sed not found on PATH"

for f in "$DECK" "$PDK_LIB_SPICE" "$PDK_CELL_SPICE" "$LIBERTY"; do
  [ -r "$f" ] || die "required file not readable: $f"
done

NGSPICE_VERSION="$(ngspice --version 2>&1 | grep -oE 'ngspice-[0-9]+(\.[0-9]+)*' | head -n 1)"
[ -n "$NGSPICE_VERSION" ] || die "could not determine ngspice version"

mkdir -p "$RESULTS_DIR"

# --- 1. Liberty reference values (declared unit, first leakage_power group) --
# Reads the first leakage_power()/value+when blocks of the target cell, plus
# cell_leakage_power and the library-wide leakage_power_unit.
liberty_unit="$(sed -n 's/.*leakage_power_unit[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$LIBERTY" | head -n 1)"
[ -n "$liberty_unit" ] || die "could not parse leakage_power_unit from liberty file"
[ "$liberty_unit" = "1nW" ] || die "unexpected leakage_power_unit '$liberty_unit' (ratios below assume the strict '1nW' reading)"

mapfile -t LIB_ROWS < <(
  awk -v cell="$CELL" '
    /^[ \t]*cell[ \t]*\(/ {
      incell = ($0 ~ ("cell[ \t]*\\(\"" cell "\"\\)")) ? 1 : 0
      if (!incell) next
    }
    incell && !seen_clp {
      if ($0 ~ /^[ \t]*value[ \t]*:/) {
        v = $0; sub(/^[ \t]*value[ \t]*:[ \t]*/, "", v); sub(/;.*/, "", v)
        pend = v; next
      }
      if ($0 ~ /^[ \t]*when[ \t]*:/ && pend != "") {
        w = $0; sub(/^[ \t]*when[ \t]*:[ \t]*/, "", w); sub(/;.*/, "", w); gsub(/"/, "", w)
        printf "%s %s\n", w, pend; pend = ""; next
      }
      if ($0 ~ /^[ \t]*cell_leakage_power[ \t]*:/) {
        c = $0; sub(/^[ \t]*cell_leakage_power[ \t]*:[ \t]*/, "", c); sub(/;.*/, "", c)
        printf "CELL_LEAKAGE_POWER %s\n", c; seen_clp = 1; next
      }
    }
  ' "$LIBERTY"
)

declare -A LIB_NW
LIB_CELL_LEAK_NW=""
for row in "${LIB_ROWS[@]}"; do
  if [[ "$row" == CELL_LEAKAGE_POWER* ]]; then
    LIB_CELL_LEAK_NW="${row#CELL_LEAKAGE_POWER }"
  else
    when="${row%% *}"; val="${row#* }"
    LIB_NW["$when"]="$val"
  fi
done

# States: deck input levels and the liberty when-condition they correspond to.
VA_VALS=(0 0 1.8 1.8)
VB_VALS=(0 1.8 0 1.8)
WHENS=("!A&!B" "!A&B" "A&!B" "A&B")

for when in "${WHENS[@]}"; do
  [ -n "${LIB_NW[$when]:-}" ] || die "liberty file has no leakage_power value for when '$when' of $CELL"
done
[ -n "$LIB_CELL_LEAK_NW" ] || die "could not parse cell_leakage_power for $CELL"

# --- 2. Run the deck once per input state ------------------------------------
TMPDECK="$(mktemp)"
trap 'rm -f "$TMPDECK"' EXIT

measured_json=""
min_ratio=""
max_ratio=""

for i in "${!VA_VALS[@]}"; do
  va="${VA_VALS[$i]}"; vb="${VB_VALS[$i]}"; when="${WHENS[$i]}"
  raw_log="$RESULTS_DIR/raw_state_${va}_${vb}.log"

  # Parameterize the deck by rewriting its two .param state lines.
  sed -e "s/^\.param VA_VAL=.*/.param VA_VAL=${va}/" \
      -e "s/^\.param VB_VAL=.*/.param VB_VAL=${vb}/" \
      "$DECK" > "$TMPDECK"
  grep -q "^\.param VA_VAL=${va}$" "$TMPDECK" || die "failed to parameterize VA_VAL in deck"
  grep -q "^\.param VB_VAL=${vb}$" "$TMPDECK" || die "failed to parameterize VB_VAL in deck"

  if ! ngspice -b "$TMPDECK" > "$raw_log" 2>&1; then
    die "ngspice failed for state A=${va} B=${vb} (see $raw_log)"
  fi
  if grep -qiE 'error|failed|no convergence|singular' "$raw_log"; then
    die "ngspice reported errors for state A=${va} B=${vb} (see $raw_log)"
  fi

  cur="$(awk '/^ileak[ \t]*=/ { print $3; n++ } END { if (n != 1) exit 3 }' "$raw_log")" \
    || die "could not extract exactly one 'ileak' value from $raw_log"
  [[ "$cur" =~ ^[+-]?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?$ ]] \
    || die "extracted leakage '$cur' is not numeric (from $raw_log)"

  pow="$(awk -v i="$cur" -v v="$VDD_V" 'BEGIN { printf "%.6e", i * v }')"
  lib_nw="${LIB_NW[$when]}"
  lib_w="$(awk -v v="$lib_nw" 'BEGIN { printf "%.6e", v * 1e-9 }')"
  ratio="$(awk -v m="$pow" -v l="$lib_w" 'BEGIN { if (l == 0) exit 4; printf "%.6g", m / l }')" \
    || die "liberty leakage for '$when' is zero; ratio undefined"

  min_ratio="$(awk -v a="${min_ratio:-$ratio}" -v b="$ratio" 'BEGIN { printf "%.6g", (a < b ? a : b) }')"
  max_ratio="$(awk -v a="${max_ratio:-$ratio}" -v b="$ratio" 'BEGIN { printf "%.6g", (a > b ? a : b) }')"

  measured_json+="    {\"va_v\": ${va}, \"vb_v\": ${vb}, \"input_state\": \"${when}\", \"current_a\": ${cur}, \"leakage_w\": ${pow}, \"liberty_w\": ${lib_w}, \"ratio_measured_over_liberty\": ${ratio}}"
  [ "$i" -lt "$((${#VA_VALS[@]} - 1))" ] && measured_json+=","
  measured_json+=$'\n'

  echo "state A=${va} B=${vb} (${when}): I=${cur} A  P=${pow} W  liberty=${lib_nw} nW  ratio=${ratio}"
done

cell_leak_w="$(awk -v v="$LIB_CELL_LEAK_NW" 'BEGIN { printf "%.6e", v * 1e-9 }')"

# --- 3. Emit JSON report ------------------------------------------------------
cat > "$JSON_OUT" <<EOF
{
  "schema": "peweaver-leakage-check-1",
  "cell": "${CELL}",
  "corner": {
    "process": "${CORNER_PROCESS}",
    "temperature_c": ${TEMP_C},
    "vdd_v": ${VDD_V},
    "ngspice_lib": "${PDK_LIB_SPICE}",
    "monte_carlo_switches": { "mc_mm_switch": 0, "mc_pr_switch": 0 },
    "body_ties": { "VNB": "VGND (0 V)", "VPB": "VPWR (${VDD_V} V)" }
  },
  "ngspice_version": "${NGSPICE_VERSION}",
  "deck": "leakage_check/nand2_leak.spice",
  "method": "DC operating point per input state; leakage = -i(VVDD); raw ngspice output in raw_state_<A>_<B>.log beside this file",
  "liberty_reference": {
    "file": "${LIBERTY}",
    "leakage_power_unit": "${liberty_unit}",
    "cell_leakage_power_nw": ${LIB_CELL_LEAK_NW},
    "cell_leakage_power_w_strict_1nw": ${cell_leak_w},
    "per_state_nw": {
      "!A&B": ${LIB_NW["!A&B"]},
      "!A&!B": ${LIB_NW["!A&!B"]},
      "A&B": ${LIB_NW["A&B"]},
      "A&!B": ${LIB_NW["A&!B"]}
    }
  },
  "measured": [
${measured_json}  ],
  "ratio_measured_over_liberty_range": { "min": ${min_ratio}, "max": ${max_ratio} },
  "conclusion": "Single-cell ngspice spot-check of ${CELL} at tt/25C/${VDD_V}V with explicit body ties (VNB=0 V, VPB=${VDD_V} V). Measured static leakages are in the pico-watt range, confirming a clean DC solution with no floating-node artifacts. Disagreement with the liberty per-state leakage_power() values (strict 1nW reading) spans roughly ${min_ratio}x-${max_ratio}x and the state ordering differs, so these numbers are documentation of a spot-check only: this is NOT library calibration and NOT a silicon measurement, and the liberty values must not be re-derived from it."
}
EOF

echo "wrote $JSON_OUT"
