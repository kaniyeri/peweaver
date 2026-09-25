#!/usr/bin/env python3
"""ChiaMerge: clean-room PE-merge composition over chialoops primitives.

    ChiaMerge(inputs)
        = ChiaAdvise(architecture prompt)          # once, before the loop
          + ChiaIterate{ ChiaAdvise -> ChiaImplement -> ChiaCheckCondition
                         -> jump to top }            # until accepted or budget

One call owns the whole merge: you breakpoint on ``ChiaMerge``, step over one
line, and the iterate is the recursion that runs until acceptance. Every
implementation attempt is a transaction: fresh sandbox, one bounded agentic
edit burst, deterministic gate ladder, then promote-to-best or discard. The
model worker never sees a shared candidate, seed, or prior solution — only the
pinned input designs, the behavioral contract, and gate feedback.

Model calls run through CHIA's own adapter (``chia.models.opencode.
OpenCodeLLM``, a ``@ChiaFunction`` node over the opencode CLI). Gate
callables are design-specific and supplied by the caller; this module stays
PE-agnostic.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from chia.models.opencode import OpenCodeLLM

VERDICT_ACCEPT = "ACCEPT"
VERDICT_IMPROVE = "IMPROVE"
VERDICT_REJECT = "REJECT"
VERDICT_RETRY = "RETRY"
MODE_DISCOVERY = "MergeDiscovery"
MODE_PARENT = "ParentOptimization"

READ_ONLY_PERMISSIONS = {
    "edit": "deny",
    "bash": "deny",
    "webfetch": "deny",
    "external_directory": "deny",
}
REPLY_PERMISSIONS = {
    "edit": "deny",
    "bash": "deny",
    "webfetch": "deny",
    "external_directory": "deny",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rmrf(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path, ignore_errors=True)


def _atomic_json(path: Path, value: object) -> None:
    """Publish a JSON evidence file without exposing a partial document."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=1, allow_nan=False))
    os.replace(tmp, path)


def workspace_manifest(root: Path) -> dict[str, str]:
    """Map relpath -> sha256 for every regular file under *root*."""
    manifest: dict[str, str] = {}
    if not root.is_dir():
        return manifest
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.is_symlink():
            manifest[str(p.relative_to(root))] = _sha256(p)
    return manifest


def manifest_hash(manifest: dict[str, str]) -> str:
    blob = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Gate ladder
# ---------------------------------------------------------------------------


@dataclass
class GateOutcome:
    """Result of one deterministic gate against a sandbox workspace."""

    name: str
    passed: bool
    note: str = ""
    detail: dict = field(default_factory=dict)
    retry: bool = False


class RetryableGateError(Exception):
    """Declared evaluator infrastructure failure, safe to retry unchanged."""


@dataclass
class CheckResult:
    verdict: str
    level: int
    feedback: str = ""
    detail: dict = field(default_factory=dict)
    retry_gate_index: int | None = None


class ChiaCheckCondition:
    """Ordered gate ladder over a sandbox: ChiaCheckCondition primitive.

    Gates run in order; ``level`` is the count of contiguously passed gates.
    The first ``retry`` outcome (infrastructure failure) aborts with VERDICT_
    RETRY; the first failing gate aborts with VERDICT_REJECT and its note as
    feedback; a full pass yields VERDICT_ACCEPT when ``level >= accept_level``,
    else VERDICT_IMPROVE.
    """

    def __init__(self, gates: Sequence[Callable[[Path], GateOutcome]],
                 accept_level: int | None = None):
        self.gates = list(gates)
        self.accept_level = accept_level if accept_level is not None else len(self.gates)

    def evaluate(self, sandbox: Path, best_level: int = 0, *,
                 start_gate: int = 0, detail: dict | None = None) -> CheckResult:
        if start_gate < 0 or start_gate > len(self.gates):
            raise ValueError("start_gate is outside the gate ladder")
        accumulated = dict(detail or {})
        level = start_gate
        for gate_index, gate in enumerate(self.gates[start_gate:], start=start_gate):
            try:
                outcome = gate(sandbox)
            except RetryableGateError as exc:
                return CheckResult(
                    verdict=VERDICT_RETRY, level=level,
                    feedback=f"gate {gate!r} raised: {exc}", detail=accumulated,
                    retry_gate_index=gate_index)
            safe_detail = {}
            for key, value in outcome.detail.items():
                try:
                    json.dumps(value, allow_nan=False)
                except (TypeError, ValueError):
                    continue
                safe_detail[key] = value
            accumulated[outcome.name] = {
                "passed": outcome.passed, "retry": outcome.retry,
                "note": outcome.note, **safe_detail}
            if outcome.retry:
                return CheckResult(
                    verdict=VERDICT_RETRY, level=level,
                    feedback=f"infrastructure failure at gate '{outcome.name}': "
                             f"{outcome.note}", detail=accumulated,
                    retry_gate_index=gate_index)
            if not outcome.passed:
                feedback = (f"gate '{outcome.name}' failed: {outcome.note}")
                if level > best_level:
                    return CheckResult(
                        verdict=VERDICT_IMPROVE, level=level, feedback=feedback,
                        detail=accumulated)
                return CheckResult(
                    verdict=VERDICT_REJECT, level=level, feedback=feedback,
                    detail=accumulated)
            level += 1
        if level >= self.accept_level:
            return CheckResult(verdict=VERDICT_ACCEPT, level=level,
                               detail=accumulated)
        return CheckResult(verdict=VERDICT_IMPROVE, level=level,
                           detail=accumulated)


# ---------------------------------------------------------------------------
# Run layout, locking, state
# ---------------------------------------------------------------------------


@dataclass
class RunPaths:
    root: Path
    inputs: Path
    best: Path
    attempts: Path
    artifacts: Path
    state_file: Path
    lock_file: Path

    @classmethod
    def create(cls, root: Path) -> "RunPaths":
        run = cls(
            root=Path(root),
            inputs=Path(root) / "inputs",
            best=Path(root) / "best",
            attempts=Path(root) / "attempts",
            artifacts=Path(root) / "artifacts",
            state_file=Path(root) / "artifacts" / "state.json",
            lock_file=Path(root) / "lock",
        )
        for d in (run.root, run.inputs, run.best, run.attempts, run.artifacts):
            d.mkdir(parents=True, exist_ok=True)
        return run


@contextmanager
def _null_lock():
    yield


@contextmanager
def _run_lock(run: RunPaths):
    """Exclusive run lock via flock: the kernel releases it if the holder
    dies, so takeover after a crash is automatic and race-free."""
    import fcntl

    fd = os.open(run.lock_file, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError(
                f"run {run.root} is locked by another live process; refusing to start")
        os.ftruncate(fd, 0)
        os.write(fd, json.dumps({"pid": os.getpid(), "ts": time.time()}).encode())
        os.fsync(fd)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def verify_resume_inputs(inputs_dir: Path, hashes_file: Path,
                         contract_file: Path, new_hashes: dict,
                         contract: str) -> None:
    """Refuse a resume whose pinned inputs or contract changed, including
    on-disk tampering of the copied input files themselves."""
    if not hashes_file.is_file():
        raise RuntimeError("resume refused: pinned input hash manifest missing")
    if not contract_file.is_file():
        raise RuntimeError("resume refused: contract file missing")
    stored = json.loads(hashes_file.read_text())
    if stored != new_hashes:
        raise RuntimeError("resume refused: pinned input set changed")
    for name, digest in stored.items():
        p = inputs_dir / Path(name).name
        if not p.is_file() or _sha256(p) != digest:
            raise RuntimeError(
                f"resume refused: pinned input '{name}' modified or missing")
    if contract_file.read_text() != contract:
        raise RuntimeError("resume refused: contract changed")


@dataclass
class IterationState:
    """Threaded loop state, persisted atomically after every mutation."""
    turn: int = 0
    accepted: bool = False
    best_level: int = 0
    best_hash: str = ""
    best_manifest: dict = field(default_factory=dict)
    architecture: str = ""
    advice: str = ""
    feedback: str = ""
    last_rejected_hash: str = ""
    last_rejected_dir: str = ""
    infra_retries: int = 0
    infra_attempts: int = 0
    history: list = field(default_factory=list)
    model_status: dict = field(default_factory=dict)
    mode: str = MODE_DISCOVERY
    parent_hash: str = ""
    parent_attested: bool = False
    config_hash: str = ""
    pending_evaluation: dict = field(default_factory=dict)
    model_infra_blocked: str = ""

    def record(self, entry: dict) -> None:
        self.history.append({"ts": time.time(), **entry})

    def save(self, state_file: Path) -> None:
        tmp = state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=1, allow_nan=False))
        os.replace(tmp, state_file)

    def to_dict(self) -> dict:
        return {
            "turn": self.turn, "accepted": self.accepted,
            "best_level": self.best_level, "best_hash": self.best_hash,
            "last_rejected_hash": self.last_rejected_hash,
            "last_rejected_dir": self.last_rejected_dir,
            "infra_retries": self.infra_retries,
            "infra_attempts": self.infra_attempts,
            "best_manifest": self.best_manifest,
            "architecture": self.architecture, "advice": self.advice,
            "feedback": self.feedback,
            "history": self.history, "model_status": self.model_status,
            "mode": self.mode, "parent_hash": self.parent_hash,
            "parent_attested": self.parent_attested,
            "config_hash": self.config_hash,
            "pending_evaluation": self.pending_evaluation,
            "model_infra_blocked": self.model_infra_blocked,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "IterationState":
        return cls(
            turn=d.get("turn", 0), accepted=d.get("accepted", False),
            best_level=d.get("best_level", 0),
            best_hash=d.get("best_hash", ""),
            best_manifest=d.get("best_manifest", {}),
            architecture=d.get("architecture", ""),
            advice=d.get("advice", ""), feedback=d.get("feedback", ""),
            last_rejected_hash=d.get("last_rejected_hash", ""),
            last_rejected_dir=d.get("last_rejected_dir", ""),
            infra_retries=d.get("infra_retries", 0),
            infra_attempts=d.get("infra_attempts", 0),
            history=d.get("history", []),
            model_status=d.get("model_status", {}),
            mode=d.get("mode", MODE_DISCOVERY),
            parent_hash=d.get("parent_hash", ""),
            parent_attested=d.get("parent_attested", False),
            config_hash=d.get("config_hash", ""),
            pending_evaluation=d.get("pending_evaluation", {}),
            model_infra_blocked=d.get("model_infra_blocked", ""),
        )

    @classmethod
    def load(cls, state_file: Path) -> "IterationState | None":
        if not state_file.is_file():
            return None
        d = json.loads(state_file.read_text())
        return cls.from_dict(d)


# ---------------------------------------------------------------------------
# Model primitives
# ---------------------------------------------------------------------------


def _make_llm(model: str, *, role: str, timeout: int, work_dir: Path,
              log_dir: Path | None, system_message: str,
              retries: int = 1, provider_options: dict | None = None):
    """Backend factory: 'gemini/<model>' selects the Gemini Developer API
    (DirectGeminiLLM, key from GEMINI_API_KEY env, pure text); anything else
    goes through the opencode CLI backend."""
    if model.startswith("gemini/"):
        from chia.models.vertex import DirectGeminiLLM

        return DirectGeminiLLM(
            model=model.split("/", 1)[1], system_message=system_message,
            timeout_seconds=timeout, retries=retries, max_tokens=65536,
            logging_name=f"chia-{role}-gemini",
            log_dir=str(log_dir) if log_dir else None)
    return OpenCodeLLM(
        model=model, timeout_seconds=timeout, retries=retries,
        work_dir=str(work_dir), logging_name=f"chia-{role}",
        log_dir=str(log_dir) if log_dir else None,
        system_message=system_message,
        provider_options=provider_options,
        dangerously_skip_permissions=False,
        config=READ_ONLY_PERMISSIONS if role == "advise" else REPLY_PERMISSIONS)


class ChiaAdvise:
    """Smart-model advisory call; opencode runs with write tools denied,
    gemini/* runs as pure text (sources are inlined into the prompt)."""

    def __init__(self, model: str, work_dir: Path, *, timeout: int = 1500,
                 log_dir: Path | None = None, retries: int = 1,
                 provider_options: dict | None = None):
        self.llm = _make_llm(model, role="advise", timeout=timeout,
                             work_dir=work_dir, log_dir=log_dir,
                             system_message="", retries=retries,
                             provider_options=provider_options)

    def __call__(self, prompt: str) -> str:
        resp = self.llm.prompt(
            prompt + "\nDo NOT edit any files; reply with the analysis only.")
        return resp.result if resp.success else ""


def _extract_code_block(text: str) -> str:
    """Return the largest fenced code block in *text* (unfenced whole text
    as a fallback when the model replied with bare Verilog)."""
    import re

    blocks = re.findall(r"```(?:\w+)?\n(.*?)```", text, flags=re.S)
    if blocks:
        return max(blocks, key=len).strip() + "\n"
    stripped = text.strip()
    if re.match(r"(module|`timescale|//)", stripped):
        return stripped + "\n"
    return ""


class ChiaImplement:
    """Cheap-model implementation burst, reply-mode.

    The model returns the COMPLETE candidate file in one fenced code block;
    the controller writes it into the sandbox. No agentic tool loop and no
    filesystem mutation by the model: the call is stateless and at-most-once,
    which sidesteps the empty-response fragility of long opencode agent
    sessions on large prompts.
    """

    def __init__(self, model: str, work_dir: Path, *, timeout: int = 1200,
                 log_dir: Path | None = None, retries: int = 1,
                 attempts: int = 1, provider_options: dict | None = None):
        self.attempts = max(1, attempts)
        self.llm = _make_llm(model, role="implement", timeout=timeout,
                             work_dir=work_dir, log_dir=log_dir,
                             system_message=("You are a Verilog generation "
                                             "engine. Always reply with "
                                             "exactly one complete fenced "
                                             "```verilog code block and "
                                             "nothing else."),
                             retries=retries,
                             provider_options=provider_options)

    def __call__(self, prompt: str) -> tuple[bool, str]:
        last = "implement call failed"
        for attempt in range(self.attempts):
            resp = self.llm.prompt(prompt)
            if resp.success:
                code = _extract_code_block(resp.result or "")
                if code:
                    return True, code
                last = "reply contained no verilog code block"
            else:
                last = resp.stderr or "implement call failed"
            if attempt + 1 < self.attempts:
                time.sleep(min(10 * (attempt + 1), 30))
        return False, last


# ---------------------------------------------------------------------------
# ChiaIterate: the transactional loop primitive
# ---------------------------------------------------------------------------


class ChiaIterate:
    """ChiaIterate { ChiaAdvise -> ChiaImplement -> ChiaCheckCondition -> jump }.

    One turn = one transaction:

        best checkpoint + feedback
          -> advise_fn(state)                     (per-turn advice)
          -> fresh sandbox copied from best       (or blank in generation mode)
          -> do_fn(state, sandbox)                (one bounded edit burst)
          -> check.evaluate(sandbox, best_level)  (deterministic gate ladder)
               ACCEPT  -> promote, stop
               IMPROVE -> promote if level advanced, else discard
               REJECT/RETRY/stall -> discard sandbox, keep best, loop
    """

    def __init__(self, run: RunPaths, *, advise_fn: Callable[[IterationState], str],
                 do_fn: Callable[[IterationState, Path], tuple[bool, str]],
                 check: ChiaCheckCondition, max_turns: int = 10,
                 on_event: Callable[[str], None] = print,
                 infra_backoff: Callable[[int], float] | None = None,
                 on_check: Callable[[int, str, CheckResult], None] | None = None,
                 on_attempt: Callable[[int, str, CheckResult, IterationState, Path], None]
                 | None = None,
                 on_checkpoint: Callable[[IterationState], None] | None = None):
        self.paths = run
        self.advise_fn = advise_fn
        self.do_fn = do_fn
        self.check = check
        self.max_turns = max_turns
        self.on_event = on_event
        self.infra_backoff = (infra_backoff if infra_backoff is not None
                              else (lambda attempt: min(5.0 * attempt, 30.0)))
        self.on_check = on_check
        self.on_attempt = on_attempt
        self.on_checkpoint = on_checkpoint

    def run(self, state: IterationState, resume: bool = False,
            use_lock: bool = True) -> IterationState:
        ctx = _run_lock(self.paths) if use_lock else _null_lock()
        with ctx:
            if resume:
                loaded = IterationState.load(self.paths.state_file)
                if loaded is None:
                    raise RuntimeError("resume refused: checkpoint state missing")
                state = loaded
                self.on_event(f"[resume] turn={state.turn} "
                              f"best_level={state.best_level} "
                              f"accepted={state.accepted}")
                if state.model_infra_blocked:
                    state.model_infra_blocked = ""
                    state.infra_attempts = 0
            self._recover_best(state)
            state.save(self.paths.state_file)
            self._notify_checkpoint(state)
            if state.pending_evaluation:
                status = self._resume_pending_evaluation(state)
                state.save(self.paths.state_file)
                self._notify_checkpoint(state)
                self.on_event(f"[resume evaluation] {status}")
                if state.pending_evaluation or state.accepted:
                    return state
            while state.turn < self.max_turns and not state.accepted:
                state.turn += 1
                state.save(self.paths.state_file)
                self._notify_checkpoint(state)
                turn = state.turn
                status = self._one_turn(state, turn)
                if status.startswith("evaluator infra blocked"):
                    # The generated candidate remains pending against the same
                    # gate. A later --resume continues it before any model call.
                    state.turn -= 1
                    state.save(self.paths.state_file)
                    self._notify_checkpoint(state)
                    self.on_event(f"[turn {turn}] {status} (turn not consumed)")
                    break
                if status.startswith(("advise infra failure",
                                      "implement infra failure")):
                    # Infrastructure failures must not consume an experiment
                    # turn; retry the turn with a bounded budget.
                    state.infra_attempts += 1
                    if state.infra_attempts <= 6:
                        state.turn -= 1
                        state.save(self.paths.state_file)
                        self._notify_checkpoint(state)
                        self.on_event(
                            f"[turn {turn}] {status} (not consumed; infra "
                            f"attempt {state.infra_attempts}/6)")
                        time.sleep(self.infra_backoff(state.infra_attempts))
                        continue
                    state.turn -= 1
                    state.model_infra_blocked = status
                    state.save(self.paths.state_file)
                    self._notify_checkpoint(state)
                    self.on_event(f"[turn {turn}] {status} (infra budget "
                                  f"exhausted; run paused, turn not consumed)")
                    break
                state.infra_attempts = 0
                state.save(self.paths.state_file)
                self._notify_checkpoint(state)
                self.on_event(f"[turn {turn}] {status}"
                              + (f" level={state.best_level}" if state.best_level else ""))
                if state.accepted:
                    break
        return state

    def _one_turn(self, state: IterationState, turn: int) -> str:
        base_workspace_hash = state.best_hash
        sandbox = self.paths.attempts / f"turn_{turn:04d}"
        _rmrf(sandbox)
        sandbox.mkdir(parents=True)
        if state.best_manifest:
            if self.paths.best.is_dir() and any(self.paths.best.iterdir()):
                shutil.copytree(self.paths.best, sandbox, dirs_exist_ok=True)
            else:
                self.on_event("[warn] best workspace missing; starting blank")
        ms = state.model_status.setdefault(str(turn), {})
        ms["base_workspace_hash"] = base_workspace_hash

        advice = ""
        try:
            advice = self.advise_fn(state) or ""
        except Exception as exc:
            ms["advise_error"] = str(exc)[:300]
            state.record({"turn": turn, "status": "advise_infra_failed"})
            return f"advise infra failure ({str(exc)[:80]})"
        ms["advise_chars"] = len(advice)
        (self.paths.artifacts / f"advice_turn{turn}.md").write_text(advice)
        state.advice = advice
        if turn == 1 and advice:
            state.architecture = advice

        try:
            ok, reason = self.do_fn(state, sandbox)
        except Exception as exc:
            ms["implement_error"] = str(exc)[:300]
            state.record({"turn": turn, "status": "implement_infra_failed"})
            _rmrf(sandbox)
            return f"implement infra failure ({str(exc)[:80]})"
        ms["implement_ok"] = ok
        ms["implement_reason"] = (reason or "")[:400]
        (self.paths.artifacts / f"implement_turn{turn}.txt").write_text(reason or "")

        manifest = workspace_manifest(sandbox)
        mhash = manifest_hash(manifest)
        ms["manifest_hash"] = mhash
        (self.paths.artifacts / f"manifest_turn{turn}.json").write_text(
            json.dumps(manifest, indent=1))
        if not ok:
            state.feedback = (
                "The previous implementation reply could not be used: "
                + (reason or "unknown reason")[:200]
                + ". Reply with exactly one complete fenced ```verilog code "
                  "block containing the entire file and nothing else.")
            state.record({"turn": turn, "status": "implement_failed",
                          "hash": mhash})
            _rmrf(sandbox)
            return "implement reported failure"
        if not manifest or (state.best_manifest and mhash == state.best_hash):
            state.feedback = (
                "Your candidate is identical to the current best. Change the "
                "design so the next gate can pass, and reply with the whole "
                "file in one fenced code block.")
            state.record({"turn": turn, "status": "stall", "hash": mhash})
            _rmrf(sandbox)
            return "stall (workspace unchanged)"

        # Retry only the failed gate against the SAME sandbox. Earlier passed
        # gates and their evidence remain bound into the accumulated detail.
        result = self._evaluate_with_retries(state, sandbox, turn=turn)
        check_path = self.paths.artifacts / f"check_turn{turn}.json"
        self._write_check(check_path, result)
        if result.verdict == VERDICT_RETRY:
            state.pending_evaluation = {
                "kind": "attempt",
                "turn": turn,
                "workspace_hash": mhash,
                "base_workspace_hash": base_workspace_hash,
                "start_gate": result.retry_gate_index,
                "detail": result.detail,
            }
            ms["transition_status"] = "infra_blocked"
            state.record({"turn": turn, "status": "evaluator_infra_blocked",
                          "level": result.level, "hash": mhash,
                          "base_hash": base_workspace_hash,
                          "infra_retries": state.infra_retries})
            return (f"evaluator infra blocked; candidate preserved at "
                    f"{sandbox.name}: {result.feedback[:120]}")
        return self._complete_attempt(
            state, turn, sandbox, manifest, mhash, result, check_path,
            base_workspace_hash)

    def _evaluate_with_retries(self, state: IterationState, sandbox: Path, *,
                               turn: int, start_gate: int = 0,
                               detail: dict | None = None) -> CheckResult:
        result: CheckResult | None = None
        gate_index = start_gate
        accumulated = dict(detail or {})
        for attempt in range(3):
            result = self.check.evaluate(
                sandbox, best_level=state.best_level,
                start_gate=gate_index, detail=accumulated)
            if result.verdict != VERDICT_RETRY:
                return result
            state.infra_retries += 1
            gate_index = (result.retry_gate_index
                          if result.retry_gate_index is not None else result.level)
            accumulated = result.detail
            self.on_event(f"[turn {turn}] infra retry {attempt + 1}/3: "
                          f"{result.feedback[:120]}")
        assert result is not None
        return result

    @staticmethod
    def _write_check(path: Path, result: CheckResult) -> None:
        _atomic_json(path, {
            "verdict": result.verdict, "level": result.level,
            "feedback": result.feedback, "detail": result.detail,
            "retry_gate_index": result.retry_gate_index,
        })

    def _resume_pending_evaluation(self, state: IterationState) -> str:
        pending = state.pending_evaluation
        if pending.get("kind") != "attempt":
            raise RuntimeError("resume refused: unknown pending evaluation kind")
        turn = int(pending["turn"])
        sandbox = self.paths.attempts / f"turn_{turn:04d}"
        manifest = workspace_manifest(sandbox)
        mhash = manifest_hash(manifest)
        if not manifest or mhash != pending.get("workspace_hash"):
            raise RuntimeError(
                "resume refused: pending evaluator sandbox missing or modified")
        result = self._evaluate_with_retries(
            state, sandbox, turn=turn,
            start_gate=int(pending.get("start_gate", 0)),
            detail=pending.get("detail", {}))
        check_path = self.paths.artifacts / f"check_turn{turn}.json"
        self._write_check(check_path, result)
        if result.verdict == VERDICT_RETRY:
            pending["start_gate"] = result.retry_gate_index
            pending["detail"] = result.detail
            state.record({"turn": turn, "status": "evaluator_infra_blocked",
                          "level": result.level, "hash": mhash,
                          "base_hash": pending.get("base_workspace_hash", ""),
                          "infra_retries": state.infra_retries})
            return f"still infra blocked: {result.feedback[:120]}"
        state.pending_evaluation = {}
        state.turn = turn
        return self._complete_attempt(
            state, turn, sandbox, manifest, mhash, result, check_path,
            pending.get("base_workspace_hash", ""))

    def _complete_attempt(self, state: IterationState, turn: int, sandbox: Path,
                          manifest: dict[str, str], mhash: str,
                          result: CheckResult, check_path: Path,
                          base_workspace_hash: str) -> str:
        ms = state.model_status.setdefault(str(turn), {})
        ms["verdict"] = result.verdict
        ms["level"] = result.level

        if result.verdict == VERDICT_REJECT:
            # Bind the feedback to the rejected WORKSPACE identity (candidate
            # file naming is composition-level) and preserve the sandbox so
            # the rejection is inspectable and repairable.
            state.feedback = (
                f"[feedback binds to REJECTED candidate workspace "
                f"sha256:{mhash} preserved at attempts/{sandbox.name}. The "
                f"next turn starts from incumbent workspace "
                f"sha256:{base_workspace_hash or '(blank)'}, so use this as "
                f"diagnostic evidence from a rejected sibling.]\n"
                + result.feedback)
            state.last_rejected_hash = mhash
            state.last_rejected_dir = sandbox.name
            ms["transition_status"] = "rejected"
            state.record({"turn": turn, "status": "rejected",
                          "level": result.level, "hash": mhash,
                          "base_hash": base_workspace_hash})
            state.save(self.paths.state_file)
            self._notify_attempt(turn, mhash, result, state, check_path)
            return f"rejected: {result.feedback[:120]}"
        if result.verdict == VERDICT_IMPROVE and result.level <= state.best_level:
            state.feedback = ("No milestone progress (level "
                              f"{result.level} == best {state.best_level}). "
                              + result.feedback)
            state.record({"turn": turn, "status": "no_progress",
                          "level": result.level, "hash": mhash,
                          "base_hash": base_workspace_hash})
            ms["transition_status"] = "no_progress"
            _rmrf(sandbox)
            state.save(self.paths.state_file)
            self._notify_attempt(turn, mhash, result, state, check_path)
            return "no milestone progress"
        prev = self._promote(sandbox)
        state.best_level = result.level
        state.best_hash = mhash
        state.best_manifest = manifest
        state.feedback = result.feedback
        if result.verdict == VERDICT_ACCEPT:
            state.accepted = True
            ms["transition_status"] = "accepted"
            state.record({"turn": turn, "status": "accepted", "level": result.level,
                          "hash": mhash, "base_hash": base_workspace_hash})
        else:
            ms["transition_status"] = "promoted"
            state.record({"turn": turn, "status": "promoted", "level": result.level,
                          "hash": mhash, "base_hash": base_workspace_hash})
        state.save(self.paths.state_file)
        _atomic_json(self.paths.artifacts / "best_snapshot.json", {
            "hash": mhash, "level": result.level, "verdict": result.verdict,
            "files": sorted(manifest), "ts": time.time()})
        self._notify_attempt(turn, mhash, result, state, check_path)
        _rmrf(prev)
        return "ACCEPTED" if state.accepted else f"promoted (level {result.level})"

    def _notify_attempt(self, turn: int, workspace_hash: str,
                        result: CheckResult, state: IterationState,
                        evidence_path: Path) -> None:
        if self.on_check is not None:
            self.on_check(turn, workspace_hash, result)
        if self.on_attempt is not None:
            self.on_attempt(turn, workspace_hash, result, state, evidence_path)

    def _notify_checkpoint(self, state: IterationState) -> None:
        if self.on_checkpoint is not None:
            self.on_checkpoint(state)

    def _promote(self, sandbox: Path) -> Path:
        """Install *sandbox* as best; return the backup path holding the old
        best. The caller MUST persist state, then _rmrf the returned path —
        the persisted state is what makes a crash in between recoverable."""
        prev = self.paths.root / "best.prev"
        _rmrf(prev)
        if self.paths.best.is_dir():
            self.paths.best.rename(prev)
        sandbox.rename(self.paths.best)
        return prev

    def _recover_best(self, state: IterationState) -> None:
        """Reconcile best/ with the persisted state after a crash.

        The persisted state is authoritative: if best/ matches state.best_hash,
        any leftover best.prev is stale and removed; otherwise best.prev holds
        the last checkpoint the state vouches for and is restored.
        """
        prev = self.paths.root / "best.prev"
        expected = state.best_hash
        current_hash = (manifest_hash(workspace_manifest(self.paths.best))
                         if self.paths.best.is_dir() else "")
        if expected and current_hash != expected and prev.is_dir():
            previous_hash = manifest_hash(workspace_manifest(prev))
            if previous_hash != expected:
                raise RuntimeError("resume refused: best and backup checkpoints mismatch")
            _rmrf(self.paths.best)
            prev.rename(self.paths.best)
            current_hash = previous_hash
        elif prev.is_dir():
            _rmrf(prev)
        if expected and current_hash != expected:
            raise RuntimeError("resume refused: best workspace missing or modified")
        if expected and state.best_manifest != workspace_manifest(self.paths.best):
            raise RuntimeError("resume refused: best manifest does not match checkpoint")
        if state.accepted and not expected:
            raise RuntimeError("resume refused: accepted state has no best checkpoint")


# ---------------------------------------------------------------------------
# ChiaMerge: thin clean-room composition
# ---------------------------------------------------------------------------


DEFAULT_ARCHITECTURE_PROMPT = """You are the architecture lead for a clean-room hardware merge.

Input designs (complete, verbatim):
{sources}

Behavioral contract that the merged design must satisfy:
{contract}

Task: derive a concrete strategy for ONE shared design that replaces both
input designs, preserving each design's externally observable behavior while
the selector input picks which design's workload runs, and meeting the
contract in every operating mode. The merged design must be ONE genuinely
shared datapath: instantiating both input designs and muxing between them is
NOT a merge and will be rejected. Produce:
1. The architecture: what is shared, what is per-mode, and why state
   ownership stays safe across modes.
2. A resource and schedule table: for each major resource or pipeline
   element, the state depths, counter periods, table addressing, and enable
   schedule in each mode.
3. The exact module interface and timing contract restated.
4. A ranked list of the riskiest parts of the design with the order you would
   implement and verify them.
Be specific: name signals, widths, and constants. Keep the entire plan under
12000 characters. Do NOT write RTL yet."""


DEFAULT_PER_TURN_PROMPT = """You are advising one implementation burst of the merged candidate design.

Architecture plan so far:
{architecture}

Progress: best attempt passed {best_level} of {total_gates} gates.
Evaluator feedback from the prior evaluated attempt (which may be a rejected
sibling rather than the current incumbent):
{feedback}

Decide the single highest-value instruction for this burst: which part of the
architecture to implement or fix next, and how to verify it against the
contract before moving on. Be concrete: name signals and expected behavior."""


DEFAULT_IMPLEMENT_PROMPT = """You are generating the merged candidate file `{candidate}`.

The current directory is an isolated attempt workspace. The pinned reference
designs' complete source code is inlined below.

You are writing ONE genuinely shared design that replaces BOTH input
designs (instantiating both designs and muxing outputs is not a merge).

Reference sources (complete, verbatim):
{sources}

The merged design you write must satisfy the contract exactly:
{contract}

Architecture plan to follow:
{architecture}

Advisor instruction for THIS burst:
{advice}

Evaluator feedback from the prior evaluated attempt. The current content below
is the actual incumbent and may differ from that rejected sibling:
{feedback}

Current content of `{candidate}` to repair or extend (may be empty):
{current}

Reply requirements:
- Reply with the COMPLETE content of `{candidate}` in a single ```verilog fenced code block, and nothing else.
- The file must be one self-contained Verilog-2005 file: the top module plus every submodule it needs.
- No $readmem, no initial/final blocks, no delays, no testbench constructs, no file I/O.
- Keep the module interface exactly as the contract requires.
- If the current content is empty, create the design; if it is non-empty, repair or extend it according to the feedback while keeping it syntactically complete.
- The reply MUST differ from the current content: an unchanged file is a wasted turn and will be discarded as a stall.
- After the code block, add one line starting with `SUMMARY:` describing what you changed."""


DEFAULT_PARENT_ARCHITECTURE_PROMPT = """You are the architecture lead optimizing an accepted merged hardware design.

An accepted parent candidate design already exists and passed all functional and physical acceptance gates:
- Placed cell area: ~288,000 um^2 (>32% reduction vs standalone sum)
- Timing met: positive setup/hold slack, TNS 0.00 ns
- DRC violations: 0
- Streaming power: ~40 mW

Input reference designs:
{sources}

Behavioral contract that the design must strictly maintain:
{contract}

Task: propose high-value power recovery optimizations for this accepted parent design:
1. Identify high-switching datapath sections (e.g. inactive butterfly stages or multiplier registers during mode 64).
2. Operand isolation: holding inputs stable when not actively computing.
3. Characterized integrated clock gating using sky130_fd_sc_hd__dlclkp_4 cells (NEVER combinational gating `clk & en`).
4. Ensure zero change to cycle-accurate streaming latency (exact 71/137 latency) and zero arithmetic deviation.
Keep the optimization plan concrete, targeted, and under 12000 characters."""


@dataclass
class MergePrompts:
    architecture: str = DEFAULT_ARCHITECTURE_PROMPT
    parent_architecture: str = DEFAULT_PARENT_ARCHITECTURE_PROMPT
    per_turn: str = DEFAULT_PER_TURN_PROMPT
    implement: str = DEFAULT_IMPLEMENT_PROMPT


def ChiaMerge(*, run_id: str, run_base: Path, inputs: dict[str, Path],
              contract: str, gates: Sequence[Callable[[Path], GateOutcome]],
              accept_level: int, adviser_model: str, implementer_model: str,
              prompts: MergePrompts | None = None,
              candidate_filename: str = "shared_candidate.v",
              turns: int = 12, advise_timeout: int = 1500,
              implement_timeout: int = 900, resume: bool = False,
              log_dir: Path | None = None, ablate_no_feedback: bool = False,
              llm_retries: int = 1, implement_attempts: int = 1,
              provider_options: dict | None = None,
              mode: str = MODE_DISCOVERY,
              parent_candidate: Path | None = None,
              config_hash: str = "",
              on_check: Callable[[int, str, CheckResult], None] | None = None,
              on_attempt: Callable[[int, str, CheckResult, IterationState, Path], None]
              | None = None,
              on_start: Callable[[RunPaths, IterationState], IterationState | None]
              | None = None,
              on_checkpoint: Callable[[IterationState], None] | None = None,
              forbidden_candidate_hashes: Sequence[str] = (),
              _adviser_factory=None, _implementer_factory=None) -> IterationState:
    """Clean-room merge of the input designs into one shared PE, judged.

    Starts from NOTHING but the pinned input files and the contract. The first
    ``ChiaAdvise`` derives the sharing architecture; every turn then runs
    ``ChiaAdvise -> ChiaImplement -> ChiaCheckCondition`` inside one
    ``ChiaIterate`` until the gate ladder accepts or ``turns`` is exhausted.
    """
    if mode not in (MODE_DISCOVERY, MODE_PARENT):
        raise ValueError(f"unknown campaign mode: {mode}")
    if mode == MODE_DISCOVERY and parent_candidate is not None:
        raise ValueError("MergeDiscovery cannot receive a parent candidate")
    if mode == MODE_PARENT and parent_candidate is None:
        raise ValueError("ParentOptimization requires a parent candidate")
    run_root = Path(run_base) / run_id
    if resume:
        if not run_root.is_dir() or not (run_root / "artifacts" / "state.json").is_file():
            raise RuntimeError("resume refused: run checkpoint missing")
    elif run_root.exists() and any(run_root.iterdir()):
        raise RuntimeError("fresh run refused: run id already contains artifacts")
    if _adviser_factory is None or _implementer_factory is None:
        import ray

        ray.init(address="auto", ignore_reinit_error=True)

    run = RunPaths.create(run_root)
    tpl = prompts or MergePrompts()

    new_hashes = {name: _sha256(Path(src)) for name, src in inputs.items()}
    hashes_file = run.artifacts / "input_hashes.json"

    with _run_lock(run):
        if resume:
            verify_resume_inputs(run.inputs, hashes_file,
                                 run.inputs / "CONTRACT.md", new_hashes, contract)
        else:
            for name, src in inputs.items():
                shutil.copy2(src, run.inputs / Path(src).name)
            (run.artifacts / "input_hashes.json").write_text(
                json.dumps(new_hashes, indent=1))
            (run.inputs / "CONTRACT.md").write_text(contract)
        inputs_text = "\n".join(f"- {name}: ./inputs/{Path(src).name}"
                                for name, src in inputs.items())
        sources_text = "\n\n".join(
            f"===== ./inputs/{Path(src).name} =====\n"
            + (run.inputs / Path(src).name).read_text()
            for _, src in inputs.items())

        state = IterationState.load(run.state_file) if resume else None
        if state is None:
            state = IterationState(mode=mode, config_hash=config_hash)
            if parent_candidate is not None:
                parent_candidate = Path(parent_candidate)
                if not parent_candidate.is_file():
                    raise FileNotFoundError(parent_candidate)
                _rmrf(run.best)
                run.best.mkdir(parents=True, exist_ok=True)
                shutil.copy2(parent_candidate, run.best / candidate_filename)
                state.parent_hash = _sha256(parent_candidate)
                state.best_manifest = workspace_manifest(run.best)
                state.best_hash = manifest_hash(state.best_manifest)
        else:
            if state.mode != mode:
                raise RuntimeError("resume refused: campaign mode changed")
            if config_hash and state.config_hash != config_hash:
                raise RuntimeError("resume refused: campaign configuration changed")
            if mode == MODE_PARENT and parent_candidate is not None:
                if _sha256(Path(parent_candidate)) != state.parent_hash:
                    raise RuntimeError("resume refused: parent candidate changed")

        if on_start is not None:
            replacement = on_start(run, state)
            if replacement is not None:
                state = replacement
        state.save(run.state_file)

        adviser_work_dir = run.root / "adviser_workspace"
        _rmrf(adviser_work_dir)
        adviser_work_dir.mkdir(parents=True, exist_ok=True)
        if _adviser_factory is not None:
            adviser = _adviser_factory(model=adviser_model,
                                       work_dir=adviser_work_dir,
                                       timeout=advise_timeout, log_dir=log_dir)
        else:
            adviser = ChiaAdvise(
                adviser_model, adviser_work_dir, timeout=advise_timeout,
                log_dir=log_dir, retries=llm_retries,
                provider_options=provider_options)
        gates = list(gates)
        total_gates = len(gates)

        def advise_fn(st: IterationState) -> str:
            if ablate_no_feedback and st.turn > 1:
                st.feedback = ""
                return ""
            if st.turn == 1:
                arch_prompt = (tpl.parent_architecture
                               if st.mode == MODE_PARENT and hasattr(tpl, "parent_architecture")
                               else tpl.architecture)
                prompt = arch_prompt.format(inputs=inputs_text,
                                            sources=sources_text,
                                            contract=contract)
            else:
                prompt = tpl.per_turn.format(
                    architecture=st.architecture[:12000] or "(none yet)",
                    best_level=st.best_level, total_gates=total_gates,
                    feedback=st.feedback[:4000] or "(first attempt)")
            return adviser(prompt)

        def do_fn(st: IterationState, sandbox: Path) -> tuple[bool, str]:
            sandbox_inputs = sandbox / "inputs"
            sandbox_inputs.mkdir(exist_ok=True)
            for name, src in inputs.items():
                pinned = run.inputs / Path(src).name
                shutil.copy2(pinned, sandbox_inputs / Path(src).name)
            (sandbox_inputs / "CONTRACT.md").write_text(contract)
            _atomic_json(run.artifacts / f"model_visible_turn{st.turn}.json", {
                "mode": st.mode,
                "manifest_hash": manifest_hash(workspace_manifest(sandbox)),
                "files": sorted(workspace_manifest(sandbox)),
            })
            best_file = run.best / candidate_filename
            current = best_file.read_text() if best_file.is_file() else ""
            if _implementer_factory is not None:
                implementer = _implementer_factory(
                    model=implementer_model, work_dir=sandbox,
                    timeout=implement_timeout, log_dir=log_dir)
            else:
                implementer = ChiaImplement(implementer_model, sandbox,
                                            timeout=implement_timeout,
                                            log_dir=log_dir,
                                            retries=llm_retries,
                                            attempts=implement_attempts,
                                            provider_options=provider_options)
            prompt = tpl.implement.format(
                candidate=candidate_filename, sources=sources_text,
                contract=contract,
                architecture=st.architecture[:12000] or "(derive it yourself from the sources)",
                advice=st.advice[:4000] or "Continue the plan; no extra instruction this turn.",
                feedback=("" if ablate_no_feedback
                          else (st.feedback[:4000] or "No previous attempt: start from scratch.")),
                current=current[:60000])
            ok, out = implementer(prompt)
            if ok:
                output_hash = hashlib.sha256(out.encode("utf-8")).hexdigest()
                if output_hash in set(forbidden_candidate_hashes):
                    return False, "candidate matches a forbidden historical artifact"
                (sandbox / candidate_filename).write_text(out)
                summary = ""
                for line in out.splitlines():
                    if line.startswith("SUMMARY:"):
                        summary = line
                        break
                return True, summary or "candidate written from model reply"
            return ok, out

        check = ChiaCheckCondition(gates, accept_level=accept_level)
        if mode == MODE_PARENT and not state.parent_attested:
            pending_parent = state.pending_evaluation
            if pending_parent and pending_parent.get("kind") != "parent":
                raise RuntimeError("resume refused: unexpected pending evaluation")
            start_gate = int(pending_parent.get("start_gate", 0))
            accumulated = pending_parent.get("detail", {})
            parent_result: CheckResult | None = None
            for attempt in range(3):
                parent_result = check.evaluate(
                    run.best, best_level=0, start_gate=start_gate,
                    detail=accumulated)
                if parent_result.verdict != VERDICT_RETRY:
                    break
                state.infra_retries += 1
                start_gate = (parent_result.retry_gate_index
                              if parent_result.retry_gate_index is not None
                              else parent_result.level)
                accumulated = parent_result.detail
            assert parent_result is not None
            parent_check = run.artifacts / "check_parent.json"
            _atomic_json(parent_check, {
                "verdict": parent_result.verdict,
                "level": parent_result.level,
                "feedback": parent_result.feedback,
                "detail": parent_result.detail,
                "retry_gate_index": parent_result.retry_gate_index,
            })
            if parent_result.verdict == VERDICT_RETRY:
                state.pending_evaluation = {
                    "kind": "parent", "turn": 0,
                    "workspace_hash": state.best_hash,
                    "start_gate": parent_result.retry_gate_index,
                    "detail": parent_result.detail,
                }
                state.record({"turn": 0,
                              "status": "parent_attestation_infra_blocked",
                              "level": parent_result.level,
                              "hash": state.best_hash})
                state.save(run.state_file)
                if on_checkpoint is not None:
                    on_checkpoint(state)
                return state
            if parent_result.verdict != VERDICT_ACCEPT:
                raise RuntimeError(
                    "parent candidate failed mandatory evaluator: "
                    + parent_result.feedback[:500])
            state.pending_evaluation = {}
            state.best_level = parent_result.level
            state.parent_attested = True
            state.model_status.setdefault("0", {}).update({
                "base_workspace_hash": "",
                "transition_status": "parent_attested",
            })
            state.record({"turn": 0, "status": "parent_attested",
                          "level": parent_result.level,
                          "hash": state.best_hash})
            state.save(run.state_file)
            if on_check is not None:
                on_check(0, state.best_hash, parent_result)
            if on_attempt is not None:
                on_attempt(0, state.best_hash, parent_result, state, parent_check)
        iterate = ChiaIterate(run, advise_fn=advise_fn, do_fn=do_fn, check=check,
                              max_turns=turns, on_check=on_check,
                              on_attempt=on_attempt,
                              on_checkpoint=on_checkpoint)
        return iterate.run(state, resume=resume, use_lock=False)
