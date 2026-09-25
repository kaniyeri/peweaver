"""Unit tests for the Phase 2 FFT128 independent arithmetic oracle.

The oracle module (fft128_oracle.py) performs no file I/O; these tests are
the only place where the upstream golden vectors are loaded, satisfying the
Phase 2 acceptance gate of examples/peweaver/PHYSICAL_PPA_PLAN.md.
"""

import re
import unittest
from pathlib import Path

try:
    from .fft128_oracle import (
        DOCUMENTED_LATENCY,
        FRAME_SAMPLES,
        Fft128Oracle,
        _TWIDDLE128_TABLE,
        _TWIDDLE128_UNSELECTED,
        _complex_multiply,
        bitrev7,
        natural_order,
        run_frame,
        run_frames_streaming,
        to_signed16,
        to_unsigned16,
    )
    from .fft128_regression import load_vector_file
except ImportError:  # unittest discovery from this directory
    from fft128_oracle import (
        DOCUMENTED_LATENCY,
        FRAME_SAMPLES,
        Fft128Oracle,
        _TWIDDLE128_TABLE,
        _TWIDDLE128_UNSELECTED,
        _complex_multiply,
        bitrev7,
        natural_order,
        run_frame,
        run_frames_streaming,
        to_signed16,
        to_unsigned16,
    )
    from fft128_regression import load_vector_file

ROOT = Path(__file__).parent
FIXTURE = ROOT / "benchmarks" / "halo_fft128_reference"
THIRD_PARTY = ROOT / "third_party" / "r22sdf"


def _load_vectors():
    return {
        name: load_vector_file(FIXTURE / "vectors" / f"{name}.txt")
        for name in ("input4", "output4", "input5", "output5")
    }


class Q15ConversionTests(unittest.TestCase):
    def test_signed16_boundary_values(self):
        self.assertEqual(to_signed16(0x0000), 0)
        self.assertEqual(to_signed16(0x7FFF), 32767)
        self.assertEqual(to_signed16(0x8000), -32768)
        self.assertEqual(to_signed16(0xFFFF), -1)

    def test_unsigned16_wraps_like_the_rtl_wires(self):
        self.assertEqual(to_unsigned16(-1), 0xFFFF)
        self.assertEqual(to_unsigned16(-32768), 0x8000)
        self.assertEqual(to_unsigned16(65536), 0x0000)

    def test_q15_round_trip(self):
        for raw in range(0, 1 << 16):
            self.assertEqual(to_unsigned16(to_signed16(raw)), raw)


class MultiplyArithmeticTests(unittest.TestCase):
    def test_shared_core_matches_fft64_semantics(self):
        # the FFT128 oracle shares the fixed-point core with FFT64
        m_re, _ = _complex_multiply(0x7FFF, 0, 0x7FFF, 0)
        self.assertEqual(m_re, 32766)  # floor(32767^2 / 2^15)
        m_re, _ = _complex_multiply(0x8000, 0, 0x8000, 0)
        self.assertEqual(m_re, 0x8000)  # (-32768)^2 wraps on the 16-bit wire


class TwiddleTableTests(unittest.TestCase):
    def test_embedded_table_matches_the_pinned_rtl_literals(self):
        source = (THIRD_PARTY / "Twiddle128.v").read_text(encoding="utf-8")
        defined = {}
        unselected = set()
        for match in re.finditer(
                r"wn_re\[\s*(\d+)\]\s*=\s*16'h([0-9A-Fa-fx]{4})\s*;"
                r"\s*(?:assign\s*)?wn_im\[\s*(\d+)\]\s*=\s*16'h([0-9A-Fa-fx]{4})\s*;", source):
            index = int(match.group(1))
            self.assertEqual(index, int(match.group(3)))
            re_raw, im_raw = match.group(2).lower(), match.group(4).lower()
            if "x" in re_raw or "x" in im_raw:
                unselected.add(index)
            else:
                defined[index] = (int(re_raw, 16), int(im_raw, 16))
        self.assertEqual(len(defined) + len(unselected), 128)
        self.assertEqual(unselected, set(_TWIDDLE128_UNSELECTED))
        for index, expected in defined.items():
            self.assertEqual(_TWIDDLE128_TABLE[index], expected, index)
        for index in unselected:
            self.assertEqual(_TWIDDLE128_TABLE[index], (0, 0), index)  # two-state zero

    def test_bypass_and_minus_j_entries(self):
        self.assertEqual(_TWIDDLE128_TABLE[0], (0x0000, 0x0000))
        self.assertEqual(_TWIDDLE128_TABLE[32], (0x0000, 0x8000))  # the -j twiddle
        # W^64 is never selected by the R2^2SDF addressing for N=128
        self.assertIn(64, _TWIDDLE128_UNSELECTED)


class OrderingHelperTests(unittest.TestCase):
    def test_bitrev7_known_values(self):
        self.assertEqual(bitrev7(0), 0)
        self.assertEqual(bitrev7(1), 64)
        self.assertEqual(bitrev7(2), 32)
        self.assertEqual(bitrev7(64), 1)
        self.assertEqual(bitrev7(15), 120)

    def test_bitrev7_is_an_involution(self):
        for value in range(FRAME_SAMPLES):
            self.assertEqual(bitrev7(bitrev7(value)), value)

    def test_natural_order_maps_emission_to_bins(self):
        emission = [(k, 0) for k in range(FRAME_SAMPLES)]
        natural = natural_order(emission)
        for n in range(FRAME_SAMPLES):
            self.assertEqual(natural[n], (bitrev7(n), 0))


class Fft128OracleEndToEndTests(unittest.TestCase):
    def _drive_frame(self, samples):
        """Stream one frame; return (emission, first_output_cycle_relative)."""
        oracle = Fft128Oracle()
        oracle.reset()
        for _ in range(16):
            oracle.step(0, 0, 0, reset=True)
        for _ in range(256):
            oracle.step(0, 0, 0)
        stream_start = oracle.cycles
        for re, im in samples:
            oracle.step(1, re, im)
        emission = []
        first_cycle = None
        for _ in range(FRAME_SAMPLES + DOCUMENTED_LATENCY + 64):
            do_en, do_re, do_im = oracle.step(0, 0, 0)
            if do_en:
                if first_cycle is None:
                    first_cycle = oracle.cycles - stream_start
                emission.append((do_re, do_im))
            elif emission:
                break
        return oracle, emission, first_cycle

    def test_latency_and_output_validity_contract(self):
        vectors = _load_vectors()
        oracle, emission, first_cycle = self._drive_frame(vectors["input4"])
        self.assertEqual(first_cycle, DOCUMENTED_LATENCY)
        self.assertEqual(len(emission), FRAME_SAMPLES)
        self.assertFalse(oracle.step(0, 0, 0)[0])  # no extra output-valid cycle

    def test_input4_matches_output4_bit_exactly(self):
        vectors = _load_vectors()
        _, emission, _ = self._drive_frame(vectors["input4"])
        expected = [vectors["output4"][bitrev7(k)] for k in range(FRAME_SAMPLES)]
        self.assertEqual(emission, expected)
        self.assertEqual(natural_order(emission), vectors["output4"])

    def test_input5_matches_output5_bit_exactly(self):
        vectors = _load_vectors()
        _, emission, _ = self._drive_frame(vectors["input5"])
        self.assertEqual(natural_order(emission), vectors["output5"])

    def test_run_frame_matches_both_golden_vector_sets(self):
        vectors = _load_vectors()
        for input_name, output_name in (("input4", "output4"), ("input5", "output5")):
            with self.subTest(vector=input_name):
                emission = run_frame(vectors[input_name])
                self.assertEqual(natural_order(emission), vectors[output_name])

    def test_streaming_frames_match_goldens(self):
        vectors = _load_vectors()
        results = run_frames_streaming([vectors["input5"], vectors["input4"]])
        self.assertEqual(natural_order(results[0]), vectors["output5"])
        self.assertEqual(natural_order(results[1]), vectors["output4"])

    def test_repeated_run_frame_calls_are_deterministic(self):
        vectors = _load_vectors()
        self.assertEqual(run_frame(vectors["input4"]), run_frame(vectors["input4"]))

    def test_unselected_twiddle_entries_are_never_addressed(self):
        vectors = _load_vectors()
        oracle = Fft128Oracle()
        oracle.reset()
        for _ in range(16):
            oracle.step(0, 0, 0, reset=True)
        for _ in range(256):
            oracle.step(0, 0, 0)
        for re, im in vectors["input4"]:
            oracle.step(1, re, im)
        for _ in range(FRAME_SAMPLES + DOCUMENTED_LATENCY + 64):
            oracle.step(0, 0, 0)
        self.assertTrue(oracle.twiddle_addresses())
        self.assertEqual(oracle.twiddle_addresses() & set(_TWIDDLE128_UNSELECTED), set())

    def test_run_frame_rejects_wrong_frame_length(self):
        vectors = _load_vectors()
        with self.assertRaisesRegex(ValueError, "expected 128 samples"):
            run_frame(vectors["input4"][:127])
        with self.assertRaisesRegex(ValueError, "expected 128 samples"):
            run_frame(vectors["input4"] + [(0, 0)])

    def test_natural_order_rejects_wrong_length(self):
        with self.assertRaisesRegex(ValueError, "expected 128 emitted samples"):
            natural_order([(0, 0)] * 127)


class OracleIndependenceTests(unittest.TestCase):
    def test_oracle_module_does_no_file_io(self):
        source = (ROOT / "fft128_oracle.py").read_text(encoding="utf-8")
        for forbidden in ("open(", "read_text", "read_bytes", "write_text",
                          "pathlib", "Path(", "import os", "__file__"):
            self.assertNotIn(forbidden, source, forbidden)

    def test_oracle_module_is_dependency_free(self):
        source = (ROOT / "fft128_oracle.py").read_text(encoding="utf-8")
        imports = re.findall(
            r"^\s*(?:from|import)\s+([\w.]+)", source, re.MULTILINE)
        self.assertEqual({name.lstrip(".") for name in imports},
                         {"__future__", "fft64_oracle"})


if __name__ == "__main__":
    unittest.main()
