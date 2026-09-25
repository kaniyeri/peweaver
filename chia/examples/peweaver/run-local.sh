#!/usr/bin/env bash
# PEWeaver local runner: unit tests, then the native-formal equivalence gate.
# Yosys is resolved from PEWEAVER_YOSYS, the oss-cad-suite checkout, or PATH.

set -Eeuo pipefail

script_path="${BASH_SOURCE[0]}"
script_dir="$(cd -- "$(dirname -- "$script_path")" && pwd -P)"
repo_root="$(cd -- "${script_dir}/../.." && pwd -P)"

die() {
    printf 'run-local.sh: %s\n' "$*" >&2
    exit 1
}

is_executable() {
    [[ -x "$1" ]] || command -v "$1" >/dev/null 2>&1
}

python_cmd=()
if [[ -n "${PEWEAVER_PYTHON:-}" ]]; then
    python_cmd=("${PEWEAVER_PYTHON}")
elif command -v python3 >/dev/null 2>&1; then
    python_cmd=(python3)
else
    die "no Python interpreter found (set PEWEAVER_PYTHON or install python3)"
fi
is_executable "${python_cmd[0]}" || die "Python interpreter is not executable: ${python_cmd[0]}"

yosys=""
if [[ -n "${PEWEAVER_YOSYS:-}" ]]; then
    yosys="${PEWEAVER_YOSYS}"
elif is_executable "${repo_root}/../toolchains/oss-cad-suite/bin/yosys"; then
    yosys="${repo_root}/../toolchains/oss-cad-suite/bin/yosys"
elif command -v yosys >/dev/null 2>&1; then
    yosys="$(command -v yosys)"
elif command -v yowasp-yosys >/dev/null 2>&1; then
    yosys="$(command -v yowasp-yosys)"
else
    die "no Yosys executable found (set PEWEAVER_YOSYS, install oss-cad-suite, or add yosys to PATH)"
fi
is_executable "${yosys}" || die "Yosys is not executable: ${yosys}"
export PEWEAVER_YOSYS="${yosys}"

verilator=""
if [[ -n "${PEWEAVER_VERILATOR:-}" ]]; then
    verilator="${PEWEAVER_VERILATOR}"
elif is_executable "${repo_root}/../toolchains/oss-cad-suite/bin/verilator"; then
    verilator="${repo_root}/../toolchains/oss-cad-suite/bin/verilator"
elif command -v verilator >/dev/null 2>&1; then
    verilator="$(command -v verilator)"
else
    die "no Verilator executable found (set PEWEAVER_VERILATOR, install oss-cad-suite, or add verilator to PATH)"
fi
is_executable "${verilator}" || die "Verilator is not executable: ${verilator}"
export PEWEAVER_VERILATOR="${verilator}"

cd -- "${repo_root}"
mkdir -p examples/peweaver/results

printf 'run-local.sh: python=%s\n' "${python_cmd[*]}"
printf 'run-local.sh: yosys=%s\n' "${yosys}"
printf 'run-local.sh: verilator=%s\n' "${verilator}"

printf 'run-local.sh: running unit tests\n'
"${python_cmd[@]}" -m unittest discover -s examples/peweaver -p 'test_*.py'

printf 'run-local.sh: running differential simulation gate\n'
"${python_cmd[@]}" examples/peweaver/simulation_runner.py \
    examples/peweaver/benchmarks \
    --json examples/peweaver/results/native-simulation.json

printf 'run-local.sh: running generic-cell synthesis proxy\n'
"${python_cmd[@]}" examples/peweaver/synthesis_runner.py \
    examples/peweaver/benchmarks \
    --json examples/peweaver/results/native-synthesis.json

printf 'run-local.sh: running equivalence gate\n'
"${python_cmd[@]}" examples/peweaver/equivalence_runner.py \
    examples/peweaver/benchmarks \
    --json examples/peweaver/results/native-formal.json
