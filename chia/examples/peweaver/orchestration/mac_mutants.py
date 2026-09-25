#!/usr/bin/env python3
"""MAC mutation library: deliberate corruptions that must fail >=1 gate.

Each mutation returns a candidate text derived from an accepted shared MAC.
The test protocol applies every applicable mutant to the accepted candidate
and requires each to fail at least one gate in the frozen ladder (plan
section 17: verification of the verifier).
"""

from __future__ import annotations

import re
from pathlib import Path


def _sub_once(text: str, pattern: str, repl: str) -> str:
    new, n = re.subn(pattern, repl, text, count=1)
    if n != 1:
        raise ValueError(f"mutation anchor not found: {pattern}")
    return new


def mutate_signedness(text: str) -> str:
    """Interpret operand a as unsigned in the product."""
    if "$signed(a) * $signed(b)" in text:
        return text.replace("$signed(a) * $signed(b)",
                            "a * $signed(b)", 1)
    raise ValueError("no signed multiply anchor")


def mutate_acc_hold_mode1(text: str) -> str:
    """Break mode-1 accumulator hold by continuing accumulation."""
    if "acc <= acc + pa" not in text:
        raise ValueError("no accumulate anchor")
    # replace the mode-1 product-only branch with a corrupting accumulate
    new = _sub_once(text, r"else if \(en && mode\) y <= pa;",
                    "else if (en && mode) begin acc <= acc + pa; "
                    "y <= pa; end")
    return new


def mutate_reset_ignored(text: str) -> str:
    """Drop the accumulator clear on reset."""
    return _sub_once(text, r"if \(reset\) begin acc <= 0; y <= 0; end",
                     "if (reset) begin y <= 0; end")


def mutate_enable_ignored(text: str) -> str:
    """Treat en as always asserted (hold behavior lost)."""
    if "else if (en && !mode)" in text:
        return text.replace("else if (en && !mode)",
                            "else if (1'b1 || (en && !mode))", 1)
    if "else if (en)" in text:
        return text.replace("else if (en)", "else if (1'b1 || en)", 1)
    raise ValueError("no enable anchor")


def mutate_unshared_recompute(text: str) -> str:
    """Mode-1 recomputes the product with commuted operands (b*a == a*b).
    This is NOT a hardware-sharing violation: opt -full proves the commuted
    expression shares the one multiplier. Kept as a NO-OVERREJECT check: the
    structure gate must NOT reject legal operand commutation (Sol-review
    classification; the naive_two_mult selftest control covers real
    duplication)."""
    if "else if (en && mode) y <= pa;" in text:
        return text.replace(
            "else if (en && mode) y <= pa;",
            "else if (en && mode) y <= $signed(b) * $signed(a);", 1)
    raise ValueError("no mode-1 product anchor")


def mutate_output_width(text: str) -> str:
    """Truncate the product to 12 bits (LSB-side corruption)."""
    return _sub_once(text, r"wire signed \[15:0\] pa = \$signed\(a\) \* \$signed\(b\)",
                     "wire signed [15:0] pa_full = $signed(a) * $signed(b);\n"
                     "  wire signed [15:0] pa = {4'b0000, pa_full[15:4]}")


CANONICAL_SHARED_MAC = (
    "module shared_mac(input wire clock, input wire reset, "
    "input wire mode, input wire en, input wire [7:0] a, "
    "input wire [7:0] b, output reg [15:0] y);\n"
    "  wire signed [15:0] pa = $signed(a) * $signed(b);\n"
    "  reg [15:0] acc;\n"
    "  always @(posedge clock) begin\n"
    "    if (reset) begin acc <= 0; y <= 0; end\n"
    "    else if (en && !mode) begin acc <= acc + pa; y <= acc + pa; end\n"
    "    else if (en && mode) y <= pa;\n"
    "  end\n"
    "endmodule\n")

MUTATIONS: dict[str, callable] = {
    "signedness": mutate_signedness,
    "acc_hold_mode1": mutate_acc_hold_mode1,
    "reset_ignored": mutate_reset_ignored,
    "enable_ignored": mutate_enable_ignored,
    "unshared_recompute": mutate_unshared_recompute,
    "output_truncation": mutate_output_width,
}

# expected verdict per mutation: True -> must fail >=1 gate (violation);
# False -> must NOT be rejected (no-overreject property of the gates)
EXPECTED_CAUGHT: dict[str, bool] = {
    "signedness": True,
    "acc_hold_mode1": True,
    "reset_ignored": True,
    "enable_ignored": True,
    "unshared_recompute": False,
    "output_truncation": True,
}


def apply_mutation(name: str, accepted_rtl: str) -> str:
    if name not in MUTATIONS:
        raise KeyError(f"unknown mutation: {name}")
    return MUTATIONS[name](accepted_rtl)


def run_mutation_suite(accepted_rtl_path: Path, gates, work: Path) -> dict:
    """Apply every mutation to a known-good candidate; require each to fail
    at least one gate. Returns a machine-readable report.

    The canonical known-good candidate (CANONICAL_SHARED_MAC, identical to
    the driver selftest's positive control) is used as the mutation base so
    every anchor is applicable regardless of which candidate text a model
    produced; the gates — not the candidate text — are what is verified."""
    accepted = CANONICAL_SHARED_MAC
    report = {}
    work.mkdir(parents=True, exist_ok=True)
    for name, fn in MUTATIONS.items():
        try:
            mutant_text = fn(accepted)
        except ValueError as exc:
            report[name] = {"applicable": False, "reason": str(exc)}
            continue
        d = work / name
        d.mkdir(exist_ok=True)
        (d / "shared_mac.v").write_text(mutant_text)
        outcomes = [g(d) for g in gates]
        failed = [o.name for o in outcomes if not o.passed]
        expected = EXPECTED_CAUGHT.get(name, True)
        report[name] = {
            "applicable": True, "failed_gates": failed,
            "caught": bool(failed), "expected_caught": expected,
            "as_expected": bool(failed) == expected,
            "notes": {o.name: o.note[:80] for o in outcomes
                      if not o.passed}}
    report["suite_valid"] = all(
        v.get("as_expected", False) for v in report.values()
        if isinstance(v, dict) and v.get("applicable"))
    return report


if __name__ == "__main__":
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--accepted", required=True, type=Path)
    parser.add_argument("--work", required=True, type=Path)
    args = parser.parse_args()
    print("use run_mutation_suite() from the driver; CLI is for inspection")
    print(json.dumps({k: fn.__doc__ for k, fn in MUTATIONS.items()}, indent=1))
