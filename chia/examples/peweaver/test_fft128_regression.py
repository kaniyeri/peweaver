import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from .equivalence_runner import DEFAULT_BENCHMARK_ROOT, discover_manifests
    from .fft128_regression import load_fixture, load_vector_file, run_regression
except ImportError:  # unittest discovery from this directory
    from equivalence_runner import DEFAULT_BENCHMARK_ROOT, discover_manifests
    from fft128_regression import load_fixture, load_vector_file, run_regression

ROOT = Path(__file__).parent
FIXTURE = ROOT / "benchmarks" / "halo_fft128_reference"
THIRD_PARTY = ROOT / "third_party" / "r22sdf"
DOCUMENTED_LATENCY = 137
FFT128_REGRESSION_MODULE = run_regression.__module__


class Fft128ReferenceFixtureTests(unittest.TestCase):
    def test_reference_manifest_loads_and_validates(self):
        data = load_fixture(FIXTURE)
        self.assertEqual(data["schema_version"], 1)
        self.assertTrue(data["directed_top"].startswith("peweaver_"))
        for entry in data["sources"]:
            self.assertTrue((FIXTURE / entry).resolve().is_file(), entry)

    def test_reference_fixture_stays_out_of_the_formal_corpus(self):
        manifest = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
        for field in ("miter", "top", "expected_equivalent", "synthesis"):
            self.assertNotIn(field, manifest)
        names = {manifest_obj.name for manifest_obj in discover_manifests(DEFAULT_BENCHMARK_ROOT)}
        self.assertNotIn("halo_fft128_reference", names)
        self.assertEqual(names, {"equivalent_mode_exclusive_mac", "unsafe_simultaneous_mac",
                                 "threshold_mode_exclusive"})

    def test_reference_manifest_rejects_formal_and_synthesis_corpus_fields(self):
        for field, value in (("top", "some_miter"), ("synthesis", {})):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp_dir:
                data = load_fixture(FIXTURE)
                data[field] = value
                (Path(temp_dir) / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "must not define formal or synthesis-corpus fields"):
                    load_fixture(Path(temp_dir))

    def test_upstream_vectors_parse_to_128_samples(self):
        provenance = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))["upstream"]
        for vector_name in provenance["vector_files"]:
            path = FIXTURE / vector_name
            pairs = load_vector_file(path)
            self.assertEqual(len(pairs), 128, vector_name)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(digest, provenance["vector_files"][vector_name], vector_name)

    def test_known_upstream_golden_values(self):
        input4 = load_vector_file(FIXTURE / "vectors/input4.txt")
        output4 = load_vector_file(FIXTURE / "vectors/output4.txt")
        output5 = load_vector_file(FIXTURE / "vectors/output5.txt")
        self.assertEqual(input4[0], (0x7FFD, 0x0000))
        self.assertEqual(output4[1], (0x3ffe, 0xffff))  # first golden sample of the full-scale tone
        self.assertEqual(output5[15], (0x7FFD, 0xFFFF))  # bin-15 impulse for the k=15 tone

    def test_malformed_vector_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bad = Path(temp_dir) / "bad.txt"
            bad.write_text("7FFD 0000\nZZZZ 0000\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "malformed vector line"):
                load_vector_file(bad)
            short = Path(temp_dir) / "short.txt"
            short.write_text("7FFD 0000\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "expected 128 samples"):
                load_vector_file(short)

    def test_documented_latency_is_consistent_between_manifest_and_testbench(self):
        manifest = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["contract"]["performance"]["latency_cycles"], DOCUMENTED_LATENCY)
        testbench = (FIXTURE / manifest["directed_testbench"]).read_text(encoding="utf-8")
        self.assertIsNotNone(
            re.search(rf"localparam\s+int\s+FIRST_OUT\s*=\s*{DOCUMENTED_LATENCY}\s*;", testbench))

    def test_third_party_files_match_recorded_provenance_hashes(self):
        readme = (THIRD_PARTY / "README.md").read_text(encoding="utf-8")
        recorded = dict(re.findall(r"\|\s*`([^`]+)`\s*\|\s*`([0-9a-f]{64})`\s*\|", readme))
        self.assertEqual(set(recorded), {"FFT64.v", "FFT128.v", "SdfUnit.v", "SdfUnit2.v", "Butterfly.v",
                                         "DelayBuffer.v", "Multiply.v", "Twiddle64.v", "Twiddle128.v",
                                         "LICENSE"})
        for filename, digest in recorded.items():
            actual = hashlib.sha256((THIRD_PARTY / filename).read_bytes()).hexdigest()
            self.assertEqual(actual, digest, filename)

    @patch(f"{FFT128_REGRESSION_MODULE}.resolve_verilator", return_value=None)
    def test_missing_verilator_fails_closed(self, _resolve):
        result = run_regression(FIXTURE)
        self.assertEqual(result.status, "tool_error")
        self.assertFalse(result.passed)

    def test_missing_fixture_directory_fails_closed(self):
        result = run_regression(ROOT / "benchmarks" / "does_not_exist_fft128")
        self.assertEqual(result.status, "tool_error")
        self.assertFalse(result.passed)


if __name__ == "__main__":
    unittest.main()
