#!/usr/bin/env bash
# PEWeaver Linux bootstrap: native RTL tools, with optional CHIA installation.
# The script is safe to invoke with sudo; only apt operations run as root.

set -Eeuo pipefail

script_path="${BASH_SOURCE[0]}"
script_dir="$(cd -- "$(dirname -- "$script_path")" && pwd -P)"
repo_root="$(cd -- "${script_dir}/../.." && pwd -P)"
tool_root="${PEWEAVER_TOOL_ROOT:-$(cd -- "${repo_root}/.." && pwd -P)/toolchains}"
download_root="${tool_root}/downloads"
mini_root="${tool_root}/miniforge3"
cad_root="${tool_root}/oss-cad-suite"

MINIFORGE_URL="https://github.com/conda-forge/miniforge/releases/download/26.3.2-2/Miniforge3-26.3.2-2-Linux-x86_64.sh"
MINIFORGE_SHA256="42260ffe3830fb953d5eee1bbb32229ff06aa7c3833c1ed7a9a0420a95685d94"
MINIFORGE_ARCHIVE="${download_root}/Miniforge3-26.3.2-2-Linux-x86_64.sh"

CAD_URL="https://github.com/YosysHQ/oss-cad-suite-build/releases/download/2026-08-28/oss-cad-suite-linux-x64-20260828.tgz"
CAD_SHA256="a7f1b795aa10271ff8a0f96de0e5ee77ac9df86b71808cbe506159cb8117eed1"
CAD_ARCHIVE="${download_root}/oss-cad-suite-linux-x64-20260828.tgz"

die() {
    printf 'bootstrap-linux.sh: %s\n' "$*" >&2
    exit 1
}

install_chia=0
case "${1:-}" in
    "") ;;
    --tools-only) ;;
    --with-chia) install_chia=1 ;;
    --help|-h)
        printf 'Usage: %s [--tools-only|--with-chia]\n' "${script_path}"
        printf '  --tools-only  install native RTL/formal tools only (default)\n'
        printf '  --with-chia   additionally install Miniforge Python 3.10.19 and CHIA\n'
        exit 0
        ;;
    *) die "unknown option: $1 (use --help)" ;;
esac

# If called as `sudo bash ...`, re-enter as the invoking user so conda, pip,
# and the checkout remain user-owned. The re-entry uses the same exact script.
if [[ "${EUID}" -eq 0 ]]; then
    [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != root ]] || \
        die "run as your normal user; the script calls sudo for apt itself"
    target_home="$(getent passwd "${SUDO_USER}" | cut -d: -f6)"
    [[ -n "${target_home}" && -d "${target_home}" ]] || die "cannot resolve SUDO_USER home"
    exec runuser -u "${SUDO_USER}" -- env HOME="${target_home}" \
        PEWEAVER_BOOTSTRAP_REENTERED=1 PEWEAVER_TOOL_ROOT="${tool_root}" \
        bash "${script_path}" "$@"
fi

command -v sudo >/dev/null 2>&1 || die "sudo is required for host package installation"
command -v curl >/dev/null 2>&1 || die "curl is required; install it before rerunning"
command -v sha256sum >/dev/null 2>&1 || die "sha256sum is required; install coreutils"
command -v tar >/dev/null 2>&1 || die "tar is required; install tar"

printf 'Repository: %s\nTool root:  %s\n' "${repo_root}" "${tool_root}"
if [[ "${install_chia}" -eq 1 ]]; then
    printf 'Mode:       native RTL tools + CHIA\n'
else
    printf 'Mode:       native RTL tools only (CHIA deferred)\n'
fi

sudo -v
sudo apt-get update
sudo apt-get install -y cmake ninja-build graphviz jq ca-certificates curl

mkdir -p "${download_root}"

fetch_verified() {
    local url="$1"
    local expected="$2"
    local output="$3"
    if [[ -f "${output}" ]] && printf '%s  %s\n' "${expected}" "${output}" | sha256sum -c --status; then
        printf 'Verified existing %s\n' "${output}"
        return
    fi
    printf 'Downloading %s\n' "${url}"
    curl --fail --location --retry 3 --retry-all-errors --progress-bar "${url}" -o "${output}"
    printf '%s  %s\n' "${expected}" "${output}" | sha256sum -c -
}

if [[ "${install_chia}" -eq 1 ]]; then
    fetch_verified "${MINIFORGE_URL}" "${MINIFORGE_SHA256}" "${MINIFORGE_ARCHIVE}"
    if [[ ! -x "${mini_root}/bin/conda" ]]; then
        # The Miniforge installer rejects any pre-existing target, including
        # an empty directory left by an interrupted install. Preserve a
        # non-working target by moving it aside rather than deleting data.
        if [[ -e "${mini_root}" ]]; then
            incomplete_root="${mini_root}.incomplete.$(date +%Y%m%d%H%M%S)"
            mv -- "${mini_root}" "${incomplete_root}"
            printf 'Moved incomplete Miniforge target to %s\n' "${incomplete_root}"
        fi
        bash "${MINIFORGE_ARCHIVE}" -b -p "${mini_root}"
    fi

    conda_exe="${mini_root}/bin/conda"
    [[ -x "${conda_exe}" ]] || die "Miniforge installation did not produce ${conda_exe}"
    pip_cache="${tool_root}/pip-cache"
    mkdir -p "${pip_cache}"
    export PIP_CACHE_DIR="${pip_cache}"

    if ! "${conda_exe}" env list | awk '{print $1}' | rg -qx 'chia_env'; then
        "${conda_exe}" create -n chia_env python=3.10.19 -y
    fi
    "${conda_exe}" run --no-capture-output -n chia_env python --version
    "${conda_exe}" run --no-capture-output -n chia_env python -m pip install \
        --disable-pip-version-check --no-input --progress-bar on -U pip
    "${conda_exe}" run --no-capture-output -n chia_env python -m pip install \
        --disable-pip-version-check --no-input --progress-bar on -e "${repo_root}[test]"
fi

fetch_verified "${CAD_URL}" "${CAD_SHA256}" "${CAD_ARCHIVE}"
if [[ ! -x "${cad_root}/bin/yosys" ]]; then
    tar -xzf "${CAD_ARCHIVE}" -C "${tool_root}"
fi
[[ -x "${cad_root}/bin/yosys" ]] || die "OSS CAD Suite extraction did not produce ${cad_root}/bin/yosys"

cad_bin="${cad_root}/bin"
export PATH="${cad_bin}:${PATH}"
export PEWEAVER_YOSYS="${cad_bin}/yosys"

printf '\nTool versions:\n'
if [[ "${install_chia}" -eq 1 ]]; then
    printf 'python:    '
    "${conda_exe}" run --no-capture-output -n chia_env python --version
    printf 'chia:      '
    "${conda_exe}" run --no-capture-output -n chia_env chia --help >/dev/null && \
        "${conda_exe}" run --no-capture-output -n chia_env python -c 'import importlib.metadata; print(importlib.metadata.version("chialoops"))'
else
    printf 'python:    '; python3 --version
    printf 'chia:      deferred (rerun with --with-chia)\n'
fi
printf 'yosys:     '
yosys -V | head -n 1
printf 'verilator: '
verilator --version | head -n 1
printf 'iverilog:  '
iverilog -V 2>&1 | head -n 1
printf 'sby:       '
if command -v sby >/dev/null 2>&1; then command -v sby; else printf 'missing\n'; fi
printf 'cmake:     '; cmake --version | head -n 1
printf 'ninja:     '; ninja --version
printf 'graphviz:  '; dot -V 2>&1 | head -n 1
printf 'jq:        '; jq --version

lock_path="${repo_root}/examples/peweaver/toolchain-lock.json"
if [[ "${install_chia}" -eq 1 ]]; then
    lock_python=("${conda_exe}" run --no-capture-output -n chia_env python)
else
    lock_python=(python3)
fi
"${lock_python[@]}" - "${lock_path}" "${repo_root}" "${mini_root}" "${cad_root}" "${install_chia}" <<'PY'
import json
import pathlib
import platform
import subprocess
import sys

lock_path, repo_root, mini_root, cad_root = map(pathlib.Path, sys.argv[1:5])
install_chia = sys.argv[5] == "1"

def version(command, *args):
    try:
        proc = subprocess.run([str(command), *args], capture_output=True, text=True, check=False)
    except OSError as exc:
        return f"unavailable: {exc}"
    text = (proc.stdout or proc.stderr).strip().splitlines()
    return text[0] if text else f"exit {proc.returncode}"

data = {
    "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()},
    "repository": str(repo_root),
    "python": version(sys.executable, "--version"),
    "chia": version(sys.executable, "-c", "import importlib.metadata; print(importlib.metadata.version('chialoops'))") if install_chia else "deferred",
    "toolchains": {
        "miniforge": {"path": str(mini_root), "release": "26.3.2-2", "sha256": "42260ffe3830fb953d5eee1bbb32229ff06aa7c3833c1ed7a9a0420a95685d94", "url": "https://github.com/conda-forge/miniforge/releases/download/26.3.2-2/Miniforge3-26.3.2-2-Linux-x86_64.sh"},
        "oss_cad_suite": {"path": str(cad_root), "release": "2026-08-28", "sha256": "a7f1b795aa10271ff8a0f96de0e5ee77ac9df86b71808cbe506159cb8117eed1", "url": "https://github.com/YosysHQ/oss-cad-suite-build/releases/download/2026-08-28/oss-cad-suite-linux-x64-20260828.tgz"},
    },
    "tools": {
        "yosys": version(cad_root / "bin/yosys", "-V"),
        "verilator": version(cad_root / "bin/verilator", "--version"),
        "iverilog": version(cad_root / "bin/iverilog", "-V"),
        "sby": str(cad_root / "bin/sby"),
        "cmake": version("cmake", "--version"),
        "ninja": version("ninja", "--version"),
        "graphviz": version("dot", "-V"),
        "jq": version("jq", "--version"),
    },
}
lock_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
PY

printf '\nBootstrap complete. In each new shell, use:\n'
printf '  export PATH=%q:$PATH\n' "${cad_bin}"
printf '  export PEWEAVER_YOSYS=%q\n' "${PEWEAVER_YOSYS}"
if [[ "${install_chia}" -eq 1 ]]; then
    printf '  %q run -n chia_env python -m unittest discover -s examples/peweaver -p '\''test_*.py'\''\n' "${conda_exe}"
    printf '  %q run -n chia_env python examples/peweaver/equivalence_runner.py examples/peweaver/benchmarks\n' "${conda_exe}"
else
    printf '  python3 -m unittest discover -s examples/peweaver -p '\''test_*.py'\''\n'
    printf '  python3 examples/peweaver/equivalence_runner.py examples/peweaver/benchmarks\n'
    printf '  (CHIA is deferred; rerun this script with --with-chia when the remote server is ready.)\n'
fi
