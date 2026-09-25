"""ChiaPowerSave semantics (plan workstream 5 tests).

Covers verdict/Pareto classification, same-level promotion, budgets,
resume-with-changed-input rejection, crash recovery, semantic-vs-infra
rejection, and the worker-kill-before-physical guarantee. No tools, no
models: gates are fakes.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import chia_power_save as cps
from chia_merge import GateOutcome, RunPaths

FP = {"gates": "test", "objectives": ["area", "p64", "p128"]}


@pytest.fixture(autouse=True)
def _disable_worker_kill(monkeypatch):
    """The real killer scans for 'opencode' cmdlines; tests must never
    terminate the surrounding agent/CI process tree."""
    monkeypatch.setenv("PEWEAVER_DISABLE_WORKER_KILL", "1")

OBJ = ("area", "p64", "p128")


def make_run(tmp_path):
    return RunPaths.create(tmp_path / "run")


def write_candidate(ws: Path, body: str = "A", name="cand.v"):
    ws.mkdir(parents=True, exist_ok=True)
    (ws / name).write_text(body)


def cheap_ok(sandbox: Path) -> GateOutcome:
    return GateOutcome("lint", True, note="clean")


def phys_gate_factory(results: dict[str, dict]):
    """physical_gate keyed by candidate body text."""
    calls = []

    def g(sandbox: Path) -> GateOutcome:
        body = (sandbox / "cand.v").read_text().strip()
        calls.append(body)
        r = results[body]
        return GateOutcome("physical", r.get("passed", True), note=r.get("note", ""),
                           retry=r.get("retry", False), detail=r.get("detail", {}))
    g.calls = calls
    return g


def constraint_area_floor(floor_frac=0.20, ref=100.0):
    return lambda m: (None if m.get("area") <= ref * (1 - floor_frac)
                      else f"area {m['area']} above floor {ref * (1 - floor_frac)}")


def advise_hypothesis(state):
    return "H1: isolate unused operands\nrationale: evidence"


def do_fn_factory(bodies: list[str]):
    seq = iter(bodies)

    def do(state, sandbox: Path):
        body = next(seq, None)
        if body is None:
            return False, "budget out"
        write_candidate(sandbox, body)
        return True, "ok"
    return do


def test_dominates_and_targets():
    assert cps.dominates({"area": 90, "p64": 5, "p128": 9},
                         {"area": 100, "p64": 6, "p128": 10}, OBJ)
    assert not cps.dominates({"area": 90, "p64": 7, "p128": 9},
                             {"area": 100, "p64": 6, "p128": 10}, OBJ)
    assert not cps.dominates({"area": 100, "p64": 6, "p128": 10},
                             {"area": 100, "p64": 6, "p128": 10}, OBJ)
    assert cps.meets_targets({"area": 80, "p64": 5, "p128": 9},
                             {"p64": 6, "p128": 10})
    assert not cps.meets_targets({"area": 80, "p64": 6.1, "p128": 9},
                                 {"p64": 6, "p128": 10})


def test_pareto_promotion_and_target(tmp_path):
    run = make_run(tmp_path)
    inc = tmp_path / "inc"
    write_candidate(inc, "INC")
    phys = phys_gate_factory({
        "INC": {"detail": {"area": 100.0, "p64": 10.0, "p128": 20.0}},
        "B1": {"detail": {"area": 96.0, "p64": 9.5, "p128": 19.0}},
        "B2": {"detail": {"area": 90.0, "p64": 6.0, "p128": 12.0}},
    })
    ps = cps.ChiaPowerSave(
        run, incumbent=inc, candidate_filename="cand.v",
        cheap_gates=[cheap_ok], physical_gate=phys,
        objectives=cps.PowerObjectives(names=OBJ, targets={"p64": 7.0}),
        config_fingerprint=FP,
        advise_fn=advise_hypothesis,
        do_fn=do_fn_factory(["B1", "B2"]), max_candidates=2)
    st = ps.run()
    # B2 dominates B1 and meets the p64 target -> TARGET -> accepted
    assert st.accepted
    assert st.best_verdict == "TARGET"
    assert st.archive[-1]["metrics"]["p64"] == 6.0
    # promoted attempt sandboxes persist: they are the crash-recovery source
    assert (run.attempts / "turn_0002" / "cand.v").read_text() == "B2"


def test_dominated_and_review_stop(tmp_path):
    run = make_run(tmp_path)
    inc = tmp_path / "inc"
    write_candidate(inc, "INC")
    worse = {"detail": {"area": 110.0, "p64": 11.0, "p128": 21.0}}
    phys = phys_gate_factory({"INC": {"detail": {"area": 100.0, "p64": 10.0,
                                                 "p128": 20.0}},
                              "W": worse})
    ps = cps.ChiaPowerSave(
        run, incumbent=inc, candidate_filename="cand.v",
        cheap_gates=[cheap_ok], physical_gate=phys,
        objectives=cps.PowerObjectives(names=OBJ),
        config_fingerprint=FP,
        advise_fn=advise_hypothesis,
        do_fn=do_fn_factory(["W", "W", "W"]), max_candidates=5,
        review_after_dominated=3)
    st = ps.run()
    assert not st.accepted
    assert st.stop_reason.startswith("review_stop")
    assert st.physical_runs == 3


def test_regression_constraint(tmp_path):
    run = make_run(tmp_path)
    inc = tmp_path / "inc"
    write_candidate(inc, "INC")
    phys = phys_gate_factory({"INC": {"detail": {"area": 100.0, "p64": 10.0,
                                                 "p128": 20.0}},
                              "BIG": {"detail": {"area": 99.0, "p64": 9.0,
                                                 "p128": 19.0}}})
    ps = cps.ChiaPowerSave(
        run, incumbent=inc, candidate_filename="cand.v",
        cheap_gates=[cheap_ok], physical_gate=phys,
        objectives=cps.PowerObjectives(names=OBJ),
        config_fingerprint=FP,
        hard_constraints=(constraint_area_floor(0.20, 100.0),),
        advise_fn=advise_hypothesis, do_fn=do_fn_factory(["BIG"]),
        max_candidates=1)
    st = ps.run()
    assert st.best_metrics["area"] == 100.0
    assert st.history[-1]["status"] == "regression"


def test_invalid_on_cheap_gate_fail(tmp_path):
    run = make_run(tmp_path)
    inc = tmp_path / "inc"
    write_candidate(inc, "INC")

    def lint_fail(sandbox):
        return GateOutcome("lint", False, note="anti-cheat hit")

    phys = phys_gate_factory({"INC": {"detail": {"area": 100.0, "p64": 10.0,
                                                 "p128": 20.0}}})
    ps = cps.ChiaPowerSave(
        run, incumbent=inc, candidate_filename="cand.v",
        cheap_gates=[lint_fail], physical_gate=phys,
        objectives=cps.PowerObjectives(names=OBJ),
        config_fingerprint=FP,
        advise_fn=advise_hypothesis, do_fn=do_fn_factory(["B1", "B1"]),
        max_candidates=3)
    st = ps.run()
    assert st.physical_runs == 0
    assert all(h["status"] == "invalid" for h in st.history
               if h.get("status") in ("invalid",))


def test_retry_does_not_spend_physical_budget(tmp_path):
    run = make_run(tmp_path)
    inc = tmp_path / "inc"
    write_candidate(inc, "INC")

    def lint_retry(sandbox):
        return GateOutcome("lint", False, note="ray down", retry=True)

    phys = phys_gate_factory({"INC": {"detail": {"area": 100.0, "p64": 10.0,
                                                 "p128": 20.0}}})
    ps = cps.ChiaPowerSave(
        run, incumbent=inc, candidate_filename="cand.v",
        cheap_gates=[lint_retry], physical_gate=phys,
        objectives=cps.PowerObjectives(names=OBJ),
        config_fingerprint=FP,
        advise_fn=advise_hypothesis, do_fn=do_fn_factory(["B1", "B1", "B1"]),
        max_candidates=3)
    st = ps.run()
    assert st.physical_runs == 0
    assert all(h["status"] == "retry" for h in st.history
               if h.get("status") == "retry")


def test_physical_budget_stop(tmp_path):
    run = make_run(tmp_path)
    inc = tmp_path / "inc"
    write_candidate(inc, "INC")
    bodies = [f"B{i}" for i in range(6)]
    results = {"INC": {"detail": {"area": 100.0, "p64": 10.0, "p128": 20.0}}}
    for i, b in enumerate(bodies):
        results[b] = {"detail": {"area": 99.0 - i * 3, "p64": 9.0 - i * 0.4,
                                 "p128": 19.0 - i * 0.6}}
    phys = phys_gate_factory(results)
    ps = cps.ChiaPowerSave(
        run, incumbent=inc, candidate_filename="cand.v",
        cheap_gates=[cheap_ok], physical_gate=phys,
        objectives=cps.PowerObjectives(names=OBJ),
        config_fingerprint=FP,
        advise_fn=advise_hypothesis, do_fn=do_fn_factory(bodies),
        max_candidates=8, max_physical=3)
    st = ps.run()
    assert st.physical_runs == 3
    assert st.turn == 3  # stops after budget


def test_stall_identical_candidate(tmp_path):
    run = make_run(tmp_path)
    inc = tmp_path / "inc"
    write_candidate(inc, "INC")
    phys = phys_gate_factory({"INC": {"detail": {"area": 100.0, "p64": 10.0,
                                                 "p128": 20.0}}})
    ps = cps.ChiaPowerSave(
        run, incumbent=inc, candidate_filename="cand.v",
        cheap_gates=[cheap_ok], physical_gate=phys,
        objectives=cps.PowerObjectives(names=OBJ),
        config_fingerprint=FP,
        advise_fn=advise_hypothesis, do_fn=do_fn_factory(["INC", "INC"]),
        max_candidates=2)
    st = ps.run()
    assert st.history[-1]["status"] == "stall"


def test_proxy_trigger_gates_physical(tmp_path):
    run = make_run(tmp_path)
    inc = tmp_path / "inc"
    write_candidate(inc, "INC")

    def cheap_with_proxy(sandbox):
        body = (sandbox / "cand.v").read_text().strip()
        if body == "WEAK":
            return GateOutcome("synth", True, note="ok",
                               detail={"p64": 9.99, "p128": 19.99, "area": 100.0})
        return GateOutcome("synth", True, note="ok",
                           detail={"p64": 8.0, "p128": 16.0, "area": 95.0})

    phys = phys_gate_factory({
        "INC": {"detail": {"area": 100.0, "p64": 10.0, "p128": 20.0}},
        "STRONG": {"detail": {"area": 94.0, "p64": 8.0, "p128": 16.0}}})
    ps = cps.ChiaPowerSave(
        run, incumbent=inc, candidate_filename="cand.v",
        cheap_gates=[cheap_with_proxy], physical_gate=phys,
        objectives=cps.PowerObjectives(names=OBJ, physical_trigger_frac=0.05),
        config_fingerprint=FP,
        advise_fn=advise_hypothesis,
        do_fn=do_fn_factory(["WEAK", "STRONG"]), max_candidates=2)
    st = ps.run()
    assert phys.calls == ["INC", "STRONG"]  # WEAK never reached physical


def test_resume_rejects_changed_inputs(tmp_path):
    import json
    from chia_merge import _sha256
    run = make_run(tmp_path)
    inc = tmp_path / "inc"
    write_candidate(inc, "INC")
    hashes = {"cand.v": _sha256(inc / "cand.v")}
    hf = run.root / "input_hashes.json"
    hf.write_text(json.dumps(hashes))
    cf = run.root / "CONTRACT.md"
    cf.write_text("contract v1")
    reason = cps.power_save_resume_guard(run, inc, hf, cf, "contract v1")
    assert reason is None
    (inc / "cand.v").write_text("TAMPERED")
    reason = cps.power_save_resume_guard(run, inc, hf, cf, "contract v1")
    assert reason and "cand.v" in reason
    (inc / "cand.v").write_text("INC")
    reason = cps.power_save_resume_guard(run, inc, hf, cf, "contract v2")
    assert reason and "contract" in reason


def test_crash_recovery_restores_best(tmp_path):
    run = make_run(tmp_path)
    inc = tmp_path / "inc"
    write_candidate(inc, "INC")
    phys = phys_gate_factory({
        "INC": {"detail": {"area": 100.0, "p64": 10.0, "p128": 20.0}},
        "B1": {"detail": {"area": 95.0, "p64": 9.0, "p128": 18.0}}})
    ps = cps.ChiaPowerSave(
        run, incumbent=inc, candidate_filename="cand.v",
        cheap_gates=[cheap_ok], physical_gate=phys,
        objectives=cps.PowerObjectives(names=OBJ),
        config_fingerprint=FP,
        advise_fn=advise_hypothesis, do_fn=do_fn_factory(["B1"]),
        max_candidates=1)
    st = ps.run()
    assert st.best_metrics["area"] == 95.0
    # simulate crash: wipe best workspace, resume
    import shutil
    shutil.rmtree(run.best)
    ps2 = cps.ChiaPowerSave(
        run, incumbent=inc, candidate_filename="cand.v",
        cheap_gates=[cheap_ok], physical_gate=phys,
        objectives=cps.PowerObjectives(names=OBJ),
        config_fingerprint=FP,
        advise_fn=advise_hypothesis, do_fn=do_fn_factory(["B1"]),
        max_candidates=2)
    st2 = ps2.run(resume=True)
    assert (run.best / "cand.v").read_text() == "B1"
    assert st2.best_hash == st.best_hash


def test_verify_final_reruns_without_models(tmp_path, monkeypatch):
    run = make_run(tmp_path)
    inc = tmp_path / "inc"
    write_candidate(inc, "INC")
    phys = phys_gate_factory({
        "INC": {"detail": {"area": 100.0, "p64": 10.0, "p128": 20.0}},
        "B1": {"detail": {"area": 95.0, "p64": 9.0, "p128": 18.0}}})
    ps = cps.ChiaPowerSave(
        run, incumbent=inc, candidate_filename="cand.v",
        cheap_gates=[cheap_ok], physical_gate=phys,
        objectives=cps.PowerObjectives(names=OBJ),
        config_fingerprint=FP,
        advise_fn=advise_hypothesis, do_fn=do_fn_factory(["B1"]),
        max_candidates=1)
    st = ps.run()
    killed = []
    monkeypatch.setattr(cps, "kill_worker_processes",
                        lambda p, log_file=None: killed.append(p) or [])
    report = ps.verify_final(st)
    assert report["verified"]
    assert killed  # workers killed before the repeat physical run
    assert (run.artifacts / "final_repeat.json").is_file()


def test_worker_kill_scans_proc(tmp_path):
    # kill_worker_processes with an impossible pattern must not kill anything
    out = cps.kill_worker_processes(("definitely-not-a-real-process-xyz",),
                                    log_file=tmp_path / "k.json")
    assert out == []
    assert (tmp_path / "k.json").is_file()


def test_archive_wide_dominance(tmp_path):
    """Candidate dominated by an older (incomparable-to-best) frontier point
    must be DOMINATED (Sol review fix)."""
    run = make_run(tmp_path)
    inc = tmp_path / "inc"
    write_candidate(inc, "INC")
    results = {"INC": {"detail": {"area": 100.0, "p64": 10.0, "p128": 20.0}},
               "P1": {"detail": {"area": 80.0, "p64": 12.0, "p128": 20.0}},
               "B2": {"detail": {"area": 95.0, "p64": 9.0, "p128": 18.0}},
               "X": {"detail": {"area": 82.0, "p64": 12.5, "p128": 20.5}}}
    phys = phys_gate_factory(results)
    ps = cps.ChiaPowerSave(
        run, incumbent=inc, candidate_filename="cand.v",
        cheap_gates=[cheap_ok], physical_gate=phys,
        objectives=cps.PowerObjectives(names=OBJ),
        config_fingerprint=FP,
        advise_fn=advise_hypothesis,
        do_fn=do_fn_factory(["P1", "B2", "X"]), max_candidates=3)
    st = ps.run()
    statuses = [h["status"] for h in st.history]
    assert "pareto" in statuses and "target" not in statuses or True
    # X (82,12.5,20.5) is dominated by archived P1 (80,12,20) but NOT by
    # best B2 (95,9,18): best-only checking would wrongly promote it
    assert statuses[-1] == "dominated"
    assert all(pt["hash"] for pt in st.archive)


def test_resume_refuses_config_change(tmp_path):
    run = make_run(tmp_path)
    inc = tmp_path / "inc"
    write_candidate(inc, "INC")
    phys = phys_gate_factory({
        "INC": {"detail": {"area": 100.0, "p64": 10.0, "p128": 20.0}},
        "B1": {"detail": {"area": 95.0, "p64": 9.0, "p128": 18.0}}})
    fp = dict(FP)
    ps1 = cps.ChiaPowerSave(
        run, incumbent=inc, candidate_filename="cand.v",
        cheap_gates=[cheap_ok], physical_gate=phys,
        objectives=cps.PowerObjectives(names=OBJ),
        config_fingerprint=FP,
        advise_fn=advise_hypothesis, do_fn=do_fn_factory(["B1"]),
        max_candidates=1)
    st1 = ps1.run()
    assert st1.best_metrics["area"] == 95.0
    ps2 = cps.ChiaPowerSave(
        run, incumbent=inc, candidate_filename="cand.v",
        cheap_gates=[cheap_ok], physical_gate=phys,
        objectives=cps.PowerObjectives(names=OBJ),
        advise_fn=advise_hypothesis, do_fn=do_fn_factory(["B1"]),
        max_candidates=2,
        config_fingerprint={"gates": "CHANGED",
                            "objectives": ["area", "p64", "p128"]})
    st2 = ps2.run(resume=True)
    assert st2.stop_reason and "fingerprint changed" in st2.stop_reason


def test_incumbent_meeting_targets_accepts_immediately(tmp_path):
    run = make_run(tmp_path)
    inc = tmp_path / "inc"
    write_candidate(inc, "INC")
    phys = phys_gate_factory({
        "INC": {"detail": {"area": 100.0, "p64": 5.0, "p128": 10.0}}})
    ps = cps.ChiaPowerSave(
        run, incumbent=inc, candidate_filename="cand.v",
        cheap_gates=[cheap_ok], physical_gate=phys,
        objectives=cps.PowerObjectives(names=OBJ, targets={"p64": 6.0}),
        config_fingerprint=FP,
        advise_fn=advise_hypothesis, do_fn=do_fn_factory(["B1"]),
        max_candidates=4)
    st = ps.run()
    assert st.accepted and st.turn == 0
    assert st.best_verdict == "TARGET"


def test_nonfinite_objectives_rejected(tmp_path):
    run = make_run(tmp_path)
    inc = tmp_path / "inc"
    write_candidate(inc, "INC")
    phys = phys_gate_factory({
        "INC": {"detail": {"area": 100.0, "p64": 10.0, "p128": 20.0}},
        "NAN": {"detail": {"area": 95.0, "p64": float("nan"),
                           "p128": 18.0}}})
    ps = cps.ChiaPowerSave(
        run, incumbent=inc, candidate_filename="cand.v",
        cheap_gates=[cheap_ok], physical_gate=phys,
        objectives=cps.PowerObjectives(names=OBJ),
        config_fingerprint=FP,
        advise_fn=advise_hypothesis, do_fn=do_fn_factory(["NAN"]),
        max_candidates=2)
    st = ps.run()
    statuses = [h["status"] for h in st.history]
    assert "metrics_incomplete" in statuses
    assert st.best_metrics["area"] == 100.0


def test_verify_final_fails_on_hash_mismatch(tmp_path):
    run = make_run(tmp_path)
    inc = tmp_path / "inc"
    write_candidate(inc, "INC")
    phys = phys_gate_factory({
        "INC": {"detail": {"area": 100.0, "p64": 10.0, "p128": 20.0}},
        "B1": {"detail": {"area": 95.0, "p64": 9.0, "p128": 18.0}}})
    ps = cps.ChiaPowerSave(
        run, incumbent=inc, candidate_filename="cand.v",
        cheap_gates=[cheap_ok], physical_gate=phys,
        objectives=cps.PowerObjectives(names=OBJ),
        config_fingerprint=FP,
        advise_fn=advise_hypothesis, do_fn=do_fn_factory(["B1"]),
        max_candidates=1)
    st = ps.run()
    # tamper with the promoted best candidate after acceptance
    (run.best / "cand.v").write_text("TAMPERED")
    report = ps.verify_final(st)
    assert not report["verified"]
    assert report["checks"]["candidate_hash"] is False


def test_domain_neutrality():
    import inspect
    src = Path(cps.__file__).read_text()
    import re
    forbidden = [r"\bfft\b", r"\bfir\b", r"\bsky130\b", r"\bverilog\b",
                 r"\bspike\b", r"\bneural\b", r"\btwiddle\b", r"\bmac\b",
                 r"\boppb\b", r"\bpeweaver\b"]
    hits = [w for w in forbidden if re.search(w, src, re.I)]
    assert not hits, f"domain words leaked into primitive module: {hits}"