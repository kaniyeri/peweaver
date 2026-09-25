import unittest

try:
    from .equivalence_runner import DEFAULT_BENCHMARK_ROOT, discover_manifests
    from .synthesis_runner import load_synthesis_spec, make_script
except ImportError:
    from equivalence_runner import DEFAULT_BENCHMARK_ROOT, discover_manifests
    from synthesis_runner import load_synthesis_spec, make_script


class SynthesisRunnerTests(unittest.TestCase):
    def test_current_benchmarks_define_synthesis_alternatives(self):
        manifests = discover_manifests(DEFAULT_BENCHMARK_ROOT)
        for manifest in manifests:
            with self.subTest(name=manifest.name):
                spec = load_synthesis_spec(manifest)
                self.assertTrue(spec.baseline_top.startswith("peweaver_"))
                self.assertTrue(spec.candidate_top.startswith("peweaver_"))
                self.assertIn(f"hierarchy -top {spec.baseline_top}", make_script(manifest, spec.baseline_top))


if __name__ == "__main__":
    unittest.main()
