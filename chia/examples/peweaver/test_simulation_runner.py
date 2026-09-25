import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from .equivalence_runner import DEFAULT_BENCHMARK_ROOT, discover_manifests
    from .simulation_runner import resolve_verilator, simulation_spec
except ImportError:
    from equivalence_runner import DEFAULT_BENCHMARK_ROOT, discover_manifests
    from simulation_runner import resolve_verilator, simulation_spec

SIMULATION_MODULE = resolve_verilator.__module__


class SimulationRunnerTests(unittest.TestCase):
    def test_current_benchmarks_define_existing_simulation_fixtures(self):
        manifests = discover_manifests(DEFAULT_BENCHMARK_ROOT)
        for manifest in manifests:
            with self.subTest(name=manifest.name):
                testbench, top = simulation_spec(manifest)
                self.assertTrue(testbench.is_file())
                self.assertTrue(top.startswith("peweaver_"))

    @patch(f"{SIMULATION_MODULE}.shutil.which", return_value="/tools/verilator")
    def test_verilator_path_falls_back_to_path_lookup(self, which):
        with patch.dict(f"{SIMULATION_MODULE}.os.environ", {}, clear=True):
            self.assertEqual(resolve_verilator(), "/tools/verilator")
        which.assert_called_once_with("verilator")

    def test_testdata_manifest_without_simulation_fixture_is_rejected(self):
        manifest = next(manifest for manifest in discover_manifests(Path(__file__).with_name("testdata"))
                        if manifest.name == "equivalent")
        with self.assertRaisesRegex(ValueError, "simulation_testbench"):
            simulation_spec(manifest)


if __name__ == "__main__":
    unittest.main()
