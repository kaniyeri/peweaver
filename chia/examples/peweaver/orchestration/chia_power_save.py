#!/usr/bin/env python3
"""ChiaPowerSave: domain-neutral bounded power optimization of an accepted
engineering artifact (plan workstream 5).

Same transactional control semantics as ChiaMerge (isolated attempts, ordered
fail-closed gates, deterministic promotion/rollback, resumable best-state
recovery), specialized for correctness-preserving Pareto optimization:

    incumbent + measured feedback
      -> advise_fn(state)                     one atomic hypothesis
      -> fresh sandbox copied from incumbent
      -> do_fn(state, sandbox)                one bounded patch burst
      -> cheap gate cascade (hard gates)      INVALID on first failure
      -> [if survivor] kill workers; physical gate -> measured objectives
      -> classify: INVALID / REGRESSION / DOMINATED / PARETO / TARGET
      -> promote on PARETO/TARGET (same-level comparison via dominance)

No weighted score: correctness, timing/DRC/activity validity, and hard
constraints gate first; objectives are minimized under Pareto dominance.
The archive (not a scalar best) is the result.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from chia_merge import (VERDICT_ACCEPT, VERDICT_IMPROVE, VERDICT_REJECT,
                        VERDICT_RETRY, ChiaCheckCondition, GateOutcome,
                        RunPaths, _null_lock, _rmrf, _run_lock,
                        manifest_hash, verify_resume_inputs,
                        workspace_manifest)

VERDICT_INVALID = "INVALID"
VERDICT_REGRESSION = "REGRESSION"
VERDICT_DOMINATED = "DOMINATED"
VERDICT_PARETO = "PARETO"
VERDICT_TARGET = "TARGET"


@dataclass
class PowerObjectives:
    """Measured objectives (all minimized) plus strict TARGET thresholds."""
    names: tuple[str, ...]
    targets: dict[str, float] = field(default_factory=dict)
    physical_trigger_frac: float = 0.0   # min relative proxy improvement
                                         # required before a full physical run


@dataclass
class PowerSaveState:
    turn: int = 0
    accepted: bool = False
    stop_reason: str = ""
    candidates_generated: int = 0
    physical_runs: int = 0
    best_hash: str = ""
    best_manifest: dict = field(default_factory=dict)
    best_metrics: dict = field(default_factory=dict)
    best_verdict: str = ""
    archive: list = field(default_factory=list)
    consecutive_dominated: int = 0
    hypothesis: str = ""
    advice: str = ""
    feedback: str = ""
    history: list = field(default_factory=list)
    model_status: dict = field(default_factory=dict)

    def record(self, entry: dict) -> None:
        self.history.append({"ts": time.time(), **entry})

    def save(self, state_file: Path) -> None:
        tmp = state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps({
            "turn": self.turn, "accepted": self.accepted,
            "stop_reason": self.stop_reason,
            "candidates_generated": self.candidates_generated,
            "physical_runs": self.physical_runs,
            "best_hash": self.best_hash, "best_manifest": self.best_manifest,
            "best_metrics": self.best_metrics,
            "best_verdict": self.best_verdict, "archive": self.archive,
            "consecutive_dominated": self.consecutive_dominated,
            "hypothesis": self.hypothesis, "advice": self.advice,
            "feedback": self.feedback, "history": self.history,
            "model_status": self.model_status}, indent=1))
        os.replace(tmp, state_file)

    @classmethod
    def load(cls, state_file: Path) -> "PowerSaveState | None":
        if not state_file.is_file():
            return None
        try:
            d = json.loads(state_file.read_text())
        except json.JSONDecodeError:
            return None
        st = cls()
        for f in ("turn", "accepted", "stop_reason", "candidates_generated",
                  "physical_runs", "best_hash", "best_manifest",
                  "best_metrics", "best_verdict", "archive",
                  "consecutive_dominated", "hypothesis", "advice",
                  "feedback", "history", "model_status"):
            if f in d:
                setattr(st, f, d[f])
        return st


def dominates(a: dict, b: dict, names: tuple[str, ...]) -> bool:
    """True if point *a* Pareto-dominates *b* on *names* (all minimized)."""
    if any(n not in a or n not in b for n in names):
        return False
    le = all(float(a[n]) <= float(b[n]) for n in names)
    lt = any(float(a[n]) < float(b[n]) for n in names)
    return le and lt


def meets_targets(metrics: dict, targets: dict[str, float]) -> bool:
    return all(n in metrics and float(metrics[n]) <= t
               for n, t in targets.items())


def _ancestry_pids() -> set[int]:
    """PIDs on this process's ancestry chain (self .. init)."""
    pids: set[int] = set()
    pid = os.getpid()
    for _ in range(64):
        pids.add(pid)
        try:
            status = Path(f"/proc/{pid}/status").read_text()
        except OSError:
            break
        row = next((ln for ln in status.splitlines()
                    if ln.startswith("PPid:")), None)
        if row is None:
            break
        try:
            pid = int(row.split()[1])
        except (IndexError, ValueError):
            break
        if pid <= 1:
            break
    return pids


def _proc_uid(pid_dir: Path) -> int | None:
    """Real UID from /proc/<pid>/status (loginuid is often unset)."""
    try:
        for line in (pid_dir / "status").read_text().splitlines():
            if line.startswith("Uid:"):
                return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return None


def kill_worker_processes(patterns: tuple[str, ...] = ("opencode", "gemini"),
                          log_file: Path | None = None) -> list[int]:
    """Controller action: terminate model-worker processes before hidden or
    physical evaluation. Scans /proc for this UID's processes whose cmdline
    matches a pattern and kills their process groups (TERM, short wait, then
    KILL for survivors).

    Safety rails: never kills this process, any ancestry member, or any
    process group containing one; disabled entirely when
    PEWEAVER_DISABLE_WORKER_KILL=1. Model-free.
    """
    import signal as _signal
    if os.environ.get("PEWEAVER_DISABLE_WORKER_KILL") == "1":
        if log_file is not None:
            log_file.write_text(json.dumps(
                {"ts": time.time(), "killed_process_groups": [],
                 "disabled": True}, indent=1))
        return []
    protected_pids = _ancestry_pids()
    protected_pgids: set[int] = set()
    for pid in protected_pids:
        try:
            protected_pgids.add(os.getpgid(pid))
        except OSError:
            continue
    killed: list[int] = []
    me = os.getuid()
    mypid = os.getpid()
    for pid_dir in Path("/proc").iterdir():
        if not pid_dir.name.isdigit():
            continue
        pid = int(pid_dir.name)
        if pid == mypid or pid in protected_pids:
            continue
        try:
            uid = _proc_uid(pid_dir)
            cmdline = (pid_dir / "cmdline").read_bytes()
            pgid = os.getpgid(pid)
        except (OSError, ValueError, PermissionError, ProcessLookupError):
            continue
        if not cmdline or pgid in protected_pgids or pgid in killed:
            continue
        if uid is not None and uid != me:
            continue
        text = cmdline.decode("utf-8", "replace").replace("\x00", " ")
        if not any(p in text for p in patterns):
            continue
        # re-verify immediately before signaling: no protected member in group
        try:
            members = [int(d.name) for d in Path("/proc").iterdir()
                       if d.name.isdigit()]
            if any(m in protected_pids and os.getpgid(m) == pgid
                   for m in members):
                continue
        except (OSError, ProcessLookupError):
            continue
        try:
            os.killpg(pgid, _signal.SIGTERM)
            killed.append(pgid)
        except (ProcessLookupError, PermissionError, OSError):
            continue
    if killed:
        time.sleep(2.0)
        for pgid in list(killed):
            try:
                os.killpg(pgid, 0)
            except ProcessLookupError:
                continue
            except PermissionError:
                continue
            try:
                os.killpg(pgid, _signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
    if log_file is not None:
        log_file.write_text(json.dumps(
            {"ts": time.time(), "killed_process_groups": sorted(set(killed))},
            indent=1))
    return killed


class ChiaPowerSave:
    """ChiaPowerSave over ChiaIterate-style transactional control semantics.

    Gates are split into a cheap cascade (run every candidate) and one full
    physical gate (run only for proxy-promising survivors, budget-bounded).
    """

    def __init__(self, run: RunPaths, *, incumbent: Path,
                 candidate_filename: str,
                 cheap_gates: list[Callable[[Path], GateOutcome]],
                 physical_gate: Callable[[Path], GateOutcome],
                 objectives: PowerObjectives,
                 hard_constraints: tuple[Callable[[dict], str | None], ...] = (),
                 advise_fn: Callable[[PowerSaveState], str] | None = None,
                 do_fn: Callable[[PowerSaveState, Path], tuple[bool, str]],
                 max_candidates: int = 16, max_physical: int = 5,
                 review_after_dominated: int = 3,
                 worker_patterns: tuple[str, ...] = ("opencode", "gemini"),
                 protected_files: dict[str, str] | None = None,
                 config_fingerprint: dict | None = None,
                 on_event: Callable[[str], None] = print):
        self.paths = run
        self.incumbent = Path(incumbent)
        self.candidate_filename = candidate_filename
        self.cheap_check = ChiaCheckCondition(cheap_gates, accept_level=len(cheap_gates))
        self.physical_gate = physical_gate
        self.objectives = objectives
        self.hard_constraints = hard_constraints
        self.advise_fn = advise_fn
        self.do_fn = do_fn
        self.max_candidates = max_candidates
        self.max_physical = max_physical
        self.review_after_dominated = review_after_dominated
        self.worker_patterns = worker_patterns
        self.protected_files = protected_files or {}
        if not config_fingerprint:
            raise ValueError(
                "ChiaPowerSave requires a non-empty config_fingerprint "
                "(gates/objectives/constraints); an absent fingerprint makes "
                "resume identity unverifiable")
        self.config_fingerprint = config_fingerprint
        self.on_event = on_event

    # ------------------------------------------------------------------
    def run(self, state: PowerSaveState | None = None,
            resume: bool = False, use_lock: bool = True) -> PowerSaveState:
        state = state or PowerSaveState()
        ctx = _run_lock(self.paths) if use_lock else _null_lock()
        with ctx:
            if resume:
                fp_file = self.paths.artifacts / "config_fingerprint.json"
                if self.config_fingerprint:
                    if not fp_file.is_file():
                        self.on_event("[STOP] resume refused: no recorded "
                                      "configuration fingerprint")
                        state.stop_reason = ("resume refused: config "
                                             "fingerprint missing")
                        return state
                    import hashlib
                    recorded = json.loads(fp_file.read_text())
                    if recorded != self.config_fingerprint:
                        self.on_event("[STOP] resume refused: configuration "
                                      "(gates/objectives/constraints) changed")
                        state.stop_reason = ("resume refused: config "
                                             "fingerprint changed")
                        return state
                loaded = PowerSaveState.load(self.paths.state_file)
                if loaded is not None:
                    state = loaded
                    self.on_event(f"[resume] turn={state.turn} "
                                  f"best_verdict={state.best_verdict} "
                                  f"archive={len(state.archive)}")
            self._recover_best(state)
            if not state.best_manifest:
                self._seed_incumbent(state)
            self._verify_protected(state)
            if self.config_fingerprint and not state.accepted:
                (self.paths.artifacts / "config_fingerprint.json").write_text(
                    json.dumps(self.config_fingerprint, indent=1))
            state.save(self.paths.state_file)
            while (state.turn < self.max_candidates
                   and not state.accepted and not state.stop_reason
                   and state.physical_runs < self.max_physical):
                state.turn += 1
                state.save(self.paths.state_file)
                status = self._one_turn(state, state.turn)
                state.save(self.paths.state_file)
                self.on_event(f"[turn {state.turn}] {status}")
        return state

    # ------------------------------------------------------------------
    def _seed_incumbent(self, state: PowerSaveState) -> None:
        """Install the incumbent as best and archive its measured point.

        best_hash identity = SHA-256 of the candidate file bytes."""
        self._install_best(self.incumbent)
        import hashlib
        f = self.paths.best / self.candidate_filename
        state.best_hash = (hashlib.sha256(f.read_bytes()).hexdigest()
                           if f.is_file() else
                           manifest_hash(workspace_manifest(self.paths.best)))
        state.best_manifest = workspace_manifest(self.paths.best)
        if not state.archive:
            metrics = self._measure(self.paths.best, state, budgeted=False)
            if metrics is None:
                state.stop_reason = ("incumbent could not be validly "
                                     "measured (missing/failed/unbounded)")
                self.on_event(f"[STOP] {state.stop_reason}")
                return
            state.best_metrics = metrics
            state.best_verdict = VERDICT_PARETO
            # incumbent already meeting all targets: record and stop
            if self.objectives.targets and meets_targets(
                    metrics, self.objectives.targets):
                state.best_verdict = VERDICT_TARGET
                state.accepted = True
                state.record({"status": "incumbent_meets_targets",
                              "metrics": metrics})
            state.archive.append({"hash": state.best_hash,
                                  "turn": 0, "verdict": state.best_verdict,
                                  "metrics": metrics})

    def _install_best(self, source: Path) -> None:
        _rmrf(self.paths.best)
        if source.is_dir():
            import shutil
            shutil.copytree(source, self.paths.best)
        else:
            self.paths.best.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(source, self.paths.best / source.name)

    def _recover_best(self, state: PowerSaveState) -> None:
        if not state.best_hash:
            return
        cur = (workspace_manifest(self.paths.best)
               if self.paths.best.is_dir() and any(self.paths.best.iterdir())
               else {})
        if manifest_hash(cur) == state.best_hash:
            return
        # crash recovery: first try to restore the promoted candidate itself
        # from its attempt sandbox (candidate file hash identifies it)
        import hashlib
        for attempt in sorted(self.paths.attempts.glob("turn_*")):
            f = attempt / self.candidate_filename
            if f.is_file() and hashlib.sha256(f.read_bytes()).hexdigest()                     == state.best_hash:
                self.on_event(f"[recover] restoring promoted candidate from "
                              f"{attempt.name}")
                self._install_best(attempt)
                state.best_manifest = workspace_manifest(self.paths.best)
                return
        self.on_event("[recover] best workspace missing/stale; "
                      "restoring from incumbent")
        self._install_best(self.incumbent)
        state.best_manifest = workspace_manifest(self.paths.best)
        import hashlib
        f = self.paths.best / self.candidate_filename
        state.best_hash = (hashlib.sha256(f.read_bytes()).hexdigest()
                           if f.is_file() else
                           manifest_hash(state.best_manifest))

    def _verify_protected(self, state: PowerSaveState) -> None:
        if not self.protected_files:
            return
        for rel, expected in self.protected_files.items():
            p = self.paths.root / rel
            from chia_merge import _sha256
            actual = _sha256(p) if p.is_file() else "MISSING"
            if actual != expected:
                state.stop_reason = f"protected hash changed: {rel}"
                self.on_event(f"[STOP] {state.stop_reason}")
                return

    # ------------------------------------------------------------------
    def _one_turn(self, state: PowerSaveState, turn: int) -> str:
        sandbox = self.paths.attempts / f"turn_{turn:04d}"
        _rmrf(sandbox)
        sandbox.mkdir(parents=True)
        if self.paths.best.is_dir():
            import shutil
            shutil.copytree(self.paths.best, sandbox, dirs_exist_ok=True)
        ms = state.model_status.setdefault(str(turn), {})

        if self.advise_fn is not None:
            try:
                advice = self.advise_fn(state) or ""
            except Exception as exc:
                ms["advise_error"] = str(exc)[:300]
                state.record({"turn": turn, "status": "advise_infra_failed"})
                _rmrf(sandbox)
                return f"advise infra failure ({str(exc)[:80]})"
            state.advice = advice
            state.hypothesis = advice.splitlines()[0][:200] if advice else ""
            ms["advise_chars"] = len(advice)
            (self.paths.artifacts / f"advice_turn{turn}.md").write_text(advice)

        try:
            ok, reason = self.do_fn(state, sandbox)
        except Exception as exc:
            ms["implement_error"] = str(exc)[:300]
            state.record({"turn": turn, "status": "implement_infra_failed"})
            _rmrf(sandbox)
            return f"implement infra failure ({str(exc)[:80]})"
        state.candidates_generated += 1
        ms["implement_ok"] = ok
        (self.paths.artifacts / f"implement_turn{turn}.txt").write_text(
            reason or "")

        cand = sandbox / self.candidate_filename
        if not ok or not cand.is_file():
            state.record({"turn": turn, "status": "implement_failed"})
            _rmrf(sandbox)
            return "implement reported failure"

        import hashlib
        cand_hash = hashlib.sha256(cand.read_bytes()).hexdigest()
        inc_file = (self.paths.best / self.candidate_filename)
        inc_hash = (hashlib.sha256(inc_file.read_bytes()).hexdigest()
                    if inc_file.is_file() else "")
        if cand_hash == inc_hash:
            state.record({"turn": turn, "status": "stall"})
            _rmrf(sandbox)
            return "stall (candidate identical to incumbent)"

        result = self.cheap_check.evaluate(sandbox, best_level=0)
        (self.paths.artifacts / f"check_turn{turn}.json").write_text(
            json.dumps({"verdict": result.verdict, "level": result.level,
                        "feedback": result.feedback, "detail": result.detail},
                       indent=1))
        ms["cheap_verdict"] = result.verdict
        ms["cheap_level"] = result.level

        if result.verdict == VERDICT_RETRY:
            state.record({"turn": turn, "status": "retry",
                          "level": result.level})
            _rmrf(sandbox)
            return f"retry: {result.feedback[:120]}"
        if result.verdict in (VERDICT_REJECT, VERDICT_IMPROVE):
            # IMPROVE cannot occur: accept_level == len(gates)
            state.feedback = result.feedback
            state.consecutive_dominated = 0
            state.record({"turn": turn, "status": "invalid",
                          "level": result.level})
            _rmrf(sandbox)
            return f"INVALID: {result.feedback[:120]}"

        # proxy trigger: spend a physical run only on a promising survivor
        flat: dict = {}
        for sub in result.detail.values():
            if isinstance(sub, dict):
                for k, v in sub.items():
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        flat[k] = v
        proxy_metrics = {n: flat[n] for n in self.objectives.names
                         if n in flat}
        if (self.objectives.physical_trigger_frac > 0
                and state.best_metrics
                and not self._improves_by(proxy_metrics, state.best_metrics,
                                          self.objectives.physical_trigger_frac)):
            state.record({"turn": turn, "status": "proxy_insufficient",
                          "proxy": proxy_metrics})
            _rmrf(sandbox)
            return "no proxy improvement; physical budget not spent"

        # full physical evaluation: workers dead first; the budget slot is
        # persisted BEFORE launch so a crash cannot refund or overdraw it
        kill_worker_processes(self.worker_patterns,
                              log_file=self.paths.artifacts
                              / f"worker_kill_turn{turn}.json")
        state.physical_runs += 1
        state.save(self.paths.state_file)
        try:
            phys = self.physical_gate(sandbox)
        except Exception as exc:
            state.record({"turn": turn, "status": "physical_infra_failed"})
            _rmrf(sandbox)
            return f"physical infra failure ({str(exc)[:80]})"
        (self.paths.artifacts / f"physical_turn{turn}.json").write_text(
            json.dumps({"passed": phys.passed, "retry": phys.retry,
                        "note": phys.note, "detail": phys.detail}, indent=1))
        if phys.retry:
            state.physical_runs -= 1   # infrastructure failure: not a run
            state.save(self.paths.state_file)
            state.record({"turn": turn, "status": "physical_retry"})
            _rmrf(sandbox)
            return f"physical retry: {phys.note[:120]}"
        if not phys.passed:
            state.feedback = f"physical gate failed: {phys.note}"
            state.record({"turn": turn, "status": "physical_failed"})
            _rmrf(sandbox)
            return f"REGRESSION: {phys.note[:120]}"

        import math
        raw = {k: v for k, v in phys.detail.items()
               if isinstance(v, (int, float)) and not isinstance(v, bool)}
        missing = [n for n in self.objectives.names if n not in raw]
        nonfinite = [n for n in self.objectives.names
                     if n in raw and not math.isfinite(float(raw[n]))]
        if missing or nonfinite:
            state.record({"turn": turn, "status": "metrics_incomplete",
                          "missing": missing, "nonfinite": nonfinite})
            _rmrf(sandbox)
            return ("physical result objectives invalid: "
                    f"missing={missing} nonfinite={nonfinite}")
        metrics = raw

        for c in self.hard_constraints:
            violation = c(metrics)
            if violation:
                state.feedback = f"constraint violated: {violation}"
                state.record({"turn": turn, "status": "regression",
                              "metrics": metrics})
                _rmrf(sandbox)
                return f"REGRESSION: {violation[:120]}"

        verdict = self._classify(state, metrics)
        state.record({"turn": turn, "status": verdict.lower(),
                      "metrics": metrics, "hash": cand_hash})
        if verdict in (VERDICT_PARETO, VERDICT_TARGET):
            self._promote(state, sandbox, metrics, verdict, cand_hash, turn)
            if verdict == VERDICT_TARGET:
                state.accepted = True
            return f"{verdict}: promoted"
        if verdict == VERDICT_DOMINATED:
            state.consecutive_dominated += 1
            state.feedback = ("candidate dominated by an archived point; "
                              "archive: "
                              + json.dumps(state.archive[-3:])[-600:])
            if state.consecutive_dominated >= self.review_after_dominated:
                state.stop_reason = ("review_stop: "
                                     f"{state.consecutive_dominated} "
                                     "consecutive dominated candidates")
            _rmrf(sandbox)
            return f"DOMINATED ({state.consecutive_dominated} consecutive)"
        state.feedback = "candidate rejected"
        _rmrf(sandbox)
        return verdict

    # ------------------------------------------------------------------
    def _improves_by(self, metrics: dict, reference: dict,
                     frac: float) -> bool:
        for n in self.objectives.names:
            if n in metrics and n in reference and float(reference[n]) > 0:
                if float(metrics[n]) <= float(reference[n]) * (1 - frac):
                    return True
        return False

    def _classify(self, state: PowerSaveState, metrics: dict) -> str:
        import math
        for point in state.archive:
            pm = point.get("metrics", {})
            if pm and dominates(pm, metrics, self.objectives.names):
                return VERDICT_DOMINATED
        for point in state.archive:
            pm = point.get("metrics", {})
            if pm and all(n in pm for n in self.objectives.names) \
                    and all(float(pm[n]) == float(metrics[n])
                            for n in self.objectives.names):
                return VERDICT_DOMINATED
        if self.objectives.targets and meets_targets(
                metrics, self.objectives.targets):
            return VERDICT_TARGET
        return VERDICT_PARETO

    def _promote(self, state: PowerSaveState, sandbox: Path, metrics: dict,
                 verdict: str, cand_hash: str, turn: int) -> None:
        state.consecutive_dominated = 0
        state.archive.append({"hash": cand_hash, "turn": turn,
                              "verdict": verdict, "metrics": metrics})
        # prune archive points dominated by the new point (keep frontier)
        state.archive = [pt for pt in state.archive
                         if pt["hash"] == cand_hash
                         or not dominates(metrics, pt.get("metrics", {}),
                                          self.objectives.names)]
        state.best_metrics = metrics
        state.best_hash = cand_hash
        state.best_verdict = verdict
        state.feedback = (f"{verdict}: " + ", ".join(
            f"{n}={metrics[n]}" for n in self.objectives.names
            if n in metrics))
        self._install_best(sandbox)
        state.best_manifest = workspace_manifest(self.paths.best)
        (self.paths.artifacts / "pareto.json").write_text(
            json.dumps(state.archive, indent=1))

    def _measure(self, ws: Path, state: PowerSaveState,
                 budgeted: bool = False) -> dict | None:
        """Measure a workspace's physical objectives (incumbent seeding or
        final verification). Not model-facing; returns None (and records the
        reason) unless every objective is present and finite."""
        import math
        try:
            phys = self.physical_gate(ws)
        except Exception as exc:
            state.record({"status": "measure_infra_failed", "error": str(exc)[:200]})
            return None
        if phys.retry or not phys.passed:
            state.record({"status": "measure_failed",
                          "note": phys.note[:200], "retry": phys.retry})
            return None
        raw = {k: v for k, v in phys.detail.items()
               if isinstance(v, (int, float)) and not isinstance(v, bool)}
        if any(n not in raw or not math.isfinite(float(raw[n]))
               for n in self.objectives.names):
            state.record({"status": "measure_incomplete"})
            return None
        return raw

    # ------------------------------------------------------------------
    def verify_final(self, state: PowerSaveState) -> dict:
        """Independent model-free repeat of the final best point. Fail-closed:
        candidate bytes must match best_hash, the cheap cascade must accept,
        the physical gate must pass without retry, every objective must be
        finite, hard constraints must hold, and metrics must agree with the
        promoted record. Always persists a report."""
        import hashlib, math
        report: dict = {"verified": False, "best_hash": state.best_hash,
                        "checks": {}, "verified_at": time.time()}
        try:
            if not state.best_hash or not self.paths.best.is_dir():
                report["reason"] = "no best candidate"
                return self._persist_final(report)
            best_file = self.paths.best / self.candidate_filename
            actual = (hashlib.sha256(best_file.read_bytes()).hexdigest()
                      if best_file.is_file() else "")
            report["checks"]["candidate_hash"] = actual == state.best_hash
            result = self.cheap_check.evaluate(self.paths.best, best_level=0)
            report["cheap_verdict"] = result.verdict
            report["checks"]["cheap_accept"] = result.verdict == VERDICT_ACCEPT
            if not report["checks"]["cheap_accept"]:
                report["reason"] = f"cheap cascade: {result.feedback[:200]}"
                return self._persist_final(report)
            kill_worker_processes(self.worker_patterns,
                                  log_file=self.paths.artifacts
                                  / "worker_kill_final.json")
            phys = self.physical_gate(self.paths.best)
            report["checks"]["physical_no_retry"] = not phys.retry
            report["checks"]["physical_passed"] = bool(
                phys.passed and not phys.retry)
            raw = {k: v for k, v in phys.detail.items()
                   if isinstance(v, (int, float)) and not isinstance(v, bool)}
            report["checks"]["objectives_finite"] = all(
                n in raw and math.isfinite(float(raw[n]))
                for n in self.objectives.names)
            violations = [c(raw) for c in self.hard_constraints
                          if c(raw)]
            report["checks"]["constraints_hold"] = not violations
            if violations:
                report["reason"] = f"constraint violations: {violations[:2]}"
            report["checks"]["metrics_agree"] = all(
                n in raw and state.best_metrics
                and float(raw[n]) == float(state.best_metrics[n])
                for n in self.objectives.names)
            if not report["checks"]["metrics_agree"] and "reason" not in report:
                report["reason"] = "physical metrics differ from promoted record"
            report["physical_metrics"] = raw
            report["verified"] = all(report["checks"].values())
        except Exception as exc:
            report["reason"] = f"verify_final exception: {str(exc)[:200]}"
        return self._persist_final(report)

    def _persist_final(self, report: dict) -> dict:
        (self.paths.artifacts / "final_repeat.json").write_text(
            json.dumps(report, indent=1))
        return report


def power_save_resume_guard(run: RunPaths, inputs_dir: Path,
                            hashes_file: Path, contract_file: Path,
                            contract: str) -> str | None:
    """Return a rejection reason if pinned inputs or the contract changed,
    including on-disk tampering of the copied input files."""
    try:
        new_hashes = json.loads(hashes_file.read_text())
        verify_resume_inputs(inputs_dir, hashes_file, contract_file,
                             new_hashes, contract)
        return None
    except (RuntimeError, json.JSONDecodeError, OSError) as exc:
        return str(exc)
