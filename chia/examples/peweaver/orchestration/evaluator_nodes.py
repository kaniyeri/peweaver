#!/usr/bin/env python3
"""Shared deterministic evaluator nodes for the PEWeaver drivers.

Every node here is domain-neutral: drivers pass their own module names, port
lists, and commands. The nodes are thin ``@ChiaFunction`` wrappers so the
CHIA graph shows deterministic tool execution as first-class scheduled work
(Ray resource ``yosys``), and every call goes through :func:`dispatch`, which
converts infrastructure failures into retryable outcomes instead of semantic
rejections.
"""

from __future__ import annotations

import os
import json
import re
import signal
import subprocess
from pathlib import Path

from chia.base.ChiaFunction import ChiaFunction, get

from chia_merge import GateOutcome, RetryableGateError
from peweaver_evaluator import map_node_result

ANTI_CHEAT = (
    (re.compile(r"\$system\b|\$readmem(?:h|b)?\b", re.I), "system or readmem I/O"),
    (re.compile(r"\$(?:fopen|fread|fwrite|fscanf|fclose)\b", re.I), "file I/O"),
    (re.compile(r"\b(?:DPI|PLI)\b|import\s+\"DPI-C\"", re.I), "DPI/PLI"),
    (re.compile(r"\$test\$plusargs\b", re.I), "plusargs"),
    (re.compile(r"\b(?:initial|final)\b", re.I), "initial/final block"),
    (re.compile(r"\b(?:tb|testbench|uut|dut)\s*\.", re.I), "hierarchical tb ref"),
)


class RetryableError(RetryableGateError):
    """Infrastructure/tooling failure: the gate may be retried unchanged."""


def tool_env(oss_bin: str | None = None) -> dict:
    env = dict(os.environ)
    if oss_bin:
        env["PATH"] = oss_bin + ":" + env.get("PATH", "/usr/bin:/bin")
    return env


def _run_child(cmd: list, cwd: str, env: dict, timeout: int):
    """Run *cmd* in its own process group; kill the whole group on timeout."""
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True,
                            start_new_session=True)
    try:
        return proc.communicate(timeout=timeout) + (proc.returncode,)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            proc.kill()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            pass
        raise RetryableError(f"tool timeout after {timeout}s: {cmd[0]}")


@ChiaFunction(resources={"yosys": 1})
def lint_node(rtl_text: str, top_module: str, ports: list[str],
              extra_patterns: list | None = None) -> dict:
    """Static anti-cheat + interface scan over stripped candidate text."""
    code = re.sub(r"/\*.*?\*/", " ", rtl_text, flags=re.S)
    code = re.sub(r"//[^\n]*", " ", code)
    code = re.sub(r'"(?:[^"\\]|\\.)*"', " ", code)
    errors = [label for pattern, label in ANTI_CHEAT if pattern.search(code)]
    for pattern, label in (extra_patterns or []):
        if pattern.search(code):
            errors.append(label)
    no_params = re.sub(r"#\s*\(\s*(?:\.|parameter\b|localparam\b)", "PARAMS(", code)
    if re.search(r"#\s*(?:\d|\w+)", no_params):
        errors.append("simulation delay")
    for port in ports:
        if not re.search(rf"\b{port}\b", rtl_text):
            errors.append(f"missing port: {port}")
    if not re.search(rf"\bmodule\s+{top_module}\b", rtl_text):
        errors.append(f"module {top_module} not found")
    return {"passed": not errors, "errors": errors}


@ChiaFunction(resources={"yosys": 1})
def yosys_node(script: str, oss_bin: str | None = None,
               timeout: int = 600) -> dict:
    """Run one Yosys -p script; rc 0 means the script itself succeeded."""
    try:
        out, err, rc = _run_child(
            ["yosys", "-p", script], cwd="/tmp", env=tool_env(oss_bin),
            timeout=timeout)
    except FileNotFoundError as exc:
        raise RetryableError(f"yosys binary missing: {exc}") from exc
    return {"passed": rc == 0, "rc": rc, "note": out[-20000:],
            "stderr": err[-4000:]}


@ChiaFunction(resources={"yosys": 1})
def sim_node(cmd: list, cwd: str, env_path_prefix: str | None = None,
             timeout: int = 900) -> dict:
    """Run one deterministic simulation/compile command in its own group."""
    env = tool_env(env_path_prefix)
    try:
        out, err, rc = _run_child(cmd, cwd=cwd, env=env, timeout=timeout)
    except FileNotFoundError as exc:
        raise RetryableError(f"simulator binary missing: {exc}") from exc
    return {"passed": rc == 0, "rc": rc,
            "note": (out + "\n" + err)[-20000:]}


@ChiaFunction(resources={"yosys": 1})
def timing_probe_node(command: list[str], cwd: str,
                      env_path_prefix: str | None = None,
                      timeout: int = 600) -> dict:
    """Run a controller-supplied, fixed timing-probe command.

    The command must print one JSON object containing a boolean ``passed`` and
    optional ``metrics`` on stdout.  The model never supplies this command;
    the driver pins it in the campaign configuration.  A missing or malformed
    result is invalid evidence, not an infrastructure pass.
    """
    if not command:
        return {"passed": False, "retry": False,
                "status": "invalid_result", "note": "empty timing probe command"}
    try:
        out, err, rc = _run_child(command, cwd=cwd, env=tool_env(env_path_prefix),
                                  timeout=timeout)
    except FileNotFoundError as exc:
        raise RetryableError(f"timing probe binary missing: {exc}") from exc
    parsed = None
    for line in reversed(out.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            parsed = value
            break
    if parsed is None or type(parsed.get("passed")) is not bool:
        return {"passed": False, "retry": False, "status": "invalid_result",
                "note": "timing probe did not emit a JSON object with boolean passed",
                "rc": rc}
    metrics = parsed.get("metrics", {})
    if not isinstance(metrics, dict):
        return {"passed": False, "retry": False, "status": "invalid_result",
                "note": "timing probe metrics must be an object", "rc": rc}
    try:
        json.dumps(metrics, allow_nan=False)
    except (TypeError, ValueError):
        return {"passed": False, "retry": False, "status": "invalid_result",
                "note": "timing probe metrics must be finite JSON", "rc": rc}
    passed = parsed["passed"] and rc == 0
    return {
        "passed": passed,
        "retry": False,
        "status": (parsed.get("status", "passed" if passed else "rejected")
                   if rc == 0 else "tool_failure"),
        "metrics": metrics,
        "diagnostics": parsed.get("diagnostics", []),
        "note": (str(parsed.get("note", "")) +
                 (f"; command exited {rc}" if rc else ""))[-4000:],
        "rc": rc,
        "stderr": err[-2000:],
    }


def call_node(node, *args, **kwargs) -> dict:
    """Invoke a node through CHIA scheduling (Ray) or locally as fallback.

    Infrastructure/transport failures are raised as :class:`RetryableError`;
    semantic tool results pass through unchanged.
    """
    try:
        if _ray_active():
            return get(node.chia_remote(*args, **kwargs))
        return node(*args, **kwargs)
    except RetryableError:
        raise
    except (ConnectionError, OSError) as exc:
        raise RetryableError(str(exc)) from exc
    except Exception as exc:  # ray/transport layer surfaces many types
        if _is_infra(exc):
            raise RetryableError(str(exc)) from exc
        raise


def dispatch(node, *args, name: str, note_len: int = 400,
             **kwargs) -> GateOutcome:
    """Call a node and normalize its dict result into a GateOutcome."""
    try:
        r = call_node(node, *args, **kwargs)
    except RetryableError as exc:
        return GateOutcome(name, False, note=f"retryable: {exc}", retry=True)
    if not isinstance(r, dict):
        return GateOutcome(name, False, note="invalid evaluator result object")
    mapped = map_node_result(r)
    detail = {k: v for k, v in r.items()
              if k not in ("passed", "note", "summary", "errors", "retry",
                           "status", "candidate_accepted", "diagnostics")}
    if mapped.metrics:
        detail["metrics"] = dict(mapped.metrics)
    if mapped.diagnostics:
        detail["diagnostics"] = list(mapped.diagnostics)
    note = str(r.get("note") or r.get("summary") or r.get("error")
               or r.get("errors") or "")
    if mapped.status == "invalid_result":
        note = note or "; ".join(mapped.diagnostics)
    return GateOutcome(name, mapped.passed, note=note[-note_len:],
                       retry=mapped.retryable,
                       detail=detail if isinstance(detail, dict) else {})


def _ray_active() -> bool:
    """True only when a CHIA/Ray dispatch should be attempted.

    ``PEWEAVER_DISABLE_RAY=1`` forces the local evaluator path even when a
    Ray instance happens to be initialized (laptop preflight and selftests).
    """
    if os.environ.get("PEWEAVER_DISABLE_RAY") == "1":
        return False
    try:
        import ray
        return ray.is_initialized()
    except Exception:
        return False


def _is_infra(exc: Exception) -> bool:
    text = f"{type(exc).__module__}.{type(exc).__name__}: {exc}".lower()
    markers = ("ray", "redis", "connection", "gcs", "worker", "actor",
               "deserialize", "timeout", "unavailable")
    return any(m in text for m in markers)
