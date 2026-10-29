"""One transactional loop that discovers a merge and optimizes its power.

The controller starts with pinned references only.  Every candidate therefore
passes through the same correctness gates and measured Pareto feedback; there
is no hidden Merge-then-PowerSave phase.
"""
from __future__ import annotations

import hashlib
import json
import math
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from chia_merge import (GateOutcome, ChiaCheckCondition, RunPaths,
                        VERDICT_ACCEPT, VERDICT_REJECT, VERDICT_RETRY,
                        _null_lock, _rmrf, _run_lock, workspace_manifest)
from chia_power_save import (PowerObjectives, VERDICT_DOMINATED,
                             VERDICT_PARETO, VERDICT_TARGET, dominates,
                             kill_worker_processes, meets_targets)


@dataclass
class JointState:
    turn: int = 0
    accepted: bool = False
    stop_reason: str = ""
    candidates_generated: int = 0
    physical_runs: int = 0
    best_hash: str = ""              # candidate-file SHA-256, always
    best_manifest: dict = field(default_factory=dict)
    best_level: int = 0
    best_metrics: dict = field(default_factory=dict)
    best_verdict: str = ""
    archive: list = field(default_factory=list)
    hypothesis: str = ""
    advice: str = ""
    feedback: str = ""
    last_rejected_hash: str = ""
    last_rejected_dir: str = ""
    history: list = field(default_factory=list)
    model_status: dict = field(default_factory=dict)

    def record(self, entry: dict) -> None:
        self.history.append({"ts": time.time(), **entry})

    def save(self, path: Path) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.__dict__, indent=1))
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> "JointState | None":
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        allowed = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in allowed})


def _candidate_hash(ws: Path, name: str) -> str:
    p = ws / name
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else ""


def _finite_metrics(raw: dict, names: tuple[str, ...]) -> dict | None:
    out = {n: raw[n] for n in names if n in raw}
    zero_allowed = {"setup_violation_ns", "tns_violation_ns"}
    if (len(out) != len(names)
            or any(isinstance(v, bool) or not isinstance(v, (int, float))
                   or not math.isfinite(float(v)) or float(v) < 0
                   or (float(v) == 0 and name not in zero_allowed)
                   for name, v in out.items())):
        return None
    return out


class ChiaMergePowerSave:
    """Clean-room merge/power search with one ordered evaluator per turn."""

    def __init__(self, run: RunPaths, *, candidate_filename: str,
                 cheap_gates: list[Callable[[Path], GateOutcome]],
                 physical_gate: Callable[[Path], GateOutcome],
                 objectives: PowerObjectives,
                 do_fn: Callable[[JointState, Path], tuple[bool, str]],
                 advise_fn: Callable[[JointState], str] | None = None,
                 hard_constraints: tuple[Callable[[dict], str | None], ...] = (),
                 max_candidates: int = 8, max_physical: int = 3,
                 protected_files: dict[str, str] | None = None,
                 config_fingerprint: dict | None = None,
                 worker_patterns: tuple[str, ...] = (),
                 on_event: Callable[[str], None] = print):
        if not config_fingerprint:
            raise ValueError("config_fingerprint must be non-empty")
        if not objectives.names or len(set(objectives.names)) != len(objectives.names):
            raise ValueError("objective names must be nonempty and unique")
        if max_candidates < 1 or max_physical < 1:
            raise ValueError("candidate and physical budgets must be positive")
        self.paths, self.candidate_filename = run, candidate_filename
        self.cheap_check = ChiaCheckCondition(cheap_gates, accept_level=len(cheap_gates))
        self.physical_gate, self.objectives, self.do_fn = physical_gate, objectives, do_fn
        self.advise_fn, self.hard_constraints = advise_fn, hard_constraints
        self.max_candidates, self.max_physical = max_candidates, max_physical
        self.protected_files, self.config_fingerprint = protected_files or {}, config_fingerprint
        self.worker_patterns, self.on_event = worker_patterns, on_event

    def run(self, state: JointState | None = None, *, resume: bool = False,
            use_lock: bool = True) -> JointState:
        state = state or JointState()
        ctx = _run_lock(self.paths) if use_lock else _null_lock()
        with ctx:
            fp = self.paths.artifacts / "config_fingerprint.json"
            if resume:
                try:
                    recorded = json.loads(fp.read_text())
                except (OSError, json.JSONDecodeError):
                    recorded = None
                if recorded != self.config_fingerprint:
                    state.stop_reason = "resume refused: configuration fingerprint changed or missing"
                    return state
                loaded = JointState.load(self.paths.state_file)
                if loaded is None:
                    state.stop_reason = "resume refused: missing or malformed state"
                    return state
                state = loaded
            else:
                if self.paths.state_file.exists():
                    state.stop_reason = "fresh run refused: state already exists; use resume"
                    return state
                fp.write_text(json.dumps(self.config_fingerprint, indent=1))
            self._recover_best(state)
            self._verify_protected(state)
            state.save(self.paths.state_file)
            while (state.turn < self.max_candidates and not state.accepted
                   and not state.stop_reason and state.physical_runs < self.max_physical):
                state.turn += 1
                state.save(self.paths.state_file)
                self._one_turn(state, state.turn)
                state.save(self.paths.state_file)
        return state

    def _verify_protected(self, state: JointState) -> None:
        for rel, expected in self.protected_files.items():
            p = self.paths.root / rel
            actual = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "MISSING"
            if actual != expected:
                state.stop_reason = f"protected hash changed: {rel}"

    def _recover_best(self, state: JointState) -> None:
        """Restore the persisted candidate by candidate-file SHA after a crash."""
        if not state.best_hash:
            return
        if (_candidate_hash(self.paths.best, self.candidate_filename) == state.best_hash
                and workspace_manifest(self.paths.best) == state.best_manifest):
            return
        for attempt in sorted(self.paths.attempts.glob("turn_*")):
            if (_candidate_hash(attempt, self.candidate_filename) == state.best_hash
                    and workspace_manifest(attempt) == state.best_manifest):
                _rmrf(self.paths.best)
                shutil.copytree(attempt, self.paths.best)
                state.best_manifest = workspace_manifest(self.paths.best)
                return
        state.stop_reason = "resume refused: promoted candidate cannot be recovered"

    def _one_turn(self, state: JointState, turn: int) -> None:
        sandbox = self.paths.attempts / f"turn_{turn:04d}"
        _rmrf(sandbox); sandbox.mkdir(parents=True)
        if self.paths.best.is_dir():
            shutil.copytree(self.paths.best, sandbox, dirs_exist_ok=True)
        ms = state.model_status.setdefault(str(turn), {})
        if self.advise_fn:
            try:
                state.advice = self.advise_fn(state) or ""
                state.hypothesis = state.advice.splitlines()[0][:200] if state.advice else ""
                (self.paths.artifacts / f"advice_turn{turn}.md").write_text(state.advice)
            except Exception as exc:
                state.record({"turn": turn, "status": "advise_infra_failed", "error": str(exc)[:200]})
                state.stop_reason = f"adviser failed: {str(exc)[:200]}"
                _rmrf(sandbox); return
        try:
            ok, reason = self.do_fn(state, sandbox)
        except Exception as exc:
            state.record({"turn": turn, "status": "implement_infra_failed", "error": str(exc)[:200]})
            state.stop_reason = f"implementer failed: {str(exc)[:200]}"
            _rmrf(sandbox); return
        state.candidates_generated += 1
        self._verify_protected(state)
        if state.stop_reason:
            return
        ms.update({"implement_ok": ok, "implement_reason": (reason or "")[:400]})
        (self.paths.artifacts / f"implement_turn{turn}.txt").write_text(reason or "")
        cand_hash = _candidate_hash(sandbox, self.candidate_filename)
        if not ok or not cand_hash:
            state.record({"turn": turn, "status": "implement_failed"}); _rmrf(sandbox); return
        if cand_hash == state.best_hash:
            state.record({"turn": turn, "status": "stall", "hash": cand_hash}); _rmrf(sandbox); return
        state.last_rejected_hash, state.last_rejected_dir = cand_hash, sandbox.name
        result = self.cheap_check.evaluate(sandbox, best_level=state.best_level)
        (self.paths.artifacts / f"check_turn{turn}.json").write_text(json.dumps(result.__dict__, indent=1))
        ms.update({"cheap_verdict": result.verdict, "cheap_level": result.level})
        if result.verdict != VERDICT_ACCEPT:
            state.feedback = result.feedback
            state.record({"turn": turn, "status": "retry" if result.verdict == VERDICT_RETRY else "invalid", "level": result.level})
            state.last_rejected_hash, state.last_rejected_dir = cand_hash, sandbox.name
            return
        if self.worker_patterns:
            kill_worker_processes(self.worker_patterns, self.paths.artifacts / f"worker_kill_turn{turn}.json")
        state.physical_runs += 1; state.save(self.paths.state_file)
        try:
            phys = self.physical_gate(sandbox)
        except Exception as exc:
            phys = GateOutcome("physical", False, note=str(exc)[:200], retry=True)
        (self.paths.artifacts / f"physical_turn{turn}.json").write_text(
            json.dumps({"passed": phys.passed, "retry": phys.retry,
                        "note": phys.note, "detail": phys.detail}, indent=1))
        if phys.retry:
            state.physical_runs -= 1
            state.feedback = f"physical retry: {phys.note}"
            state.record({"turn": turn, "status": "physical_retry"}); return
        if not phys.passed:
            state.feedback = f"physical gate failed: {phys.note}; measured detail: {json.dumps(phys.detail, sort_keys=True)}"
            state.record({"turn": turn, "status": "physical_failed", "metrics": phys.detail}); return
        metrics = _finite_metrics(phys.detail, self.objectives.names)
        violation = None
        if metrics is not None:
            for constraint in self.hard_constraints:
                violation = constraint(metrics)
                if violation:
                    break
        if metrics is None or violation:
            state.feedback = (f"constraint violated: {violation}; measured objectives: "
                              + json.dumps(metrics, sort_keys=True)) if violation else "physical objectives missing/non-finite"
            state.record({"turn": turn, "status": "regression", "metrics": metrics or {}}); return
        equal = any(p.get("metrics", {}) == metrics for p in state.archive)
        dominated = any(dominates(p.get("metrics", {}), metrics, self.objectives.names)
                        for p in state.archive)
        verdict = (VERDICT_DOMINATED if equal or dominated else
                   VERDICT_TARGET if self.objectives.targets and meets_targets(metrics, self.objectives.targets)
                   else VERDICT_PARETO)
        state.record({"turn": turn, "status": verdict.lower(), "metrics": metrics, "hash": cand_hash})
        if verdict in (VERDICT_PARETO, VERDICT_TARGET):
            state.archive = [p for p in state.archive if not dominates(metrics, p.get("metrics", {}), self.objectives.names)]
            state.archive.append({"hash": cand_hash, "turn": turn, "verdict": verdict, "metrics": metrics})
            _rmrf(self.paths.best)
            shutil.copytree(sandbox, self.paths.best)
            state.best_hash, state.best_manifest = cand_hash, workspace_manifest(self.paths.best)
            state.best_metrics, state.best_verdict, state.best_level = metrics, verdict, result.level
            state.last_rejected_hash, state.last_rejected_dir = "", ""
            state.feedback = ", ".join(f"{k}={v}" for k, v in metrics.items())
            if verdict == VERDICT_TARGET: state.accepted = True
        else:
            state.feedback = "candidate dominated by archived measured point"
        (self.paths.artifacts / "pareto.json").write_text(json.dumps(state.archive, indent=1))

    def verify_final(self, state: JointState) -> dict:
        report = {"verified": False, "best_hash": state.best_hash, "checks": {}}
        try:
            p = self.paths.best / self.candidate_filename
            actual = _candidate_hash(self.paths.best, self.candidate_filename)
            report["checks"]["candidate_hash"] = bool(state.best_hash and actual == state.best_hash)
            report["checks"]["protected_inputs"] = all(
                (self.paths.root / rel).is_file()
                and hashlib.sha256((self.paths.root / rel).read_bytes()).hexdigest() == expected
                for rel, expected in self.protected_files.items())
            if not all(report["checks"].values()):
                raise RuntimeError("candidate identity or protected inputs changed")
            cheap = self.cheap_check.evaluate(self.paths.best)
            report["checks"]["cheap_accept"] = cheap.verdict == VERDICT_ACCEPT
            if report["checks"]["cheap_accept"]:
                if self.worker_patterns:
                    kill_worker_processes(self.worker_patterns,
                                          self.paths.artifacts / "worker_kill_final.json")
                phys = self.physical_gate(self.paths.best)
                report["checks"]["physical_passed"] = phys.passed and not phys.retry
                metrics = _finite_metrics(phys.detail, self.objectives.names) if phys.passed else None
                report["checks"]["objectives_finite"] = metrics is not None
                violations = []
                if metrics is not None:
                    violations = [v for c in self.hard_constraints if (v := c(metrics))]
                report["checks"]["constraints_hold"] = not violations
                report["metrics"] = metrics or {}
                report["checks"]["metrics_agree"] = metrics is not None and all(float(metrics[n]) == float(state.best_metrics.get(n)) for n in self.objectives.names)
            report["verified"] = bool(report["checks"]) and all(report["checks"].values())
        except Exception as exc:
            report["reason"] = str(exc)[:200]
        (self.paths.artifacts / "final_repeat.json").write_text(json.dumps(report, indent=1))
        return report

