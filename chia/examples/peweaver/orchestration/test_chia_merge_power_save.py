import json
import math
import sys
from pathlib import Path

import pytest

# Run against the repository primitives while this new composition is staged.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
for parent in HERE.parents:
    if (parent / "chia_merge.py").is_file():
        sys.path.insert(0, str(parent)); break

from chia_merge import GateOutcome, RunPaths
from chia_power_save import PowerObjectives
from chia_merge_power_save import ChiaMergePowerSave, JointState, _finite_metrics


def test_finite_metrics_accept_zero_timing_violations_only():
    names = ("mapped_area_um2", "power_mw", "setup_violation_ns", "tns_violation_ns")
    feasible = {"mapped_area_um2": 58516.1216, "power_mw": 5.366647616,
                "setup_violation_ns": 0.0, "tns_violation_ns": 0.0}
    assert _finite_metrics(feasible, names) == feasible

    for field, value in (
        ("setup_violation_ns", -0.01),
        ("tns_violation_ns", -1.0),
        ("setup_violation_ns", math.nan),
        ("tns_violation_ns", math.inf),
        ("setup_violation_ns", -math.inf),
        ("mapped_area_um2", 0.0),
        ("mapped_area_um2", -1.0),
        ("mapped_area_um2", math.nan),
        ("mapped_area_um2", math.inf),
        ("power_mw", 0.0),
        ("power_mw", -1.0),
        ("power_mw", math.nan),
        ("power_mw", math.inf),
    ):
        invalid = dict(feasible, **{field: value})
        assert _finite_metrics(invalid, names) is None


def setup(tmp_path, bodies=("A",), metrics=None, targets=None, **kw):
    run = RunPaths.create(tmp_path / "run")
    metrics = metrics or {b: {"area": 90.0, "power": 9.0} for b in bodies}
    calls = []
    def cheap(ws):
        return GateOutcome("functional", True)
    def physical(ws):
        body = (ws / "cand.v").read_text()
        calls.append(body)
        return GateOutcome("physical", True, detail=metrics[body])
    seq = iter(bodies)
    def do(state, ws):
        body = next(seq, None)
        if body is None: return False, "done"
        (ws / "cand.v").write_text(body)
        return True, body
    obj = PowerObjectives(names=("area", "power"), targets=targets or {})
    loop = ChiaMergePowerSave(run, candidate_filename="cand.v", cheap_gates=[cheap],
                              physical_gate=physical, objectives=obj, do_fn=do,
                              max_candidates=kw.pop("max_candidates", len(bodies)),
                              max_physical=kw.pop("max_physical", len(bodies)),
                              config_fingerprint={"test": 1}, **kw)
    return loop, calls


def test_bootstrap_is_reference_free_and_first_pareto_continues(tmp_path):
    loop, calls = setup(tmp_path, ("A", "B"), {"A": {"area": 100, "power": 8}, "B": {"area": 90, "power": 8}})
    st = loop.run(use_lock=False)
    assert st.best_hash and st.best_verdict == "PARETO" and not st.accepted
    assert calls == ["A", "B"]


def test_feedback_is_interleaved_and_adviser_sees_metrics(tmp_path):
    seen = []
    loop, _ = setup(tmp_path, ("A", "B"), {"A": {"area": 100, "power": 10}, "B": {"area": 90, "power": 9}}, max_candidates=2)
    loop.advise_fn = lambda st: seen.append((st.turn, dict(st.best_metrics), st.feedback)) or "merge/power"
    loop.run(use_lock=False)
    assert seen[0][1] == {}
    assert seen[1][1] == {"area": 100, "power": 10}


def test_target_is_only_accepted_verdict(tmp_path):
    loop, _ = setup(tmp_path, ("A",), {"A": {"area": 90, "power": 9}}, targets={"power": 9})
    st = loop.run(use_lock=False)
    assert st.accepted and st.best_verdict == "TARGET"


def test_cheap_failure_skips_physical_and_preserves_attempt(tmp_path):
    loop, calls = setup(tmp_path, ("A",))
    loop.cheap_check = loop.cheap_check.__class__([lambda ws: GateOutcome("lint", False, note="bad")])
    st = loop.run(use_lock=False)
    assert calls == [] and st.last_rejected_hash
    assert (loop.paths.attempts / "turn_0001" / "cand.v").is_file()


def test_physical_retry_refunds_budget(tmp_path):
    loop, _ = setup(tmp_path, ("A",), max_candidates=1, max_physical=1)
    loop.physical_gate = lambda ws: GateOutcome("physical", False, retry=True)
    st = loop.run(use_lock=False)
    assert st.physical_runs == 0 and not st.stop_reason


def test_dominated_candidate_is_not_promoted(tmp_path):
    loop, _ = setup(tmp_path, ("A", "B"), {"A": {"area": 90, "power": 9}, "B": {"area": 100, "power": 10}})
    st = loop.run(use_lock=False)
    assert st.best_hash and st.best_metrics == {"area": 90, "power": 9}
    assert any(x["status"] == "dominated" for x in st.history)


def test_resume_rejects_fingerprint_change(tmp_path):
    loop, _ = setup(tmp_path, ("A",), max_candidates=1)
    loop.run(use_lock=False)
    loop.config_fingerprint = {"test": 2}
    resumed = loop.run(resume=True, use_lock=False)
    assert resumed.stop_reason.startswith("resume refused")


def test_verify_final_requires_metric_agreement(tmp_path):
    loop, _ = setup(tmp_path, ("A",), {"A": {"area": 90, "power": 9}})
    st = loop.run(use_lock=False)
    assert loop.verify_final(st)["verified"]
    st.best_metrics["power"] = 99
    assert not loop.verify_final(st)["verified"]


def test_verify_final_requires_candidate_hash(tmp_path):
    loop, _ = setup(tmp_path, ("A",))
    st = loop.run(use_lock=False)
    (loop.paths.best / "cand.v").write_text("tampered")
    assert not loop.verify_final(st)["verified"]


def test_config_fingerprint_persisted_and_state_json_is_readable(tmp_path):
    loop, _ = setup(tmp_path, ("A",))
    st = loop.run(use_lock=False)
    assert json.loads((loop.paths.artifacts / "config_fingerprint.json").read_text()) == {"test": 1}
    assert JointState.load(loop.paths.state_file).best_hash == st.best_hash


def test_resume_recovers_best_from_immutable_attempt(tmp_path):
    loop, _ = setup(tmp_path)
    st = loop.run(use_lock=False)
    (loop.paths.best / "cand.v").write_text("corrupt")
    recovered = loop.run(resume=True, use_lock=False)
    assert not recovered.stop_reason
    assert (loop.paths.best / "cand.v").read_text() == "A"
    assert recovered.best_hash == st.best_hash


def test_resume_refuses_missing_promoted_bytes(tmp_path):
    loop, _ = setup(tmp_path)
    loop.run(use_lock=False)
    (loop.paths.best / "cand.v").unlink()
    (loop.paths.attempts / "turn_0001" / "cand.v").unlink()
    assert "cannot be recovered" in loop.run(resume=True, use_lock=False).stop_reason


def test_protected_reference_tamper_prevents_generation(tmp_path):
    import hashlib
    loop, calls = setup(tmp_path)
    ref = loop.paths.inputs / "ref.v"
    ref.write_text("reference")
    loop.protected_files = {"inputs/ref.v": hashlib.sha256(ref.read_bytes()).hexdigest()}
    ref.write_text("tampered")
    st = loop.run(use_lock=False)
    assert "protected hash changed" in st.stop_reason
    assert calls == [] and st.candidates_generated == 0


def test_incomplete_physical_metrics_never_call_constraints(tmp_path):
    loop, _ = setup(tmp_path, metrics={"A": {"area": 90}})
    loop.hard_constraints = (lambda m: pytest.fail("constraints need complete metrics"),)
    st = loop.run(use_lock=False)
    assert not st.best_hash and "missing/non-finite" in st.feedback


def test_semantic_failure_spends_reserved_physical_budget(tmp_path):
    loop, _ = setup(tmp_path, bodies=("A", "B"), max_physical=1)
    loop.physical_gate = lambda ws: GateOutcome("physical", False, note="timing")
    st = loop.run(use_lock=False)
    assert st.physical_runs == 1 and st.turn == 1 and not st.best_hash


def test_equal_metrics_are_dominated_and_keep_source(tmp_path):
    loop, _ = setup(tmp_path, bodies=("A", "B"))
    st = loop.run(use_lock=False)
    assert st.history[-1]["status"] == "dominated"
    assert (loop.paths.best / "cand.v").read_text() == "A"
    assert (loop.paths.attempts / "turn_0002" / "cand.v").read_text() == "B"


def test_provider_error_stops_without_repeated_calls(tmp_path):
    loop, physical_calls = setup(tmp_path, bodies=("A", "B"), max_candidates=6)
    calls = []
    def fail(state):
        calls.append(state.turn)
        raise RuntimeError("HTTP 429 monthly spending cap")
    loop.advise_fn = fail
    st = loop.run(use_lock=False)
    assert calls == [1] and physical_calls == []
    assert st.turn == 1 and "HTTP 429" in st.stop_reason


def test_rejected_physical_metrics_reach_next_turn(tmp_path):
    seen = []
    values = {"A": {"area": 100, "power": 7}, "B": {"area": 70, "power": 6}}
    loop, _ = setup(tmp_path, bodies=("A", "B"), metrics=values)
    loop.hard_constraints = (lambda m: "area too large" if m["area"] > 80 else None,)
    loop.advise_fn = lambda st: seen.append(st.feedback) or "improve"
    st = loop.run(use_lock=False)
    assert 'area too large' in seen[1] and '"power": 7' in seen[1]
    assert st.history[0]["metrics"] == values["A"]
    assert st.best_metrics == values["B"]

