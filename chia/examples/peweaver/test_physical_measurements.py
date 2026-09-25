#!/usr/bin/env python3
"""Focused regressions for physical-result measurement arithmetic."""

import tempfile
import unittest
import copy
import json
from pathlib import Path

try:
    from .physical.assemble_results import (
        finite_window_energy_nj,
        build_flow_input_hashes,
        last_vcd_timestamp_ps,
        load_staged_leakage_check,
        validate_leakage_check,
        DESIGNS,
        PHYS,
    )
    from .physical.vcd_normalize import canonicalize_and_shift
except ImportError:  # unittest discovery from examples/peweaver.
    from physical.assemble_results import (
        finite_window_energy_nj,
        build_flow_input_hashes,
        last_vcd_timestamp_ps,
        load_staged_leakage_check,
        validate_leakage_check,
        DESIGNS,
        PHYS,
    )
    from physical.vcd_normalize import canonicalize_and_shift


class PhysicalMeasurementTests(unittest.TestCase):
    def test_half_cycle_vcd_duration_is_not_floored(self):
        with tempfile.TemporaryDirectory() as tmp:
            vcd = Path(tmp) / "window.vcd"
            vcd.write_text("$timescale 1ps $end\n#0\n#2625000\n", encoding="utf-8")
            duration_ps = last_vcd_timestamp_ps(vcd)

        self.assertEqual(duration_ps, 2_625_000)
        self.assertAlmostEqual(
            finite_window_energy_nj(23.31441, duration_ps, 3),
            20.40010875,
            places=8,
        )

    def test_fft128_archived_window_energy(self):
        self.assertAlmostEqual(
            finite_window_energy_nj(41.04030, 5_205_000, 3),
            71.2049205,
            places=7,
        )

    def test_vcd_wall_clock_header_is_canonicalized(self):
        first = ["$date", "  first wall clock", "$end", "#25", "1!"]
        second = ["$date", "  another wall clock", "$end", "#25", "1!"]
        expected = [
            "$date",
            "  normalized by vcd_normalize.py",
            "$end",
            "#0",
            "1!",
        ]
        self.assertEqual(canonicalize_and_shift(first, 25), expected)
        self.assertEqual(canonicalize_and_shift(second, 25), expected)

    def test_frozen_leakage_record_is_validated(self):
        record = json.loads(
            (PHYS / "leakage_check/nand2_leakage_check.json").read_text())
        validate_leakage_check(record)

        bad = copy.deepcopy(record)
        bad["measured"][1]["input_state"] = "!A&!B"
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_leakage_check(bad)

        bad = copy.deepcopy(record)
        bad["measured"][0]["leakage_w"] *= 2
        with self.assertRaisesRegex(ValueError, "power/current"):
            validate_leakage_check(bad)

        bad = copy.deepcopy(record)
        bad["measured"][0]["current_a"] = float("nan")
        with self.assertRaisesRegex(ValueError, "finite"):
            validate_leakage_check(bad)

    def test_flow_hashes_cover_exact_templates_leakage_and_vectors(self):
        hashes = build_flow_input_hashes(
            "dual_b", DESIGNS["dual_b"],
            synth_template="synth/dual_b_synth.ys",
            frontend_template="openroad/dual_b_d050_frontend_holdfix.tcl",
            backend_template="openroad/fft64_backend.tcl")
        required = {
            "openroad/dual_b_d050_frontend_holdfix.tcl",
            "leakage_check/nand2_leakage_check.json",
            "leakage_check/nand2_leak.spice",
            "leakage_check/run_leakage_check.sh",
            "rtl/peweaver_ppa_fft64.v",
            "rtl/peweaver_ppa_fft128.v",
            "../benchmarks/halo_fft64_reference/manifest.json",
            "../benchmarks/halo_fft128_reference/manifest.json",
            "../benchmarks/halo_fft64_reference/vectors/input4.txt",
            "../benchmarks/halo_fft128_reference/vectors/output5.txt",
        }
        self.assertTrue(required.issubset(hashes), required - set(hashes))
        self.assertNotIn("openroad/fft64_frontend.tcl", hashes)

    def test_staged_leakage_record_must_match_source_bytes(self):
        source_bytes = (
            PHYS / "leakage_check/nand2_leakage_check.json").read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.json"
            staged = Path(tmp) / "staged.json"
            source.write_bytes(source_bytes)
            staged.write_bytes(source_bytes)
            self.assertEqual(load_staged_leakage_check(source, staged)["schema"],
                             "peweaver-leakage-check-1")
            staged.write_bytes(source_bytes + b"\n")
            with self.assertRaisesRegex(ValueError, "differs"):
                load_staged_leakage_check(source, staged)


if __name__ == "__main__":
    unittest.main()
