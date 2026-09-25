"""Tests for the ChiaMerge transactional primitives (no RTL, no ray needed
for the loop tests; the module import needs the chia package importable).

Run from the repo root:  pytest examples/peweaver/orchestration/test_chia_primitives.py -v
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import pytest

try:
    from .chia_merge import (
        GateOutcome,
        IterationState,
        ChiaCheckCondition,
        RetryableGateError,
        ChiaIterate,
        RunPaths,
        VERDICT_ACCEPT,
        VERDICT_IMPROVE,
        VERDICT_REJECT,
        VERDICT_RETRY,
        _extract_code_block,
        _sha256,
        manifest_hash,
        verify_resume_inputs,
        workspace_manifest,
        MergePrompts as _mp,
        ChiaMerge as _cm,
    )
    HAS_DEPS = True
except ImportError:  # pragma: no cover
    HAS_DEPS = False


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@unittest.skipUnless(HAS_DEPS, "chia package unavailable")
class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_manifest_covers_all_files_and_is_order_stable(self):
        _write(self.root / "b.txt", "two")
        _write(self.root / "a" / "c.txt", "three")
        m1 = workspace_manifest(self.root)
        m2 = workspace_manifest(self.root)
        self.assertEqual(m1, m2)
        self.assertEqual(set(m1), {"b.txt", str(Path("a") / "c.txt")})

    def test_manifest_hash_changes_on_any_content_change(self):
        _write(self.root / "f.txt", "v1")
        h1 = manifest_hash(workspace_manifest(self.root))
        _write(self.root / "f.txt", "v2")
        h2 = manifest_hash(workspace_manifest(self.root))
        _write(self.root / "g.txt", "new")
        h3 = manifest_hash(workspace_manifest(self.root))
        self.assertNotEqual(h1, h2)
        self.assertNotEqual(h2, h3)

    def test_empty_dir_manifest(self):
        self.assertEqual(workspace_manifest(self.root), {})
        self.assertEqual(manifest_hash({}),
                         manifest_hash(workspace_manifest(self.root)))


@unittest.skipUnless(HAS_DEPS, "chia package unavailable")
class CheckConditionTests(unittest.TestCase):
    def test_all_pass_below_accept_level_is_improve(self):
        check = ChiaCheckCondition(
            [lambda sb: GateOutcome("g1", True),
             lambda sb: GateOutcome("g2", True)],
            accept_level=3)
        r = check.evaluate(Path("/nonexistent"), best_level=1)
        self.assertEqual(r.verdict, VERDICT_IMPROVE)
        self.assertEqual(r.level, 2)

    def test_full_pass_meeting_accept_level_accepts(self):
        check = ChiaCheckCondition(
            [lambda sb: GateOutcome("g1", True)], accept_level=1)
        r = check.evaluate(Path("/nonexistent"), best_level=0)
        self.assertEqual(r.verdict, VERDICT_ACCEPT)

    def test_failing_gate_at_same_level_rejects_with_feedback(self):
        check = ChiaCheckCondition(
            [lambda sb: GateOutcome("g1", True),
             lambda sb: GateOutcome("g2", False, note="mismatch 5/128")])
        r = check.evaluate(Path("/nonexistent"), best_level=1)
        self.assertEqual(r.verdict, VERDICT_REJECT)
        self.assertEqual(r.level, 1)
        self.assertIn("mismatch 5/128", r.feedback)

    def test_partial_advance_beyond_best_improves_with_feedback(self):
        check = ChiaCheckCondition(
            [lambda sb: GateOutcome("lint", True),
             lambda sb: GateOutcome("functional", False, note="128 mode broken")])
        r = check.evaluate(Path("/nonexistent"), best_level=0)
        self.assertEqual(r.verdict, VERDICT_IMPROVE)
        self.assertEqual(r.level, 1)
        self.assertIn("128 mode broken", r.feedback)

    def test_retry_gate_aborts_as_retry(self):
        check = ChiaCheckCondition(
            [lambda sb: GateOutcome("g1", True),
             lambda sb: GateOutcome("g2", False, note="tool missing", retry=True),
             lambda sb: GateOutcome("g3", False, note="never reached")])
        r = check.evaluate(Path("/nonexistent"))
        self.assertEqual(r.verdict, VERDICT_RETRY)
        self.assertEqual(r.level, 1)
        self.assertIn("g2", r.feedback)

    def test_raising_gate_is_retry_not_reject(self):
        def boom(sb):
            raise RetryableGateError("infra down")
        check = ChiaCheckCondition([boom])
        r = check.evaluate(Path("/nonexistent"))
        self.assertEqual(r.verdict, VERDICT_RETRY)
        self.assertIn("infra down", r.feedback)


@unittest.skipUnless(HAS_DEPS, "chia package unavailable")
class ChiaIterateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _make_run(self, name="run"):
        return RunPaths.create(self.base / name)

    def _state(self):
        return IterationState()

    def test_reject_discards_sandbox_and_keeps_best(self):
        run = self._make_run()
        _write(run.best / "candidate.v", "best v1")
        best_hash = manifest_hash(workspace_manifest(run.best))

        calls = {"n": 0}

        def advise(st):
            return "advice"

        def do(st, sandbox):
            calls["n"] += 1
            _write(sandbox / "candidate.v", f"broken {calls['n']}")
            return True, "edited"

        gates = [lambda sb: GateOutcome("lint", False, note="syntax error")]
        check = ChiaCheckCondition(gates)
        state = self._state()
        state.best_manifest = workspace_manifest(run.best)
        state.best_hash = best_hash
        it = ChiaIterate(run, advise_fn=advise, do_fn=do, check=check,
                         max_turns=2)
        out = it.run(state)

        self.assertEqual(out.turn, 2)
        self.assertFalse(out.accepted)
        self.assertEqual(out.best_level, 0)
        self.assertEqual(out.best_hash, best_hash)
        self.assertEqual((run.best / "candidate.v").read_text(), "best v1")
        # rejected sandboxes are preserved (astra-review semantics): each is
        # bound to feedback via last_rejected_hash and kept for inspection
        self.assertEqual(len(list(run.attempts.iterdir())), 2)
        self.assertTrue(out.last_rejected_dir)
        self.assertEqual([h["status"] for h in out.history],
                         ["rejected", "rejected"])
        self.assertIn("gate 'lint' failed: syntax error", out.feedback)
        self.assertIn("REJECTED candidate", out.feedback)

    def test_improve_promotes_sandbox_to_best(self):
        run = self._make_run()

        def advise(st):
            return "advice"

        def do(st, sandbox):
            _write(sandbox / "candidate.v", "better v1")
            return True, "wrote candidate"

        gates = [lambda sb: GateOutcome("g1", True)]
        check = ChiaCheckCondition(gates, accept_level=99)
        it = ChiaIterate(run, advise_fn=advise, do_fn=do, check=check,
                         max_turns=1)
        out = it.run(self._state())

        self.assertFalse(out.accepted)
        self.assertEqual(out.best_level, 1)
        self.assertEqual((run.best / "candidate.v").read_text(), "better v1")
        self.assertEqual(out.best_hash, manifest_hash(workspace_manifest(run.best)))

    def test_accept_stops_and_promotes(self):
        run = self._make_run()
        turns_seen = []

        def do(st, sandbox):
            turns_seen.append(st.turn)
            _write(sandbox / "candidate.v", f"good v{st.turn}")
            return True, "ok"

        gates = [lambda sb: GateOutcome("g1", True)]
        check = ChiaCheckCondition(gates, accept_level=1)
        it = ChiaIterate(run, advise_fn=lambda st: "a", do_fn=do, check=check,
                         max_turns=5)
        out = it.run(self._state())

        self.assertTrue(out.accepted)
        self.assertEqual(turns_seen, [1])
        self.assertEqual((run.best / "candidate.v").read_text(), "good v1")

    def test_no_milestone_progress_discards_attempt(self):
        run = self._make_run()
        _write(run.best / "candidate.v", "level2 candidate")
        state = self._state()
        state.best_level = 2
        state.best_manifest = workspace_manifest(run.best)
        state.best_hash = manifest_hash(state.best_manifest)

        def do(st, sandbox):
            _write(sandbox / "candidate.v", "different but same level")
            return True, "edited"

        gates = [lambda sb: GateOutcome("g1", True),
                 lambda sb: GateOutcome("g2", True)]
        check = ChiaCheckCondition(gates, accept_level=3)
        it = ChiaIterate(run, advise_fn=lambda st: "a", do_fn=do, check=check,
                         max_turns=1)
        out = it.run(state)

        self.assertEqual(out.best_level, 2)
        self.assertEqual((run.best / "candidate.v").read_text(), "level2 candidate")
        self.assertEqual(out.history[0]["status"], "no_progress")
        self.assertIn("No milestone progress", out.feedback)

    def test_stall_when_workspace_unchanged(self):
        run = self._make_run()
        _write(run.best / "candidate.v", "unchanged")
        state = self._state()
        state.best_manifest = workspace_manifest(run.best)
        state.best_hash = manifest_hash(state.best_manifest)

        def do(st, sandbox):
            return True, "did nothing"

        it = ChiaIterate(run, advise_fn=lambda st: "a", do_fn=do,
                         check=ChiaCheckCondition([]), max_turns=1)
        out = it.run(state)
        self.assertEqual(out.history[0]["status"], "stall")

    def test_retry_gate_discards_without_changing_best(self):
        run = self._make_run()
        _write(run.best / "candidate.v", "best")
        state = self._state()
        state.best_manifest = workspace_manifest(run.best)
        state.best_hash = manifest_hash(state.best_manifest)

        def do(st, sandbox):
            _write(sandbox / "candidate.v", "attempt")
            return True, "ok"

        gates = [lambda sb: GateOutcome("phys", False, note="yosys down",
                                        retry=True)]
        it = ChiaIterate(run, advise_fn=lambda st: "a", do_fn=do,
                         check=ChiaCheckCondition(gates), max_turns=1)
        out = it.run(state)
        self.assertEqual(out.history[0]["status"], "evaluator_infra_blocked")
        self.assertEqual(out.turn, 0)
        self.assertTrue(out.pending_evaluation)
        self.assertEqual((run.best / "candidate.v").read_text(), "best")
        # candidate preserved for inspection; infra retry did not consume
        # it silently (astra-review semantics)
        self.assertTrue((run.attempts / "turn_0001" / "candidate.v").exists())

    def test_implement_infra_failure_recorded(self):
        run = self._make_run()
        provider_up = {"value": False}

        def do(st, sandbox):
            if not provider_up["value"]:
                raise RuntimeError("ray down")
            _write(sandbox / "f", "recovered")
            return True, "ok"

        it = ChiaIterate(run, advise_fn=lambda st: "a", do_fn=do,
                         check=ChiaCheckCondition([]), max_turns=1,
                         infra_backoff=lambda attempt: 0.0)
        out = it.run(self._state())
        self.assertEqual(out.history[0]["status"], "implement_infra_failed")
        self.assertTrue(all(h["status"] == "implement_infra_failed"
                            for h in out.history))
        self.assertEqual(out.turn, 0)
        self.assertIn("implement infra failure", out.model_infra_blocked)

        provider_up["value"] = True
        resumed = it.run(IterationState(), resume=True)
        self.assertTrue(resumed.accepted)
        self.assertEqual(resumed.turn, 1)
        self.assertEqual(resumed.model_infra_blocked, "")

    def test_state_persisted_atomically_each_turn(self):
        run = self._make_run()

        def do(st, sandbox):
            _write(sandbox / "f.v", "x" * st.turn)
            return True, "ok"

        it = ChiaIterate(run, advise_fn=lambda st: "a", do_fn=do,
                         check=ChiaCheckCondition([lambda sb: GateOutcome("g", True)],
                                                  accept_level=99),
                         max_turns=2)
        out = it.run(self._state())
        loaded = IterationState.load(run.state_file)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.turn, 2)
        self.assertEqual(loaded.best_hash, out.best_hash)
        self.assertEqual(loaded.history, out.history)

    def test_resume_continues_from_saved_state(self):
        run = self._make_run()
        _write(run.best / "candidate.v", "prior best")
        saved = IterationState()
        saved.turn = 3
        saved.best_level = 1
        saved.best_manifest = workspace_manifest(run.best)
        saved.best_hash = manifest_hash(saved.best_manifest)
        saved.feedback = "prior feedback"
        saved.save(run.state_file)

        turns = []

        def do(st, sandbox):
            turns.append(st.turn)
            _write(sandbox / "candidate.v", "new attempt")
            return True, "ok"

        it = ChiaIterate(run, advise_fn=lambda st: "a", do_fn=do,
                         check=ChiaCheckCondition([lambda sb: GateOutcome("g", True)],
                                                  accept_level=99),
                         max_turns=4)
        out = it.run(IterationState(), resume=True)
        self.assertEqual(turns, [4], "resume must continue at saved turn+1")
        self.assertEqual(out.turn, 4)
        self.assertEqual(out.best_level, 1)

    def test_resume_without_state_starts_fresh(self):
        run = self._make_run()
        turns = []

        def do(st, sandbox):
            turns.append(st.turn)
            _write(sandbox / "f", "x")
            return True, "ok"

        it = ChiaIterate(run, advise_fn=lambda st: "a", do_fn=do,
                         check=ChiaCheckCondition([lambda sb: GateOutcome("g", True)],
                                                  accept_level=99),
                         max_turns=1)
        with self.assertRaisesRegex(RuntimeError, "checkpoint state missing"):
            it.run(IterationState(), resume=True)
        self.assertEqual(turns, [])

    def test_run_lock_refuses_live_flock_holder(self):
        import fcntl
        run = self._make_run()
        fd = os.open(run.lock_file, os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            def do(st, sandbox):
                _write(sandbox / "f", "x")
                return True, "ok"
            it = ChiaIterate(run, advise_fn=lambda st: "a", do_fn=do,
                             check=ChiaCheckCondition([]), max_turns=1)
            with self.assertRaises(RuntimeError):
                it.run(self._state())
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def test_run_lock_takeover_from_dead_owner(self):
        import fcntl
        run = self._make_run()
        run.lock_file.write_text(json.dumps({"pid": 2 ** 28, "ts": 0.0}))
        done = []

        def do(st, sandbox):
            done.append(st.turn)
            _write(sandbox / "f", "x")
            return True, "ok"

        it = ChiaIterate(run, advise_fn=lambda st: "a", do_fn=do,
                         check=ChiaCheckCondition([]), max_turns=1)
        it.run(self._state())
        self.assertEqual(done, [1])
        fd = os.open(run.lock_file, os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def test_best_snapshot_artifact_written_on_promotion(self):
        run = self._make_run()

        def do(st, sandbox):
            _write(sandbox / "candidate.v", "v1")
            return True, "ok"

        it = ChiaIterate(run, advise_fn=lambda st: "a", do_fn=do,
                         check=ChiaCheckCondition([lambda sb: GateOutcome("g", True)],
                                                  accept_level=99),
                         max_turns=1)
        it.run(self._state())
        snap = json.loads((run.artifacts / "best_snapshot.json").read_text())
        self.assertIn("candidate.v", snap["files"])
        self.assertEqual(snap["level"], 1)

    def test_partial_advance_promotes_attempt(self):
        run = self._make_run()

        def do(st, sandbox):
            _write(sandbox / "candidate.v", "partial candidate")
            return True, "ok"

        gates = [lambda sb: GateOutcome("lint", True),
                 lambda sb: GateOutcome("functional", False, note="128 mode broken")]
        it = ChiaIterate(run, advise_fn=lambda st: "a", do_fn=do,
                         check=ChiaCheckCondition(gates), max_turns=1)
        out = it.run(self._state())

        self.assertEqual(out.best_level, 1)
        self.assertEqual((run.best / "candidate.v").read_text(), "partial candidate")
        self.assertIn("128 mode broken", out.feedback)

    def test_advice_is_threaded_into_state_for_do_fn(self):
        run = self._make_run()
        seen = []

        def advise(st):
            return f"advice for turn {st.turn}"

        def do(st, sandbox):
            seen.append(st.advice)
            _write(sandbox / "candidate.v", f"v{st.turn}")
            return True, "ok"

        it = ChiaIterate(run, advise_fn=advise, do_fn=do,
                         check=ChiaCheckCondition([lambda sb: GateOutcome("g", True)],
                                                  accept_level=99),
                         max_turns=2)
        it.run(self._state())
        self.assertEqual(seen, ["advice for turn 1", "advice for turn 2"])

    def test_recover_best_from_interrupted_promotion(self):
        run = self._make_run()
        prev = run.root / "best.prev"
        _write(prev / "candidate.v", "recovered checkpoint")
        state = self._state()
        state.best_manifest = workspace_manifest(prev)
        state.best_hash = manifest_hash(state.best_manifest)

        def do(st, sandbox):
            return True, "did nothing"

        it = ChiaIterate(run, advise_fn=lambda st: "a", do_fn=do,
                         check=ChiaCheckCondition([]), max_turns=1)
        it.run(state)
        self.assertEqual((run.best / "candidate.v").read_text(),
                         "recovered checkpoint")
        self.assertFalse(prev.exists())

    def test_recover_prefers_checkpoint_state_does_not_vouch_for_best(self):
        run = self._make_run()
        old = run.root / "best.prev"
        _write(old / "candidate.v", "verified old best")
        _write(run.best / "candidate.v", "unverified newer install")
        state = self._state()
        state.best_manifest = workspace_manifest(old)
        state.best_hash = manifest_hash(state.best_manifest)

        def do(st, sandbox):
            return True, "did nothing"

        it = ChiaIterate(run, advise_fn=lambda st: "a", do_fn=do,
                         check=ChiaCheckCondition([]), max_turns=1)
        it.run(state)
        self.assertEqual((run.best / "candidate.v").read_text(),
                         "verified old best")

    def test_recover_keeps_best_state_vouches_and_drops_prev(self):
        run = self._make_run()
        prev = run.root / "best.prev"
        _write(prev / "candidate.v", "stale prev")
        _write(run.best / "candidate.v", "vouched best")
        state = self._state()
        state.best_manifest = workspace_manifest(run.best)
        state.best_hash = manifest_hash(state.best_manifest)

        def do(st, sandbox):
            return True, "did nothing"

        it = ChiaIterate(run, advise_fn=lambda st: "a", do_fn=do,
                         check=ChiaCheckCondition([]), max_turns=1)
        it.run(state)
        self.assertEqual((run.best / "candidate.v").read_text(), "vouched best")
        self.assertFalse(prev.exists())

    def test_verify_resume_inputs_refuses_changes(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            inputs = root / "inputs"
            inputs.mkdir()
            _write(inputs / "FFT64.v", "rtl")
            hf = root / "hashes.json"
            cf = root / "CONTRACT.md"
            hf.write_text(json.dumps({"FFT64.v": _sha256(inputs / "FFT64.v")}))
            cf.write_text("contract v1")
            verify_resume_inputs(inputs, hf, cf,
                                 {"FFT64.v": _sha256(inputs / "FFT64.v")},
                                 "contract v1")
            with self.assertRaises(RuntimeError):
                verify_resume_inputs(inputs, hf, cf, {"FFT64.v": "h2"},
                                     "contract v1")
            with self.assertRaises(RuntimeError):
                verify_resume_inputs(inputs, hf, cf,
                                     {"FFT64.v": _sha256(inputs / "FFT64.v")},
                                     "contract v2")
            with self.assertRaises(RuntimeError):
                verify_resume_inputs(root / "nope", hf, cf, {}, "contract v1")
            (inputs / "FFT64.v").write_text("tampered")
            with self.assertRaises(RuntimeError):
                verify_resume_inputs(inputs, hf, cf,
                                     {"FFT64.v": _sha256(inputs / "FFT64.v")},
                                     "contract v1")


@unittest.skipUnless(HAS_DEPS, "chia package unavailable")
class ExtractCodeBlockTests(unittest.TestCase):
    def test_fenced_verilog_block_extracted(self):
        text = "Here is the design:\n```verilog\nmodule a; endmodule\n```\nSUMMARY: made it"
        self.assertEqual(_extract_code_block(text), "module a; endmodule\n")

    def test_largest_block_wins_when_multiple(self):
        text = ("```verilog\nmodule small; endmodule\n```\n"
                "```verilog\nmodule big;\n  wire a, b, c;\n  assign a = b & c;\n"
                "  assign b = c | a;\n  assign c = ~a;\nendmodule\n```\n")
        self.assertIn("module big", _extract_code_block(text))

    def test_bare_module_reply_fallback(self):
        self.assertEqual(_extract_code_block("module x;\nendmodule"),
                         "module x;\nendmodule\n")

    def test_no_code_returns_empty(self):
        self.assertEqual(_extract_code_block("I could not do it."), "")


@unittest.skipUnless(HAS_DEPS, "chia package unavailable")
class DomainNeutralityTests(unittest.TestCase):
    """chia_merge.py is the domain-neutral primitive layer: no benchmark
    vocabulary may leak back into it."""

    def test_no_domain_vocabulary_in_primitives(self):
        import re
        src = (Path(__file__).resolve().parent / "chia_merge.py").read_text()
        # strip comments and docstrings crudely but effectively for this check
        body = re.sub(r'"""(?:.|\n)*?"""', " ", src)
        body = re.sub(r'[^_\w]#[^\n]*', " ", body)
        leaked = re.findall(r"\btwiddle\b|\bradix\b|\bfft\b|\bsdf\b|\bpeweaver\b",
                            body, flags=re.I)
        self.assertEqual(leaked, [],
                         f"domain vocabulary leaked into primitives: {leaked}")


@unittest.skipUnless(HAS_DEPS, "chia package unavailable")
class DriverGateLadderTests(unittest.TestCase):
    """make_gate_ladder's closures must resolve GateOutcome at module scope,
    not depend on a function-local import that never reaches them."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_gate_ladder_gates_construct_gate_outcomes(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        try:
            import peweaver_chia_graph as drv
        finally:
            sys.path.pop(0)
        run_root = self.root / "rr"
        run_root.mkdir()
        gates = drv.make_gate_ladder(run_root)
        out = gates[0](self.root / "empty_sandbox")
        self.assertEqual(out.name, "lint")
        self.assertFalse(out.passed)
        self.assertIn("missing", out.note)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Astra-review semantics: rejected-candidate preservation + eval retry
# ---------------------------------------------------------------------------

def test_reject_preserves_candidate_and_binds_feedback(tmp_path):
    run = RunPaths.create(tmp_path / "run")
    (run.inputs / "a.v").write_text("module a; endmodule\n")

    def advise_fn(st):
        return "adv"

    calls = {"n": 0}

    def do_fn(st, sandbox):
        calls["n"] += 1
        (sandbox / "cand.v").write_text(f"C{calls['n']}")
        return True, "ok"

    gates = [lambda sb: GateOutcome("g", False, note="bad counter")]
    check = ChiaCheckCondition(gates, accept_level=1)
    it = ChiaIterate(run, advise_fn=advise_fn, do_fn=do_fn, check=check,
                     max_turns=2)
    st = it.run(IterationState(), use_lock=False)
    assert st.last_rejected_dir, "rejected workspace must be preserved"
    assert (run.attempts / st.last_rejected_dir / "cand.v").exists()
    assert st.last_rejected_hash in st.feedback
    assert "REJECTED candidate" in st.feedback
    # feedback references a workspace that still exists on disk


def test_rejected_attempts_are_recorded_as_incumbent_siblings(tmp_path):
    run = RunPaths.create(tmp_path / "run")
    (run.best / "cand.v").write_text("incumbent")
    state = IterationState()
    state.best_manifest = workspace_manifest(run.best)
    state.best_hash = manifest_hash(state.best_manifest)
    incumbent_hash = state.best_hash
    calls = {"n": 0}
    observed = []

    def do_fn(st, sandbox):
        calls["n"] += 1
        (sandbox / "cand.v").write_text(f"rejected-{calls['n']}")
        return True, "ok"

    def on_attempt(turn, workspace_hash, result, st, evidence_path):
        status = st.model_status[str(turn)]
        observed.append((status["base_workspace_hash"],
                         status["transition_status"], workspace_hash))

    check = ChiaCheckCondition(
        [lambda sb: GateOutcome("g", False, note="semantic failure")],
        accept_level=1)
    out = ChiaIterate(
        run, advise_fn=lambda st: "advice", do_fn=do_fn, check=check,
        max_turns=2, on_attempt=on_attempt).run(state, use_lock=False)

    assert not out.accepted
    assert [entry[0] for entry in observed] == [incumbent_hash, incumbent_hash]
    assert [entry[1] for entry in observed] == ["rejected", "rejected"]
    assert observed[0][2] != observed[1][2]
    assert "rejected sibling" in out.feedback


def test_retry_reevaluates_same_sandbox_without_new_model_call(tmp_path):
    run = RunPaths.create(tmp_path / "run")
    (run.inputs / "a.v").write_text("module a; endmodule\n")

    advise_calls = {"n": 0}

    def advise_fn(st):
        advise_calls["n"] += 1
        return "adv"

    do_calls = {"n": 0}

    def do_fn(st, sandbox):
        do_calls["n"] += 1
        (sandbox / "cand.v").write_text("C1")
        return True, "ok"

    eval_calls = {"g1": 0, "g2": 0, "g3": 0}

    def first_gate(sb):
        eval_calls["g1"] += 1
        return GateOutcome("g1", True, note="clean")

    def flaky_gate(sb):
        eval_calls["g2"] += 1
        # infra failure twice, then a passing evaluation of the SAME text
        if eval_calls["g2"] <= 2:
            return GateOutcome("g2", False, note="ray down", retry=True)
        return GateOutcome("g2", True, note="clean")

    def last_gate(sb):
        eval_calls["g3"] += 1
        return GateOutcome("g3", True, note="clean")

    check = ChiaCheckCondition([first_gate, flaky_gate, last_gate], accept_level=3)
    it = ChiaIterate(run, advise_fn=advise_fn, do_fn=do_fn, check=check,
                     max_turns=1)
    st = it.run(IterationState(), use_lock=False)
    assert st.accepted
    assert advise_calls["n"] == 1 and do_calls["n"] == 1
    assert eval_calls == {"g1": 1, "g2": 3, "g3": 1}
    assert st.infra_retries == 2


def test_retry_exhaustion_is_resumable_without_consuming_turn(tmp_path):
    run = RunPaths.create(tmp_path / "run")
    (run.inputs / "a.v").write_text("module a; endmodule\n")

    def advise_fn(st):
        return "adv"

    def do_fn(st, sandbox):
        (sandbox / "cand.v").write_text("C1")
        return True, "ok"

    gate_up = {"value": False}
    eval_calls = {"n": 0}

    def flaky_infra(sb):
        eval_calls["n"] += 1
        return GateOutcome("g", gate_up["value"], note="up" if gate_up["value"] else "down",
                           retry=not gate_up["value"])

    check = ChiaCheckCondition([flaky_infra], accept_level=1)
    it = ChiaIterate(run, advise_fn=advise_fn, do_fn=do_fn, check=check,
                     max_turns=1)
    st = it.run(IterationState(), use_lock=False)
    assert not st.accepted
    assert st.turn == 0
    assert st.pending_evaluation["workspace_hash"]
    assert any(h.get("status") == "evaluator_infra_blocked" for h in st.history)
    assert (run.attempts / "turn_0001" / "cand.v").exists()

    gate_up["value"] = True
    resumed = it.run(IterationState(), resume=True, use_lock=False)
    assert resumed.accepted
    assert resumed.turn == 1
    assert not resumed.pending_evaluation
    assert eval_calls["n"] == 4


def test_parent_attestation_retries_failed_gate_without_model_call(tmp_path):
    reference = tmp_path / "ref.v"
    reference.write_text("module ref; endmodule\n")
    parent = tmp_path / "parent.v"
    parent.write_text("module candidate; endmodule\n")
    calls = {"g1": 0, "g2": 0}

    def first_gate(sb):
        calls["g1"] += 1
        return GateOutcome("g1", True)

    def flaky_gate(sb):
        calls["g2"] += 1
        if calls["g2"] == 1:
            return GateOutcome("g2", False, note="temporary", retry=True)
        return GateOutcome("g2", True)

    state = _cm(
        run_id="parent-retry", run_base=tmp_path / "runs",
        inputs={"ref.v": reference}, contract="contract",
        gates=[first_gate, flaky_gate], accept_level=2,
        adviser_model="test", implementer_model="test",
        candidate_filename="candidate.v", turns=0,
        mode="ParentOptimization", parent_candidate=parent,
        _adviser_factory=lambda **kw: (lambda prompt: (_ for _ in ()).throw(
            AssertionError("model must not be called"))),
        _implementer_factory=lambda **kw: (lambda prompt: (_ for _ in ()).throw(
            AssertionError("model must not be called"))),
    )
    assert state.parent_attested
    assert calls == {"g1": 1, "g2": 2}


def test_parent_attestation_infra_exhaustion_resumes_same_parent(tmp_path):
    reference = tmp_path / "ref.v"
    reference.write_text("module ref; endmodule\n")
    parent = tmp_path / "parent.v"
    parent.write_text("module candidate; endmodule\n")
    gate_up = {"value": False}
    calls = {"model": 0, "gate": 0}

    def gate(sb):
        calls["gate"] += 1
        return GateOutcome("physical", gate_up["value"],
                           note="clean" if gate_up["value"] else "tool down",
                           retry=not gate_up["value"])

    def adviser_factory(**kwargs):
        def adviser(prompt):
            calls["model"] += 1
            return "must not run"
        return adviser

    common = dict(
        run_id="parent-resume", run_base=tmp_path / "runs",
        inputs={"ref.v": reference}, contract="contract", gates=[gate],
        accept_level=1, adviser_model="test", implementer_model="test",
        candidate_filename="candidate.v", turns=0,
        mode="ParentOptimization", parent_candidate=parent,
        _adviser_factory=adviser_factory,
        _implementer_factory=lambda **kw: (lambda prompt: (False, "unused")),
    )
    blocked = _cm(**common)
    assert not blocked.parent_attested
    assert blocked.pending_evaluation["kind"] == "parent"
    assert blocked.turn == 0
    assert calls == {"model": 0, "gate": 3}

    gate_up["value"] = True
    resumed = _cm(**common, resume=True)
    assert resumed.parent_attested
    assert not resumed.pending_evaluation
    assert resumed.parent_hash == _sha256(parent)
    assert calls == {"model": 0, "gate": 4}


def test_ablate_no_feedback_suppresses_turns_and_feedback(tmp_path):
    run = RunPaths.create(tmp_path / "run")
    (run.inputs / "a.v").write_text("module a; endmodule\n")

    seen = {"feedback": [], "advice_turns": []}

    def do_fn(st, sandbox):
        seen["feedback"].append(st.feedback[:40])
        (sandbox / "cand.v").write_text(f"C{st.turn}")
        return True, "ok"

    MergePrompts = _mp; ChiaMerge = _cm
    gates = [lambda sb: GateOutcome("g", False, note="boom")]
    state = ChiaMerge(
        run_id="abl", run_base=tmp_path / "runs",
        inputs={"a.v": run.inputs / "a.v"},
        contract="c", gates=gates, accept_level=1,
        adviser_model="test", implementer_model="test",
        candidate_filename="cand.v", turns=2,
        prompts=MergePrompts(architecture="A {inputs} {sources} {contract}",
                             per_turn="T {turn} {best_level} {feedback}",
                             implement="I {candidate} {sources} {contract} "
                                       "{architecture} {advice} {feedback} "
                                       "{current}"),
        _adviser_factory=lambda **kw: (lambda p: "arch"),
        _implementer_factory=lambda **kw: (lambda p: (True,
                                                      "```verilog\nX\n```\n"
                                                      "SUMMARY: ok")),
        ablate_no_feedback=True)
    # turn 2's do_fn must have seen NO gate feedback
    assert "boom" not in "".join(seen["feedback"])


def test_parent_optimization_seeds_explicit_parent_and_preserves_metrics(tmp_path):
    reference = tmp_path / "ref.v"
    reference.write_text("module ref; endmodule\n")
    parent = tmp_path / "accepted.v"
    parent.write_text("module candidate; endmodule\n")
    seen = []

    state = _cm(
        run_id="parent", run_base=tmp_path / "runs",
        inputs={"ref.v": reference}, contract="contract",
        gates=[lambda sb: GateOutcome(
            "timing", True, detail={"metrics": {"setup_slack_ns": 0.2}})],
        accept_level=1, adviser_model="test", implementer_model="test",
        candidate_filename="candidate.v", turns=1,
        mode="ParentOptimization", parent_candidate=parent,
        config_hash="cfg",
        on_check=lambda turn, candidate_hash, result: seen.append(result.detail),
        prompts=_mp(architecture="{sources} {contract}",
                    per_turn="{architecture} {best_level} {feedback}",
                    implement="{candidate} {sources} {contract} {architecture} "
                              "{advice} {feedback} {current}"),
        _adviser_factory=lambda **kw: (lambda prompt: "plan"),
        _implementer_factory=lambda **kw: (lambda prompt: (
            True, "```verilog\nmodule candidate; /* changed */ endmodule\n```")),
    )

    assert state.mode == "ParentOptimization"
    assert state.parent_hash == _sha256(parent)
    assert state.best_level == 1
    assert seen[0]["timing"]["metrics"]["setup_slack_ns"] == 0.2


def test_merge_discovery_rejects_parent_candidate_before_execution(tmp_path):
    parent = tmp_path / "accepted.v"
    parent.write_text("candidate\n")
    with pytest.raises(ValueError, match="cannot receive a parent"):
        _cm(
            run_id="bad", run_base=tmp_path / "runs", inputs={}, contract="c",
            gates=[], accept_level=0, adviser_model="test",
            implementer_model="test", mode="MergeDiscovery",
            parent_candidate=parent,
        )


def test_fresh_merge_rejects_dirty_run_root(tmp_path):
    run_root = tmp_path / "runs" / "dirty"
    run_root.mkdir(parents=True)
    (run_root / "unexpected.txt").write_text("old candidate")
    with pytest.raises(RuntimeError, match="already contains artifacts"):
        _cm(
            run_id="dirty", run_base=tmp_path / "runs", inputs={}, contract="c",
            gates=[], accept_level=0, adviser_model="test",
            implementer_model="test",
        )


def test_resume_refuses_tampered_best_workspace(tmp_path):
    run = RunPaths.create(tmp_path / "run")
    _write(run.best / "candidate.v", "accepted")
    state = IterationState(accepted=True)
    state.best_manifest = workspace_manifest(run.best)
    state.best_hash = manifest_hash(state.best_manifest)
    state.save(run.state_file)
    (run.best / "candidate.v").write_text("tampered")
    it = ChiaIterate(
        run, advise_fn=lambda st: "a",
        do_fn=lambda st, sb: (True, "ok"),
        check=ChiaCheckCondition([]), max_turns=1,
    )
    with pytest.raises(RuntimeError, match="best workspace missing or modified"):
        it.run(IterationState(), resume=True)


def test_attempt_callback_runs_after_evidence_and_checkpoint(tmp_path):
    run = RunPaths.create(tmp_path / "run")
    captured = []

    def do_fn(st, sandbox):
        _write(sandbox / "candidate.v", "candidate")
        return True, "ok"

    def on_attempt(turn, workspace_hash, result, state, evidence_path):
        captured.append((state.to_dict(), evidence_path))

    it = ChiaIterate(
        run, advise_fn=lambda st: "a", do_fn=do_fn,
        check=ChiaCheckCondition(
            [lambda sb: GateOutcome("g", True)], accept_level=1),
        max_turns=1, on_attempt=on_attempt,
    )
    out = it.run(IterationState())
    assert out.accepted
    assert captured and captured[0][1].is_file()
    assert IterationState.load(run.state_file).to_dict() == captured[0][0]


def test_fake_backend_end_to_end_covers_both_campaign_modes(tmp_path):
    reference = tmp_path / "ref.v"
    reference.write_text("module ref; endmodule\n")
    parent = tmp_path / "accepted.v"
    parent.write_text("module candidate; endmodule\n")

    def run(mode, run_id, parent_candidate=None):
        return _cm(
            run_id=run_id, run_base=tmp_path / "runs", inputs={"ref.v": reference},
            contract="contract", gates=[lambda sb: GateOutcome("gate", True)],
            accept_level=1, adviser_model="fake", implementer_model="fake",
            candidate_filename="candidate.v", turns=1, mode=mode,
            parent_candidate=parent_candidate, config_hash=mode,
            prompts=_mp(architecture="{sources} {contract}",
                        per_turn="{architecture} {best_level} {feedback}",
                        implement="{candidate} {sources} {contract} {architecture} "
                                  "{advice} {feedback} {current}"),
            _adviser_factory=lambda **kw: (lambda prompt: "plan"),
            _implementer_factory=lambda **kw: (lambda prompt: (
                True, "module candidate; /* new */ endmodule\n")),
        )

    discovery = run("MergeDiscovery", "discovery")
    optimized = run("ParentOptimization", "optimization", parent)
    assert discovery.accepted and discovery.mode == "MergeDiscovery"
    assert optimized.accepted and optimized.parent_attested
