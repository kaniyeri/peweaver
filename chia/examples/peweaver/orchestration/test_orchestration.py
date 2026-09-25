"""Stdlib-only safety tests for the PEWeaver orchestration boundary."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from .config import OrchestrationConfig
from .peweaver_gemini_loop import (
    changed_protected_files,
    path_kind,
    restore_protected_files,
    restore_regular_file,
)
from .runner import (
    dispatch_ray,
    evaluate_local,
    outcome_from_results,
    preflight,
    vertex_connectivity_proof,
    write_manifest,
)


class OrchestrationSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]
        self.tmp = tempfile.TemporaryDirectory()
        self.config = OrchestrationConfig(
            benchmark_root=self.root,
            manifest_dir=Path(self.tmp.name),
            vertex_project="test-project",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_module_does_not_require_cloud_runtime(self) -> None:
        # This suite itself imports only stdlib plus orchestration modules.
        self.assertTrue(preflight(self.config)["passed"])

    def test_missing_bundle_is_blocked(self) -> None:
        config = OrchestrationConfig(Path(self.tmp.name) / "absent", Path(self.tmp.name))
        result = preflight(config)
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["passed"])
        self.assertTrue(any("required PEWeaver source" in e for e in result["errors"]))

    def test_local_evaluator_exception_fails_closed(self) -> None:
        result = evaluate_local(self.config, evaluator=lambda: (_ for _ in ()).throw(TimeoutError("timed out")))
        self.assertEqual(result.status, "error")
        self.assertFalse(result.passed)
        self.assertFalse(result.candidate_accepted)

    def test_unknown_tool_result_cannot_pass_or_accept(self) -> None:
        result = outcome_from_results([{
            "status": "tool_error", "passed": False,
            "actual_equivalent": None, "expected_equivalent": True,
        }])
        self.assertFalse(result.passed)
        self.assertFalse(result.candidate_accepted)

    def test_explicit_expected_mismatch_cannot_pass(self) -> None:
        result = outcome_from_results([{
            "status": "inequivalent", "passed": False,
            "actual_equivalent": False, "expected_equivalent": True,
        }])
        self.assertFalse(result.passed)
        self.assertFalse(result.candidate_accepted)

    def test_vertex_requires_both_gates_and_does_not_import_without_them(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            result = vertex_connectivity_proof(self.config, cli_authorized=False)
        self.assertEqual(result["status"], "not_authorized")
        self.assertFalse(result["attempted"])

    def test_cloud_dispatch_requires_both_gates(self) -> None:
        with patch.dict(os.environ, {"RAY_ADDRESS": "ray://example", "PEWEAVER_ALLOW_CHIA_DISPATCH": "0"}, clear=True):
            result = dispatch_ray(self.config, cli_authorized=False)
        self.assertFalse(result.passed)
        self.assertIn("two-gate", result.error)

    def test_cloud_dispatch_checks_yosys_before_chia_import(self) -> None:
        class FakeRay:
            @staticmethod
            def is_initialized():
                return True

            @staticmethod
            def cluster_resources():
                return {"vertex_creds": 1.0}

            @staticmethod
            def available_resources():
                return {"vertex_creds": 1.0}

        config = OrchestrationConfig(self.root, Path(self.tmp.name), ray_address="auto")
        with patch.dict(os.environ, {"PEWEAVER_ALLOW_CHIA_DISPATCH": "1"}, clear=True), \
                patch.dict(sys.modules, {"ray": FakeRay}, clear=False):
            result = dispatch_ray(config, cli_authorized=True)
        self.assertFalse(result.passed)
        self.assertIn("yosys", result.error)

    def test_vertex_checks_live_worker_before_remote_call(self) -> None:
        class FakeRay:
            @staticmethod
            def is_initialized():
                return True

            @staticmethod
            def cluster_resources():
                return {"yosys": 1.0}

            @staticmethod
            def available_resources():
                return {"yosys": 1.0}

        with patch.dict(os.environ, {"PEWEAVER_ALLOW_VERTEX_BILLABLE": "1"}, clear=True), \
                patch.dict(sys.modules, {"ray": FakeRay}, clear=False):
            result = vertex_connectivity_proof(self.config, cli_authorized=True)
        self.assertFalse(result["attempted"])
        self.assertIn("vertex_creds", result["error"])

    def test_manifest_redacts_ray_address_and_never_persists_secrets(self) -> None:
        config = OrchestrationConfig(self.root, Path(self.tmp.name), ray_address="secret-ray-address")
        pf = preflight(config)
        path = write_manifest(config, preflight_result=pf, run_id="test-run")
        document = json.loads(path.read_text(encoding="utf-8"))
        encoded = path.read_text(encoding="utf-8")
        self.assertNotIn("secret-ray-address", encoded)
        self.assertNotIn("ray_address", document["config"])
        self.assertEqual(document["run_id"], "test-run")
        self.assertTrue(document["config_hash"])
        self.assertTrue(document["source_hashes"])

    def test_candidate_restore_replaces_symlink_without_following_it(self) -> None:
        root = Path(self.tmp.name)
        target = root / "unrelated-secret"
        target.write_bytes(b"do-not-touch")
        candidate = root / "candidate.v"
        candidate.symlink_to(target)

        restore_regular_file(
            candidate, b"accepted-rtl\n", 0o600,
            quarantine_dir=root / "quarantine")

        self.assertEqual(path_kind(candidate), "regular")
        self.assertEqual(candidate.read_bytes(), b"accepted-rtl\n")
        self.assertEqual(target.read_bytes(), b"do-not-touch")

    def test_candidate_restore_quarantines_directory_replacement(self) -> None:
        root = Path(self.tmp.name)
        candidate = root / "candidate.v"
        candidate.mkdir()
        (candidate / "model-output").write_text("preserved", encoding="utf-8")

        quarantine = restore_regular_file(
            candidate, b"accepted-rtl\n", 0o644,
            quarantine_dir=root / "quarantine")

        self.assertEqual(path_kind(candidate), "regular")
        self.assertEqual(candidate.read_bytes(), b"accepted-rtl\n")
        self.assertIsNotNone(quarantine)
        self.assertEqual(
            (Path(quarantine) / "model-output").read_text(encoding="utf-8"),
            "preserved")

    def test_protected_file_snapshot_is_restored(self) -> None:
        root = Path(self.tmp.name)
        protected = root / "judge.py"
        original = b"immutable = True\n"
        protected.write_bytes(original)
        rel = "judge.py"
        expected = {rel: hashlib.sha256(original).hexdigest()}
        snapshots = {rel: (original, 0o644)}
        protected.write_bytes(b"immutable = False\n")

        changed = changed_protected_files(root, expected)
        restored, errors = restore_protected_files(
            root, changed, snapshots, quarantine_dir=root / "quarantine")

        self.assertEqual(changed, [rel])
        self.assertEqual(restored, [rel])
        self.assertEqual(errors, [])
        self.assertEqual(protected.read_bytes(), original)

    def test_candidate_restore_replaces_fifo_without_opening_it(self) -> None:
        root = Path(self.tmp.name)
        candidate = root / "candidate.v"
        os.mkfifo(candidate)

        restore_regular_file(
            candidate, b"accepted-rtl\n", 0o644,
            quarantine_dir=root / "quarantine")

        self.assertEqual(path_kind(candidate), "regular")
        self.assertEqual(candidate.read_bytes(), b"accepted-rtl\n")


if __name__ == "__main__":
    unittest.main()
