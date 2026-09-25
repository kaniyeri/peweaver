import json
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from .equivalence_runner import DEFAULT_BENCHMARK_ROOT, discover_manifests, make_script, run_manifest
except ImportError:  # unittest discovery from this directory
    from equivalence_runner import DEFAULT_BENCHMARK_ROOT, discover_manifests, make_script, run_manifest

EQUIVALENCE_MODULE = run_manifest.__module__


class RunnerTests(unittest.TestCase):
    def make_manifest(self, expected=True):
        root = Path(__file__).with_name("testdata")
        manifest = root / ("equivalent.json" if expected else "inequivalent.json")
        return root, json.loads(manifest.read_text(encoding="utf-8")) and discover_manifests(root)[0 if expected else 1]

    def test_discovery_and_script(self):
        _, manifest = self.make_manifest()
        self.assertIn("prep -top m -flatten", make_script(manifest))
        self.assertIn("sat -verify -prove mismatch 0", make_script(manifest))

    def test_default_corpus_has_three_manifests(self):
        manifests = discover_manifests(DEFAULT_BENCHMARK_ROOT)
        self.assertEqual({manifest.name for manifest in manifests},
                         {"equivalent_mode_exclusive_mac", "unsafe_simultaneous_mac",
                          "threshold_mode_exclusive"})

    @patch(f"{EQUIVALENCE_MODULE}.resolve_yosys", return_value=None)
    def test_missing_tool_fails_closed(self, _resolve):
        _, manifest = self.make_manifest()
        result = run_manifest(manifest)
        self.assertEqual(result.status, "tool_error")
        self.assertFalse(result.passed)

    @patch(f"{EQUIVALENCE_MODULE}.subprocess.run")
    def test_equivalent_and_expected_match(self, run):
        _, manifest = self.make_manifest()
        run.return_value = type("P", (), {"returncode": 0, "stdout": "SAT proof finished - no model found\n", "stderr": ""})()
        result = run_manifest(manifest, yosys="yosys")
        self.assertEqual(result.status, "equivalent")
        self.assertTrue(result.passed)
        run.assert_called_once()

    @patch(f"{EQUIVALENCE_MODULE}.subprocess.run")
    def test_counterexample_is_inequivalent(self, run):
        _, manifest = self.make_manifest(expected=False)
        run.return_value = type("P", (), {"returncode": 1, "stdout": "SAT: model found\n", "stderr": ""})()
        result = run_manifest(manifest, yosys="yosys")
        self.assertEqual(result.status, "inequivalent")
        self.assertTrue(result.passed)

    @patch(f"{EQUIVALENCE_MODULE}.subprocess.run", side_effect=OSError("boom"))
    def test_process_error_fails_closed(self, _run):
        _, manifest = self.make_manifest()
        result = run_manifest(manifest, yosys="yosys")
        self.assertEqual(result.status, "tool_error")
        self.assertFalse(result.passed)


if __name__ == "__main__":
    unittest.main()
