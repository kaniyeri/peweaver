"""Unit tests for the Phase 1 FFT64 independent arithmetic oracle.

The oracle module (fft64_oracle.py) performs no file I/O; these tests are the
only place where the upstream golden vectors are loaded, satisfying the
Phase 1 acceptance gate of examples/peweaver/PHYSICAL_PPA_PLAN.md.
"""

import re
import unittest
from pathlib import Path

try:
    from .fft64_oracle import (
        DOCUMENTED_LATENCY,
        FRAME_SAMPLES,
        Fft64Oracle,
        _TWIDDLE_TABLE,
        _TWIDDLE_UNSELECTED,
        _butterfly,
        _complex_multiply,
        bitrev6,
        natural_order,
        run_frame,
        run_frames_streaming,
        to_signed16,
        to_unsigned16,
    )
    from .fft64_regression import load_vector_file
except ImportError:  # unittest discovery from this directory
    from fft64_oracle import (
        DOCUMENTED_LATENCY,
        FRAME_SAMPLES,
        Fft64Oracle,
        _TWIDDLE_TABLE,
        _TWIDDLE_UNSELECTED,
        _butterfly,
        _complex_multiply,
        bitrev6,
        natural_order,
        run_frame,
        run_frames_streaming,
        to_signed16,
        to_unsigned16,
    )
    from fft64_regression import load_vector_file

ROOT = Path(__file__).parent
FIXTURE = ROOT / "benchmarks" / "halo_fft64_reference"
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
        self.assertEqual(to_unsigned16(-32769), 0x7FFF)  # modulo 2^16 wrap
        self.assertEqual(to_unsigned16(32768), 0x8000)   # -32768 on the wire
        self.assertEqual(to_unsigned16(65536), 0x0000)

    def test_q15_round_trip(self):
        for raw in range(0, 1 << 16):
            self.assertEqual(to_unsigned16(to_signed16(raw)), raw)


class ButterflyArithmeticTests(unittest.TestCase):
    def test_bf1_floor_rounding(self):
        y0_re, _, y1_re, _ = _butterfly(1, 0, 2, 0, rh=0)
        self.assertEqual((y0_re, y1_re), (1, 65535))  # floor(1.5)=1, floor(-0.5)=-1

    def test_bf2_round_half_up(self):
        y0_re, _, y1_re, _ = _butterfly(1, 0, 2, 0, rh=1)
        self.assertEqual((y0_re, y1_re), (2, 0))  # round(1.5) up, round(-0.5) up
        y0_re, _, _, _ = _butterfly(3, 0, 0, 0, rh=1)
        self.assertEqual(y0_re, 2)  # 1.5 -> 2
        y0_re, _, _, _ = _butterfly(0xFFFF, 0, 0, 0, rh=1)  # -1
        self.assertEqual(y0_re, 0)  # -0.5 -> 0 (half up)

    def test_no_wrap_on_the_shift_path(self):
        y0_re, _, _, _ = _butterfly(0x7FFF, 0, 0x7FFF, 0, rh=1)
        self.assertEqual(y0_re, 32767)  # floor(65535/2)
        y0_re, _, y1_re, _ = _butterfly(0x8000, 0, 0x8000, 0, rh=1)
        self.assertEqual(y0_re, 0x8000)  # floor((-65536+1)/2) = -32768
        _, _, y1_re, _ = _butterfly(0x8000, 0, 0x7FFF, 0, rh=0)
        self.assertEqual(y1_re, 0x8000)  # floor(-65535/2) = -32768

    def test_imaginary_component_is_independent(self):
        y0_re, y0_im, y1_re, y1_im = _butterfly(0, 10, 0, 3, rh=0)
        self.assertEqual((y0_re, y0_im), (0, 6))  # floor(13/2)=6
        self.assertEqual((y1_re, y1_im), (0, 3))  # floor(7/2)=3


class MultiplyArithmeticTests(unittest.TestCase):
    def test_real_scaling_floors_without_bias(self):
        m_re, m_im = _complex_multiply(0xFFFF, 0, 16384, 0)  # -1 * 0.5
        self.assertEqual((m_re, m_im), (0xFFFF, 0x0000))  # floor(-0.5) = -1

    def test_known_products(self):
        m_re, _ = _complex_multiply(0x7FFF, 0, 0x7FFF, 0)
        self.assertEqual(m_re, 32766)  # floor(32767^2 / 2^15)
        m_re, m_im = _complex_multiply(0x0000, 0x7FFF, 0x7FFF, 0)
        self.assertEqual((m_re, m_im), (0, 32766))
        m_re, m_im = _complex_multiply(0x0000, 0x7FFF, 0x0000, 0x7FFF)  # j*j = -1
        self.assertEqual((m_re, m_im), (0x8002, 0x0000))  # -32766 raw

    def test_modulo_wrap_on_the_sub_add_paths(self):
        m_re, _ = _complex_multiply(0x8000, 0, 0x8000, 0)  # (-32768)^2 -> 32768
        self.assertEqual(m_re, 0x8000)  # 32768 wraps to -32768 on the 16-bit wire

    def test_multiply_by_minus_j_twiddle_is_the_bf1_mj_mapping(self):
        wn16_re, wn16_im = _TWIDDLE_TABLE[16]
        self.assertEqual((wn16_re, wn16_im), (0x0000, 0x8000))
        for re, im in ((1, 2), (0xFFFF, 0x0001), (0x8000, 0x8000), (0x1234, 0xCDEF)):
            with self.subTest(sample=(re, im)):
                self.assertEqual(_complex_multiply(re, im, wn16_re, wn16_im),
                                 (im, to_unsigned16(-to_signed16(re))))


class TwiddleTableTests(unittest.TestCase):
    def test_embedded_table_matches_the_pinned_rtl_literals(self):
        source = (THIRD_PARTY / "Twiddle64.v").read_text(encoding="utf-8")
        defined = {}
        unselected = set()
        for match in re.finditer(
                r"wn_re\[\s*(\d+)\]\s*=\s*16'h([0-9A-Fa-fx]{4})\s*;"
                r"\s*assign\s*wn_im\[\s*(\d+)\]\s*=\s*16'h([0-9A-Fa-fx]{4})\s*;", source):
            index = int(match.group(1))
            self.assertEqual(index, int(match.group(3)))
            re_raw, im_raw = match.group(2).lower(), match.group(4).lower()
            if "x" in re_raw or "x" in im_raw:
                unselected.add(index)
            else:
                defined[index] = (int(re_raw, 16), int(im_raw, 16))
        self.assertEqual(len(defined) + len(unselected), 64)
        self.assertEqual(unselected, set(_TWIDDLE_UNSELECTED))
        for index, expected in defined.items():
            self.assertEqual(_TWIDDLE_TABLE[index], expected, index)
        for index in unselected:
            self.assertEqual(_TWIDDLE_TABLE[index], (0, 0), index)  # two-state zero

    def test_bypass_and_minus_j_entries(self):
        self.assertEqual(_TWIDDLE_TABLE[0], (0x0000, 0x0000))
        self.assertEqual(_TWIDDLE_TABLE[16], (0x0000, 0x8000))


class OrderingHelperTests(unittest.TestCase):
    def test_bitrev6_known_values(self):
        self.assertEqual(bitrev6(0), 0)
        self.assertEqual(bitrev6(1), 32)
        self.assertEqual(bitrev6(2), 16)
        self.assertEqual(bitrev6(32), 1)
        self.assertEqual(bitrev6(15), 60)

    def test_bitrev6_is_an_involution(self):
        for value in range(FRAME_SAMPLES):
            self.assertEqual(bitrev6(bitrev6(value)), value)

    def test_natural_order_maps_emission_to_bins(self):
        emission = [(k, 0) for k in range(FRAME_SAMPLES)]
        natural = natural_order(emission)
        for n in range(FRAME_SAMPLES):
            self.assertEqual(natural[n], (bitrev6(n), 0))


class Fft64OracleEndToEndTests(unittest.TestCase):
    def _drive_frame(self, samples):
        """Stream one frame; return (emission, first_output_cycle_relative_to_stream)."""
        oracle = Fft64Oracle()
        oracle.reset()
        for _ in range(16):
            oracle.step(0, 0, 0, reset=True)
        for _ in range(96):
            oracle.step(0, 0, 0)
        stream_start = oracle.cycles
        for re, im in samples:
            oracle.step(1, re, im)
        emission = []
        first_cycle = None
        for _ in range(FRAME_SAMPLES + DOCUMENTED_LATENCY + 32):
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
        expected = [vectors["output4"][bitrev6(k)] for k in range(FRAME_SAMPLES)]
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

    def test_back_to_back_streaming_matches_goldens(self):
        vectors = _load_vectors()
        results = run_frames_streaming([vectors["input5"], vectors["input4"]])
        self.assertEqual(natural_order(results[0]), vectors["output5"])
        self.assertEqual(natural_order(results[1]), vectors["output4"])

    def test_repeated_run_frame_calls_are_deterministic(self):
        vectors = _load_vectors()
        first = run_frame(vectors["input4"])
        second = run_frame(vectors["input4"])
        self.assertEqual(first, second)

    def test_unselected_twiddle_entries_are_never_addressed(self):
        vectors = _load_vectors()
        oracle = Fft64Oracle()
        oracle.reset()
        for _ in range(16):
            oracle.step(0, 0, 0, reset=True)
        for _ in range(96):
            oracle.step(0, 0, 0)
        for re, im in vectors["input4"]:
            oracle.step(1, re, im)
        for _ in range(FRAME_SAMPLES + DOCUMENTED_LATENCY + 32):
            oracle.step(0, 0, 0)
        self.assertTrue(oracle.twiddle_addresses())
        self.assertEqual(oracle.twiddle_addresses() & set(_TWIDDLE_UNSELECTED), set())

    def test_run_frame_rejects_wrong_frame_length(self):
        vectors = _load_vectors()
        with self.assertRaisesRegex(ValueError, "expected 64 samples"):
            run_frame(vectors["input4"][:63])
        with self.assertRaisesRegex(ValueError, "expected 64 samples"):
            run_frame(vectors["input4"] + [(0, 0)])

    def test_natural_order_rejects_wrong_length(self):
        with self.assertRaisesRegex(ValueError, "expected 64 emitted samples"):
            natural_order([(0, 0)] * 63)


class OracleIndependenceTests(unittest.TestCase):
    def test_oracle_module_does_no_file_io(self):
        source = (ROOT / "fft64_oracle.py").read_text(encoding="utf-8")
        for forbidden in ("open(", "read_text", "read_bytes", "write_text",
                          "pathlib", "Path(", "import os", "__file__"):
            self.assertNotIn(forbidden, source, forbidden)

    def test_oracle_module_is_dependency_free(self):
        source = (ROOT / "fft64_oracle.py").read_text(encoding="utf-8")
        imports = re.findall(r"^\s*(?:from|import)\s+(\w+)", source, re.MULTILINE)
        self.assertEqual(set(imports), {"__future__"})


if __name__ == "__main__":
    unittest.main()
