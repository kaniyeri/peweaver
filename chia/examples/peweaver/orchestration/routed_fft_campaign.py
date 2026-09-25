"""Bounded PEWeaver campaign with a local model and a remote evaluator.

The model process is deliberately given a tiny staging directory containing a
historical candidate and explicitly curated reference files.  Acceptance is
owned by the remote, model-free functional/physical ladder.  This module is
stdlib-only at import time; network and GCP calls are made only by the
injected transport (or by :class:`GcloudRemoteTransport` when explicitly
used).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Protocol, Sequence

from .model_shim import ModelRequest, ModelResponse, ProviderNeutralModelShim, ShimConfig


REMOTE_BASE = PurePosixPath("/work/peweaver/runs")
REMOTE_SOURCE = PurePosixPath("/work/peweaver/source")
REMOTE_PROJECT = "peweaver-gcp-project"
REMOTE_ZONE = "peweaver-zone"
REMOTE_INSTANCE = "peweaver-vm"
REMOTE_RESULT = PurePosixPath("physical/results/shared_baseline_sky130.json")
REMOTE_CANDIDATE = PurePosixPath("physical/rtl/peweaver_shared_fft.v")
GLS_LOG_NAMES = (
    "physical/results/logs/iverilog_gls_scenario_shared_run.log",
    "physical/results/logs/iverilog_gls_stream_shared_run.log",
    "physical/results/logs/iverilog_gls_stream_128_shared_run.log",
)
OPENROAD_LOG_NAMES = (
    "physical/results/logs/openroad_frontend_shared.log",
    "physical/results/logs/openroad_backend_shared.log",
)

# Toolchain environment for the remote evaluator.  The VM keeps the frozen
# toolchain outside PATH; without these the functional judge and the physical
# flow fail closed.  Keys mirror run-physical.sh's resolve_tool contract.
REMOTE_TOOL_ENV: dict[str, str] = {
    "PATH": "/work/peweaver/toolchains/oss-cad-suite/bin:/usr/local/bin:/usr/bin:/bin",
    "PEWEAVER_YOSYS": "/work/peweaver/toolchains/oss-cad-suite/bin/yosys",
    "PEWEAVER_VERILATOR": "/work/peweaver/toolchains/oss-cad-suite/bin/verilator",
    "PEWEAVER_IVERILOG": "/work/peweaver/toolchains/oss-cad-suite/bin/iverilog",
    "PEWEAVER_VVP": "/work/peweaver/toolchains/oss-cad-suite/bin/vvp",
    "PEWEAVER_OPENROAD": "/work/peweaver/toolchains/openroad/usr/bin/openroad",
    "PEWEAVER_VOLARE_VENV": "/work/peweaver/toolchains/physical-venv",
    "PEWEAVER_PDK_ROOT": "/work/peweaver/toolchains/.volare",
}


class CampaignError(ValueError):
    """A fail-closed campaign or staging violation."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class RemoteTransport(Protocol):
    """Minimal transport used by the evaluator; tests can implement it in memory."""

    def prepare_source(self, run_id: str, remote_source: PurePosixPath) -> Any: ...
    def upload(self, local_path: Path, remote_path: PurePosixPath) -> Any: ...
    def run(self, argv: Sequence[str], *, cwd: PurePosixPath,
            env: Mapping[str, str] | None = None, timeout: float = 180.0) -> Any: ...
    def download(self, remote_path: PurePosixPath, local_path: Path) -> Any: ...


@dataclass(frozen=True)
class RemoteConfig:
    project: str = REMOTE_PROJECT
    zone: str = REMOTE_ZONE
    instance: str = REMOTE_INSTANCE
    base: PurePosixPath = REMOTE_BASE
    source: PurePosixPath = REMOTE_SOURCE


@dataclass(frozen=True)
class StagedCampaign:
    root: Path
    candidate: Path
    protected_hashes: Mapping[str, str]
    context_hash: str
    curated_files: tuple[str, ...] = ()


@dataclass(frozen=True)
class CampaignResult:
    run_id: str
    status: str
    candidate_accepted: bool = False
    turns: tuple[Mapping[str, Any], ...] = ()
    evaluator_results: tuple[Mapping[str, Any], ...] = ()
    artifact_dir: str = ""
    error: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id, "status": self.status,
            "candidate_accepted": self.candidate_accepted,
            "turns": [dict(x) for x in self.turns],
            "evaluator_results": [dict(x) for x in self.evaluator_results],
            "artifact_dir": self.artifact_dir, "error": self.error,
        }


def validate_run_id(run_id: str) -> str:
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", run_id):
        raise CampaignError("invalid run id")
    return run_id


def remote_run_root(run_id: str, config: RemoteConfig | None = None) -> PurePosixPath:
    # The run root is exactly base/<run_id>; run_id is already validated
    # (alnum/underscore/hyphen only, so no traversal is possible).  The
    # stricter _validate_remote_path applies to paths BELOW the root and
    # rejects the root itself by design.
    validate_run_id(run_id)
    cfg = config or RemoteConfig()
    return PurePosixPath(cfg.base) / run_id


def _validate_remote_path(path: PurePosixPath | str, run_id: str, config: RemoteConfig) -> PurePosixPath:
    value = PurePosixPath(path)
    root = PurePosixPath(config.base) / validate_run_id(run_id)
    if not value.is_absolute() or value == root or root not in value.parents:
        raise CampaignError("remote path is outside the per-run directory")
    if any(part in {"", ".", ".."} for part in value.parts):
        raise CampaignError("unsafe remote path")
    if PurePosixPath(config.source) in value.parents or value == config.source:
        raise CampaignError("remote source path is immutable")
    return value


def sha256_file(path: Path) -> str:
    mode = path.lstat().st_mode
    if not stat.S_ISREG(mode):
        raise CampaignError(f"non-regular file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _regular(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except FileNotFoundError:
        return False


def _forbidden_curated_path(path: Path, source_root: Path) -> bool:
    rel = PurePosixPath(path.resolve().relative_to(source_root.resolve()).as_posix())
    parts = set(rel.parts)
    name = path.name.lower()
    if "results" in parts or "vectors" in parts or "fixtures" in parts:
        return True
    if name in {"shared_fft_regression.py", "fft64_oracle.py", "fft128_oracle.py"}:
        return True
    if "activity_tb" in name or name.endswith("_testbench.sv"):
        return True
    return False


def _copy_regular(source: Path, destination: Path) -> None:
    if not _regular(source):
        raise CampaignError(f"curated entry is not a regular file: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    os.chmod(destination, 0o600)


_PROTECTED_DIRS = ("architecture", "references")


def _protected_snapshot(root: Path, candidate: Path) -> dict[str, str]:
    """Hash exactly the curated trees that must stay immutable.

    The candidate is deliberately excluded: a worker is expected to rewrite
    it.  OpenCode's runtime artifacts (XDG config, node_modules, session
    state) created beside the staging tree when opencode is the backend are
    equally excluded -- only curated model inputs are protected.
    """
    root = root.resolve()
    candidate = candidate.resolve()
    result: dict[str, str] = {}
    if not root.is_dir():
        raise CampaignError("staging directory missing")
    for kind in _PROTECTED_DIRS:
        base = root / kind
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                raise CampaignError(f"staged symlink rejected: {relative}")
            if path.is_file():
                result[relative] = sha256_file(path)
    return result


def assert_staged_immutable(staged: StagedCampaign) -> None:
    if not _regular(staged.candidate):
        raise CampaignError("candidate is missing, symlinked, or non-regular")
    current = _protected_snapshot(staged.root, staged.candidate)
    if dict(current) != dict(staged.protected_hashes):
        raise CampaignError("staged reference/task files were mutated")


def stage_campaign(*, source_root: Path, failing_rtl: Path,
                   architecture_files: Sequence[Path] = (),
                   reference_rtl_files: Sequence[Path] = (),
                   staging_root: Path | None = None) -> StagedCampaign:
    """Create a model staging tree from an explicit historical failing RTL."""
    source_root = source_root.resolve()
    failing_rtl = failing_rtl.resolve()
    if not source_root.is_dir() or not _regular(failing_rtl):
        raise CampaignError("source root or historical failing RTL is invalid")
    try:
        failing_rtl.relative_to(source_root)
    except ValueError as exc:
        raise CampaignError("historical RTL must be inside source root") from exc
    if _forbidden_curated_path(failing_rtl, source_root):
        raise CampaignError("historical RTL is a protected evaluator input")

    if staging_root is None:
        staging_root = Path(tempfile.mkdtemp(prefix="peweaver-routed-", dir="/tmp"))
    staging_root = staging_root.resolve()
    try:
        staging_root.relative_to(source_root)
    except ValueError:
        pass
    else:
        raise CampaignError("model staging must be outside the repository/source")
    staging_root.mkdir(parents=True, exist_ok=True)
    os.chmod(staging_root, 0o700)
    candidate = staging_root / "candidate.v"
    _copy_regular(failing_rtl, candidate)

    curated: list[str] = []
    seen: set[Path] = set()
    for kind, entries in (("architecture", architecture_files), ("references", reference_rtl_files)):
        for original in entries:
            path = Path(original).resolve()
            if path in seen:
                raise CampaignError(f"duplicate curated file: {path}")
            seen.add(path)
            try:
                rel = path.relative_to(source_root)
            except ValueError as exc:
                raise CampaignError("curated file must be inside source root") from exc
            if _forbidden_curated_path(path, source_root):
                raise CampaignError(f"protected evaluator input cannot be curated: {rel}")
            destination = staging_root / kind / rel
            _copy_regular(path, destination)
            curated.append((kind + "/" + rel.as_posix()))

    protected = _protected_snapshot(staging_root, candidate)
    context = hashlib.sha256(json.dumps(protected, sort_keys=True).encode()).hexdigest()
    return StagedCampaign(staging_root, candidate, protected, context, tuple(curated))


_ANTI_CHEAT_PATTERNS = (
    (re.compile(r"\$system\b|\$readmem(?:h|b)?\b", re.I), "system or readmem I/O"),
    (re.compile(r"\$(?:fopen|fread|fwrite|fscanf|fclose)\b", re.I), "file I/O"),
    (re.compile(r"\b(?:DPI|PLI)\b|import\s+\"DPI-C\"", re.I), "DPI/PLI"),
    (re.compile(r"\$(?:test|value)\$plusargs\b|\+\w+", re.I), "plusargs"),
    (re.compile(r"\b(?:ifdef|ifndef|elsif|translate_off|translate_on)\b", re.I), "simulation conditional"),
    (re.compile(r"\b(?:initial|final)\b", re.I), "unexpected initial/final block"),
    (re.compile(r"\b(?:tb|testbench|uut|dut)\s*\.", re.I), "hierarchical testbench reference"),
)


def static_candidate_errors(candidate: Path) -> list[str]:
    """Return static anti-cheat violations; no candidate is uploaded on error.

    Patterns are evaluated against the candidate with comments and string
    literals removed: prose like "final radix-2 stage" in a comment must not
    reject a legitimate candidate, and parameter passing such as
    ``module m #(parameter W = 8)`` or ``u #(.W(8))`` is RTL, not a
    simulation delay.  Real constructs (``$readmemh``, ``initial`` blocks,
    ``#10`` delays, plusargs, ...) remain rejected wherever they appear in
    actual code.
    """
    if not _regular(candidate):
        return ["candidate is not a regular file"]
    try:
        text = candidate.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return [f"candidate unreadable: {type(exc).__name__}"]
    if not text.strip():
        return ["candidate is empty"]
    code = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    code = re.sub(r"//[^\n]*", " ", code)
    code = re.sub(r'"(?:[^"\\]|\\.)*"', " ", code)
    errors: list[str] = []
    for pattern, label in _ANTI_CHEAT_PATTERNS:
        if pattern.search(code):
            errors.append(label)
    # A Verilog timescale is harmless; every other preprocessor delay marker
    # is rejected, including delays hidden in macros.  Parameter-passing
    # headers/instantiations are neutralized before the delay scan.
    without_timescale = re.sub(r"`timescale[^\n]*", "", code, flags=re.I)
    without_params = re.sub(r"#\s*\(\s*(?:\.|parameter\b|localparam\b)", "PARAMS(",
                            without_timescale)
    if re.search(r"#\s*(?:\d|\(|\w+)", without_params):
        errors.append("simulation delay")
    return errors


def extract_candidate_verilog(text: str) -> str | None:
    """Extract a complete candidate file from a model response.

    Prefers a fenced ``verilog``/``systemverilog`` code block that contains a
    module definition; falls back to unlabeled fences, then to raw text when
    the model replied with bare Verilog.  As a last resort an UNCLOSED fence
    is salvaged (a truncated file will fail the judge, which is better
    information for the next turn than discarding the attempt).  Returns
    None when no plausible candidate is present.
    """
    if not text:
        return None
    blocks = re.findall(r"```(?:[a-zA-Z]*verilog[a-zA-Z]*|[sS][vV])\s*\n(.*?)```",
                        text, flags=re.S)
    if not blocks:
        blocks = re.findall(r"```\s*\n(.*?)```", text, flags=re.S)
    for block in blocks:
        if re.search(r"\bmodule\b", block):
            return block.strip() + "\n"
    if re.search(r"\bmodule\b", text) and "```" not in text:
        return text.strip() + "\n"
    # Unclosed fence salvage: labeled or bare fence opened but never closed
    # (typically MAX_TOKENS truncation mid-file).
    salvage = re.search(r"```(?:[a-zA-Z]*)?\s*\n(.*)$", text, flags=re.S)
    if salvage and re.search(r"\bmodule\b", salvage.group(1)):
        return salvage.group(1).strip() + "\n"
    return None


def apply_worker_output(candidate: Path, output: str, *, provider: str) -> bool:
    """Apply a text-backend worker response to the staged candidate.

    OpenCode workers edit the candidate in place, so their output is never
    re-applied (a stray fenced block in a chat answer must not overwrite a
    deliberate file edit).  Text-only backends return the full file, which is
    written atomically.  Returns True when the candidate was changed.
    """
    if provider == "opencode":
        return False
    extracted = extract_candidate_verilog(output or "")
    if extracted is None:
        return False
    current = candidate.read_text(encoding="utf-8") if candidate.is_file() else ""
    if extracted == current:
        return False
    tmp = candidate.with_name(candidate.name + ".apply-tmp")
    tmp.write_text(extracted, encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, candidate)
    return True


def _as_command_result(value: Any) -> CommandResult:
    if isinstance(value, CommandResult):
        return value
    if isinstance(value, Mapping):
        return CommandResult(int(value.get("returncode", value.get("return_code", 1))),
                             str(value.get("stdout", "") or ""), str(value.get("stderr", "") or ""))
    return CommandResult(int(getattr(value, "returncode", 1)), str(getattr(value, "stdout", "") or ""),
                         str(getattr(value, "stderr", "") or ""))


class GcloudRemoteTransport:
    """Production IAP transport.  It is never constructed or called at import time."""

    def __init__(self, config: RemoteConfig | None = None,
                 runner: Callable[..., Any] | None = None) -> None:
        self.config = config or RemoteConfig()
        self.runner = runner or subprocess.run

    def _ssh(self, command: str, *, timeout: float) -> CommandResult:
        argv = ["gcloud", "compute", "ssh", REMOTE_INSTANCE, "--project", self.config.project,
                "--zone", self.config.zone, "--tunnel-through-iap", "--command", command]
        return _as_command_result(self.runner(argv, capture_output=True, text=True, timeout=timeout, check=False))

    def prepare_source(self, run_id: str, remote_source: PurePosixPath) -> CommandResult:
        root = remote_run_root(run_id, self.config)
        _validate_remote_path(remote_source, run_id, self.config)
        command = (f"mkdir -p -- {shlex.quote(str(root))} {shlex.quote(str(remote_source))} && "
                   f"cp -a -- {shlex.quote(str(self.config.source))}/. {shlex.quote(str(remote_source))}/")
        return self._ssh(command, timeout=600)

    def upload(self, local_path: Path, remote_path: PurePosixPath) -> CommandResult:
        run_id = remote_path.parts[len(REMOTE_BASE.parts)] if len(remote_path.parts) > len(REMOTE_BASE.parts) else ""
        _validate_remote_path(remote_path, run_id, self.config)
        destination = f"{self.config.instance}:{remote_path}"
        argv = ["gcloud", "compute", "scp", str(local_path), destination, "--project", self.config.project,
                "--zone", self.config.zone, "--tunnel-through-iap"]
        return _as_command_result(self.runner(argv, capture_output=True, text=True, timeout=600, check=False))

    def run(self, argv: Sequence[str], *, cwd: PurePosixPath,
            env: Mapping[str, str] | None = None, timeout: float = 180.0) -> CommandResult:
        if not cwd.is_absolute():
            raise CampaignError("remote cwd must be absolute")
        run_id = cwd.parts[len(REMOTE_BASE.parts)] if len(cwd.parts) > len(REMOTE_BASE.parts) else ""
        _validate_remote_path(cwd, run_id, self.config)
        command = "cd -- " + shlex.quote(str(cwd)) + " && "
        if env:
            command += "env " + " ".join(shlex.quote(str(k) + "=" + str(v)) for k, v in env.items()) + " "
        command += " ".join(shlex.quote(str(part)) for part in argv)
        return self._ssh(command, timeout=timeout)

    def download(self, remote_path: PurePosixPath, local_path: Path) -> CommandResult:
        run_id = remote_path.parts[len(REMOTE_BASE.parts)] if len(remote_path.parts) > len(REMOTE_BASE.parts) else ""
        _validate_remote_path(remote_path, run_id, self.config)
        argv = ["gcloud", "compute", "scp", f"{self.config.instance}:{remote_path}", str(local_path),
                "--project", self.config.project, "--zone", self.config.zone, "--tunnel-through-iap"]
        return _as_command_result(self.runner(argv, capture_output=True, text=True, timeout=600, check=False))


class LocalTransport:
    """Filesystem transport for running the whole campaign on the evaluator host.

    Used on the GCP VM (chialoops): prepare/upload/download are copies inside
    /work/peweaver/runs, and run() executes commands with subprocess.  The
    per-run directory containment checks are identical to the remote
    transport; nothing outside base/<run_id>/source is touched.
    """

    def __init__(self, config: RemoteConfig | None = None,
                 runner: Callable[..., Any] | None = None) -> None:
        self.config = config or RemoteConfig()
        self.runner = runner or subprocess.run

    def prepare_source(self, run_id: str, remote_source: PurePosixPath) -> CommandResult:
        root = remote_run_root(run_id, self.config)
        _validate_remote_path(remote_source, run_id, self.config)
        try:
            Path(root).mkdir(parents=True, exist_ok=True)
            shutil.copytree(str(self.config.source), str(remote_source),
                            dirs_exist_ok=True, symlinks=True)
        except (OSError, shutil.Error) as exc:
            return CommandResult(1, "", f"prepare_source failed: {type(exc).__name__}")
        return CommandResult(0, "prepared", "")

    def upload(self, local_path: Path, remote_path: PurePosixPath) -> CommandResult:
        run_id = remote_path.parts[len(REMOTE_BASE.parts)] if len(remote_path.parts) > len(REMOTE_BASE.parts) else ""
        _validate_remote_path(remote_path, run_id, self.config)
        try:
            Path(str(remote_path)).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(local_path), str(remote_path))
        except OSError as exc:
            return CommandResult(1, "", f"upload failed: {type(exc).__name__}")
        return CommandResult(0, "uploaded", "")

    def run(self, argv: Sequence[str], *, cwd: PurePosixPath,
            env: Mapping[str, str] | None = None, timeout: float = 180.0) -> CommandResult:
        if not cwd.is_absolute():
            raise CampaignError("remote cwd must be absolute")
        run_id = cwd.parts[len(REMOTE_BASE.parts)] if len(cwd.parts) > len(REMOTE_BASE.parts) else ""
        _validate_remote_path(cwd, run_id, self.config)
        merged_env = dict(os.environ)
        merged_env.update({str(k): str(v) for k, v in (env or {}).items()})
        completed = self.runner([str(part) for part in argv], cwd=str(cwd), env=merged_env,
                                capture_output=True, text=True, timeout=timeout, check=False)
        return _as_command_result(completed)

    def download(self, remote_path: PurePosixPath, local_path: Path) -> CommandResult:
        run_id = remote_path.parts[len(REMOTE_BASE.parts)] if len(remote_path.parts) > len(REMOTE_BASE.parts) else ""
        _validate_remote_path(remote_path, run_id, self.config)
        try:
            shutil.copy2(str(remote_path), str(local_path))
        except OSError as exc:
            return CommandResult(1, "", f"download failed: {type(exc).__name__}")
        return CommandResult(0, "downloaded", "")


def _json_from_output(text: str) -> dict[str, Any] | None:
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def parse_functional_result(value: Mapping[str, Any]) -> tuple[bool, list[str]]:
    """Require explicit single-frame and three-frame continuous results in both modes."""
    if not isinstance(value, Mapping):
        return False, ["functional result is not an object"]
    modes = value.get("modes", value.get("results", value))
    if not isinstance(modes, Mapping):
        return False, ["functional modes are missing"]
    required = {
        "mode64_single": ("mode64_single",),
        "mode128_single": ("mode128_single",),
        "mode64_continuous": ("mode64_continuous", "mode64_three_frame", "mode64_burst"),
        "mode128_continuous": ("mode128_continuous", "mode128_three_frame", "mode128_burst"),
    }
    errors: list[str] = []
    for label, aliases in required.items():
        found = next((modes.get(alias) for alias in aliases if alias in modes), None)
        if not isinstance(found, Mapping) or found.get("passed") is not True:
            errors.append(f"{label} did not explicitly pass")
    return not errors and value.get("passed") is True, errors


def validate_physical_result(result: Mapping[str, Any], candidate_hash: str,
                             logs: Mapping[str, str] | None = None) -> list[str]:
    errors: list[str] = []
    try:
        if result.get("schema") != "peweaver-physical-result-2":
            errors.append("unexpected physical result schema")
        design = result["design"]
        if design.get("top") != "peweaver_ppa_shared_fft":
            errors.append("unexpected physical top module")
        recorded = design["reference_source_hashes_sha256"]["rtl/peweaver_shared_fft.v"]
        if recorded != candidate_hash:
            errors.append("physical result candidate hash mismatch")
        pnr = result["results"]["pnr"]
        if pnr.get("timing_met") is not True:
            errors.append("timing is not met")
        if float(pnr.get("setup_slack_ns", -1)) <= 0 or float(pnr.get("hold_slack_ns", -1)) <= 0:
            errors.append("timing slack is not positive")
        if int(result.get("drc_violation_lines", -1)) != 0:
            errors.append("DRC is not clean")
        area = float(pnr.get("cell_area_um2", 0))
        if not (0 < area < 424885):
            errors.append("placed area is outside the accepted bound")
        power = result["results"]["power_mw"]
        for mode in ("streaming_window_64", "streaming_window_128"):
            if float(power[mode]["total_mw"]) <= 0:
                errors.append(f"missing {mode} power/activity")
        activity = result["activity"]
        if int(activity.get("annotated_pins_streaming", 0)) <= 0 or int(activity.get("annotated_pins_streaming_128", 0)) <= 0:
            errors.append("missing power activity annotation")
    except (KeyError, TypeError, ValueError):
        errors.append("malformed physical result")
    logs = logs or {}
    gls = {name: text for name, text in logs.items() if "gls" in name.lower() or "iverilog" in name.lower()}
    if not gls:
        errors.append("missing newly generated GLS logs")
    for name, text in gls.items():
        upper = text.upper()
        if any(marker in upper for marker in ("FAIL", "ERROR", "PEWEAVER_ACTIVITY_ERROR")):
            errors.append(f"GLS failure in {Path(name).name}")
        if not any(marker in upper for marker in ("PASS", "PEWEAVER_ACTIVITY_DONE", "COMPLETED SUCCESSFULLY")):
            errors.append(f"GLS pass marker missing in {Path(name).name}")
    openroad = {name: text for name, text in logs.items() if "openroad" in name.lower()}
    if not openroad:
        errors.append("missing newly generated OpenROAD logs")
    if any("STA-1452" in text for text in openroad.values()):
        errors.append("STA-1452 present in OpenROAD logs")
    return errors


def _bounded_feedback(value: Mapping[str, Any], limit: int = 1200) -> str:
    allowed = ("status", "reason", "error_code", "summary", "mismatch", "errors")
    parts = []
    for key in allowed:
        if key in value:
            text = "".join(ch for ch in str(value[key]).replace("\n", " ") if ch.isprintable())
            parts.append(f"{key}={text}")
    return ("Evaluator summary: " + "; ".join(parts))[:limit]


def _private_write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    os.chmod(path, 0o600)


class RoutedCampaign:
    def __init__(self, shim: ProviderNeutralModelShim, *, transport: RemoteTransport | None = None,
                 artifact_root: Path | None = None, remote: RemoteConfig | None = None,
                 max_turns: int = 3, model_timeout: float = 600.0,
                 evaluator_timeout: float = 180.0) -> None:
        self.shim = shim
        self.transport = transport
        self.artifact_root = (artifact_root or Path(tempfile.gettempdir()) / "peweaver-campaigns").resolve()
        self.remote = remote or RemoteConfig()
        self.max_turns = max(1, int(max_turns))
        self.model_timeout = model_timeout
        self.evaluator_timeout = evaluator_timeout

    def preflight(self, *, run_id: str, source_root: Path, failing_rtl: Path,
                  architecture_files: Sequence[Path] = (), reference_rtl_files: Sequence[Path] = ()) -> dict[str, Any]:
        errors: list[str] = []
        try:
            validate_run_id(run_id)
            source = source_root.resolve()
            fail = failing_rtl.resolve()
            if not source.is_dir() or not _regular(fail):
                errors.append("source root or historical failing RTL is invalid")
            else:
                fail.relative_to(source)
                if _forbidden_curated_path(fail, source):
                    errors.append("historical RTL is a protected evaluator input")
                for path in (*architecture_files, *reference_rtl_files):
                    p = Path(path).resolve()
                    p.relative_to(source)
                    if not _regular(p) or _forbidden_curated_path(p, source):
                        errors.append(f"invalid curated file: {p.name}")
            remote_run_root(run_id, self.remote)
        except (OSError, ValueError, CampaignError):
            errors.append("invalid staging or remote path")
        return {"status": "ready" if not errors else "blocked", "passed": not errors,
                "attempted": False, "errors": errors}

    def _remote_evaluate(self, run_id: str, staged: StagedCampaign, *, allow_physical: bool,
                         artifact_dir: Path) -> dict[str, Any]:
        if self.transport is None:
            return {"passed": False, "status": "remote_transport_missing", "error_code": "no_transport"}
        root = remote_run_root(run_id, self.remote)
        remote_source = root / "source"
        _validate_remote_path(remote_source, run_id, self.remote)
        prep = _as_command_result(self.transport.prepare_source(run_id, remote_source))
        if prep.returncode != 0:
            return {"passed": False, "status": "source_prepare_failed"}
        errors = static_candidate_errors(staged.candidate)
        if errors:
            return {"passed": False, "status": "candidate_rejected", "errors": errors}
        upload_path = remote_source / REMOTE_CANDIDATE
        _validate_remote_path(upload_path, run_id, self.remote)
        uploaded = _as_command_result(self.transport.upload(staged.candidate, upload_path))
        if uploaded.returncode != 0:
            return {"passed": False, "status": "candidate_upload_failed"}
        functional = _as_command_result(self.transport.run(
            ("python3", "orchestration/shared_fft_regression.py", "--candidate", str(upload_path), "--json"),
            cwd=remote_source, env=REMOTE_TOOL_ENV, timeout=max(self.evaluator_timeout, 300.0)))
        _private_write(artifact_dir / "functional.transcript", f"returncode={functional.returncode}\nstatus={'output-present' if functional.stdout else 'empty'}\n")
        parsed = _json_from_output(functional.stdout)
        if functional.returncode != 0 or parsed is None:
            return {"passed": False, "status": "functional_failed"}
        functional_ok, functional_errors = parse_functional_result(parsed)
        # Bounded measured-failure evidence for the next worker turn: the
        # judge's own tail contains per-test PASS/FAIL lines and mismatch
        # counts.  A blind "functional_failed" cannot drive iteration.
        tail = str(parsed.get("log_tail", ""))
        summary = "".join(ch for ch in tail.replace("\n", " | ") if ch.isprintable())[-800:]
        record: dict[str, Any] = {"passed": functional_ok,
                                  "status": "functional_passed" if functional_ok else "functional_failed",
                                  "summary": summary}
        if functional_errors:
            record["errors"] = functional_errors
        if not functional_ok or not allow_physical:
            record["physical"] = {"status": "not_run"}
            return record
        physical = _as_command_result(self.transport.run(
            ("env", "PEWEAVER_DESIGN=shared", "./run-physical.sh"),
            cwd=remote_source / "physical", env=REMOTE_TOOL_ENV,
            timeout=max(self.evaluator_timeout, 3600.0)))
        _private_write(artifact_dir / "physical.transcript", f"returncode={physical.returncode}\nstatus={'output-present' if physical.stdout else 'empty'}\n")
        result_local = artifact_dir / "physical_result.json"
        downloaded = _as_command_result(self.transport.download(remote_source / REMOTE_RESULT, result_local))
        result: dict[str, Any] | None = None
        if downloaded.returncode == 0 and result_local.is_file():
            try:
                result = json.loads(result_local.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                result = None
        logs: dict[str, str] = {}
        for rel in (*GLS_LOG_NAMES, *OPENROAD_LOG_NAMES):
            target = artifact_dir / Path(rel).name
            response = _as_command_result(self.transport.download(remote_source / rel, target))
            if response.returncode == 0 and target.is_file():
                logs[rel] = target.read_text(encoding="utf-8", errors="replace")
        physical_errors = ["physical command failed"] if physical.returncode != 0 else []
        if result is None:
            physical_errors.append("physical result missing or malformed")
        else:
            physical_errors.extend(validate_physical_result(result, sha256_file(staged.candidate), logs))
        record["physical"] = {"passed": not physical_errors, "errors": physical_errors}
        record["passed"] = not physical_errors
        return record

    def run(self, *, run_id: str, source_root: Path, failing_rtl: Path,
            architecture_files: Sequence[Path] = (), reference_rtl_files: Sequence[Path] = (),
            lead_prompt: str = "Rank the bounded atomic PEWeaver power hypothesis.",
            worker_prompt: str = "Edit only candidate.v for one atomic hypothesis.",
            allow_model_calls: bool = False, allow_physical: bool = False,
            dry_run: bool = False, staging_root: Path | None = None,
            token_cap: int = 32768) -> CampaignResult:
        pf = self.preflight(run_id=run_id, source_root=source_root, failing_rtl=failing_rtl,
                            architecture_files=architecture_files, reference_rtl_files=reference_rtl_files)
        if dry_run or not pf["passed"]:
            return CampaignResult(run_id, "dry_run" if dry_run else "blocked", error=";".join(pf["errors"]))
        if not allow_model_calls:
            return CampaignResult(run_id, "model_calls_not_authorized", error="allow_model_calls_required")
        staged = stage_campaign(source_root=source_root, failing_rtl=failing_rtl,
                                architecture_files=architecture_files, reference_rtl_files=reference_rtl_files,
                                staging_root=staging_root)
        # OpenCode workers edit the candidate inside their isolated work dir;
        # that dir must BE the campaign staging tree or the worker can never
        # mutate candidate.v.  Point the shim's OpenCode work dir at staging
        # when any configured route uses opencode.
        routes = set(self.shim.config.lead_routes) | set(self.shim.config.worker_routes)
        if any(route.provider == "opencode" for route in routes):
            # ShimConfig is frozen; build a derived config scoped to staging.
            self.shim.config = replace(self.shim.config, opencode_work_dir=staged.root)
        artifact_dir = self.artifact_root / validate_run_id(run_id)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(artifact_dir, 0o700)
        _private_write(artifact_dir / "hashes.json", json.dumps({"candidate": sha256_file(staged.candidate),
                      "protected": dict(staged.protected_hashes)}, sort_keys=True))
        lead_hash = sha256_file(staged.candidate)
        lead = self.shim.call(ModelRequest.create(run_id=run_id, work_id="lead", role="lead",
            prompt=lead_prompt, context_hash=staged.context_hash, candidate_hash=lead_hash,
            candidate_path=str(staged.candidate), candidate_hash_reader=lambda: sha256_file(staged.candidate),
            deadline=time.time() + self.model_timeout, request_id=f"{run_id}:lead",
            token_cap=token_cap))
        try:
            assert_staged_immutable(staged)
            if sha256_file(staged.candidate) != lead_hash:
                raise CampaignError("lead mutated candidate")
        except CampaignError as exc:
            return CampaignResult(run_id, "mutation_guard_failed", artifact_dir=str(artifact_dir), error=str(exc))
        if not lead.success:
            return CampaignResult(run_id, "lead_failed", artifact_dir=str(artifact_dir), error="lead_call_failed")
        # Human-readable capture of the model's plan for operator review.
        _private_write(artifact_dir / "lead_plan.txt", (lead.output or "")[:8192])
        turns: list[Mapping[str, Any]] = []
        evaluations: list[Mapping[str, Any]] = []
        plan = (lead.output or "")[:4096]
        candidate_intro = (
            "--- CURRENT CANDIDATE (candidate.v) ---\n"
            + staged.candidate.read_text(encoding="utf-8", errors="replace")
            + "\n--- END CURRENT CANDIDATE ---\n"
            "Reply with the COMPLETE corrected candidate.v file (one ```verilog fenced block).\n"
            "Do not truncate, do not add commentary outside the block.\n")
        feedback = (worker_prompt + "\nBounded lead plan (advisory):\n" + plan
                    + "\n" + candidate_intro)
        for turn in range(1, self.max_turns + 1):
            current_hash = sha256_file(staged.candidate)
            response = self.shim.call(ModelRequest.create(run_id=run_id, work_id=f"worker:{turn}", role="worker",
                prompt=feedback[:200000], context_hash=staged.context_hash, candidate_hash=current_hash,
                candidate_path=str(staged.candidate), candidate_hash_reader=lambda: sha256_file(staged.candidate),
                deadline=time.time() + self.model_timeout, request_id=f"{run_id}:worker:{turn}",
                token_cap=token_cap))
            try:
                assert_staged_immutable(staged)
            except CampaignError as exc:
                return CampaignResult(run_id, "mutation_guard_failed", turns=tuple(turns), evaluator_results=tuple(evaluations),
                                      artifact_dir=str(artifact_dir), error=str(exc))
            # Human-readable capture of the worker's full response for
            # operator review (bounded at 256 KiB).
            _private_write(artifact_dir / f"worker_turn{turn}_response.txt",
                           (response.output or "")[:262144])
            turn_record = {"turn": turn, "provider": response.provider,
                           "status": "model_succeeded" if response.success else response.status,
                           "candidate_hash": sha256_file(staged.candidate)}
            turns.append(turn_record)
            # An agentic backend (opencode) may legitimately mutate the
            # candidate and still return an unusable final message.  A
            # candidate that changed during the call is the work product and
            # must be evaluated; only an unchanged candidate with a failed
            # response is a hard worker failure.
            if not response.success and sha256_file(staged.candidate) == current_hash:
                print(json.dumps({"diagnostic": "worker_call_failed",
                                  "status": response.status, "provider": response.provider,
                                  "model": response.model, "attempt": response.attempt,
                                  "error": response.error, "failover": response.failover},
                                 sort_keys=True), flush=True)
                return CampaignResult(run_id, "worker_failed", turns=tuple(turns), evaluator_results=tuple(evaluations),
                                      artifact_dir=str(artifact_dir), error=f"worker_call_failed:{response.status}:{response.provider}:{response.error}")
            applied = False
            if response.provider != "opencode":
                try:
                    applied = apply_worker_output(staged.candidate, response.output or "",
                                                  provider=response.provider)
                except (OSError, UnicodeError):
                    applied = False
                if not applied:
                    turns.append({"turn": turn, "status": "no_candidate_in_output",
                                  "provider": response.provider})
                    evaluations.append({"passed": False, "status": "candidate_unchanged"})
                    return CampaignResult(run_id, "candidate_rejected", turns=tuple(turns),
                                          evaluator_results=tuple(evaluations),
                                          artifact_dir=str(artifact_dir),
                                          error="worker_output_lacked_candidate")
            new_hash = sha256_file(staged.candidate)
            static_errors = static_candidate_errors(staged.candidate)
            if new_hash == current_hash:
                evaluations.append({"passed": False, "status": "candidate_unchanged"})
                return CampaignResult(run_id, "candidate_rejected", turns=tuple(turns), evaluator_results=tuple(evaluations), artifact_dir=str(artifact_dir), error="candidate_unchanged")
            if static_errors:
                evaluations.append({"passed": False, "status": "candidate_rejected", "errors": static_errors})
                return CampaignResult(run_id, "candidate_rejected", turns=tuple(turns), evaluator_results=tuple(evaluations), artifact_dir=str(artifact_dir), error="anti_cheat_rejected")
            evaluation = self._remote_evaluate(run_id, staged, allow_physical=allow_physical, artifact_dir=artifact_dir)
            evaluations.append(evaluation)
            if evaluation.get("passed") is True:
                return CampaignResult(run_id, "accepted", True, tuple(turns), tuple(evaluations), str(artifact_dir))
            feedback = (worker_prompt + "\n" + _bounded_feedback(evaluation)
                        + "\n" + candidate_intro)
        return CampaignResult(run_id, "exhausted", turns=tuple(turns), evaluator_results=tuple(evaluations),
                              artifact_dir=str(artifact_dir), error="turn_budget_exhausted")


def preflight(**kwargs: Any) -> dict[str, Any]:
    """Convenience preflight that constructs no transport and performs no calls."""
    shim = kwargs.pop("shim", None) or ProviderNeutralModelShim()
    return RoutedCampaign(shim).preflight(**kwargs)


def _cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--failing-rtl", type=Path, required=True)
    parser.add_argument("--architecture", type=Path, action="append", default=[])
    parser.add_argument("--reference-rtl", type=Path, action="append", default=[])
    parser.add_argument("--allow-model-calls", action="store_true")
    parser.add_argument("--allow-physical", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--transport", choices=("gcloud", "local"), default="gcloud",
                        help="gcloud: IAP ssh/scp to the VM from an authed host; "
                             "local: filesystem transport (run the whole campaign on the VM)")
    parser.add_argument("--evaluator-timeout", type=float, default=3600.0,
                        help="per-evaluator-command timeout in seconds")
    parser.add_argument("--model-timeout", type=float, default=600.0,
                        help="per-model-call deadline in seconds")
    parser.add_argument("--max-turns", type=int, default=6,
                        help="maximum worker repair turns per campaign")
    parser.add_argument("--token-cap", type=int, default=32768,
                        help="per-model-call output token cap")
    parser.add_argument("--remote-source", type=PurePosixPath,
                        default=PurePosixPath("/work/peweaver/source/chia/examples/peweaver_deployed"),
                        help="remote tree copied into each run root")
    parser.add_argument("--lead-prompt", default="Rank the bounded atomic PEWeaver power hypothesis.")
    parser.add_argument("--worker-prompt", default="Edit only candidate.v for one atomic hypothesis.")
    args = parser.parse_args(argv)
    if args.dry_run:
        result = preflight(run_id=args.run_id, source_root=args.source_root, failing_rtl=args.failing_rtl,
                           architecture_files=args.architecture, reference_rtl_files=args.reference_rtl)
    else:
        # cli_opt_in=True: this reviewed campaign entry point is the CLI opt-in
        # boundary; OpenRouter remains additionally gated by the runtime flag
        # and PEWEAVER_ALLOW_OPENROUTER_BILLABLE=1.
        shim = ProviderNeutralModelShim(ShimConfig.from_environment(cli_opt_in=True))
        remote = RemoteConfig(source=args.remote_source)
        transport: RemoteTransport
        if args.transport == "local":
            transport = LocalTransport(remote)
        else:
            transport = GcloudRemoteTransport(remote)
        result = RoutedCampaign(shim, transport=transport,
                                max_turns=args.max_turns,
                                evaluator_timeout=args.evaluator_timeout,
                                model_timeout=args.model_timeout).run(
            run_id=args.run_id, source_root=args.source_root, failing_rtl=args.failing_rtl,
            architecture_files=args.architecture, reference_rtl_files=args.reference_rtl,
            lead_prompt=args.lead_prompt, worker_prompt=args.worker_prompt,
            allow_model_calls=args.allow_model_calls, allow_physical=args.allow_physical,
            token_cap=args.token_cap)
        result = result.public_dict()
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("passed") or result.get("status") == "accepted" else 1


if __name__ == "__main__":
    raise SystemExit(_cli())


__all__ = ["CampaignError", "CampaignResult", "CommandResult", "GcloudRemoteTransport", "RemoteConfig",
           "RoutedCampaign", "StagedCampaign", "assert_staged_immutable", "parse_functional_result",
           "preflight", "remote_run_root", "sha256_file", "stage_campaign", "static_candidate_errors",
           "validate_physical_result", "validate_run_id"]
