#!/usr/bin/env python3
"""Pure-Python oracle and stimulus generators for the DWT merge benchmark.

Implements exactly the semantics frozen in
``campaigns/dwt_campaign/TIGHTENED_CAMPAIGN_SPEC.md``:

- latest-first 4-tap window per context, zero prehistory;
- pinned signed Q15 db2 low/high coefficients;
- exact signed 16x16 products, sign-extended to 40 bits, summed modulo 2**40;
- per-context accepted-sample index parity drives level-1 output/valid;
- level-2 input is ``q(v) = signed16(v[30:15])`` of the generated level-1
  low result; a job is created on odd pair indices and consumed on the next
  enabled sample with no level-1 output due.

This module is model-free and controller-owned. It is never exposed to a model
worker and contains no hidden stimulus.
"""

from __future__ import annotations

from pathlib import Path

COEF_H = (15826, 27411, 7345, -4240)
COEF_G = (-4240, -7345, 27411, -15826)
MOD = 1 << 40

PUBLIC_SEED = 0xD17A5EED
HIDDEN_SEED = 0x7D17BEEF

# Directed mutant-corner case (mutant 4: truncation [30:15] vs [31:16]):
# context-B accepted samples in order 0..3. The level-1 low result at
# accepted-sample index 3 is 0xFFFB9F19A7, whose bit 31 (1) differs from its
# bit 15 (0), so the two truncations provably differ.
MUTANT_CORNER_B_SAMPLES = (-19336, 27280, -20681, 13337)


def s16(v: int) -> int:
    return v - 65536 if v >= 32768 else v


def q16(v: int) -> int:
    """signed16(v[30:15]) of a 40-bit two's-complement value."""
    u = v & (MOD - 1)
    b = (u >> 15) & 0xFFFF
    return b - 65536 if b >= 32768 else b


def dot40(window, coef) -> int:
    return sum(coef[i] * s16(window[i]) for i in range(4)) % MOD


def _l1(window):
    return dot40(window, COEF_H), dot40(window, COEF_G)


def oracle_stream(stim):
    """Cycle-aligned 9-tuples for (ctx, en, x, rst) stimulus tuples.

    Tuple order: a_l1_lo, a_l1_hi, a_l1_valid, b_l1_lo, b_l1_hi, b_l1_valid,
    b_l2_lo, b_l2_hi, b_l2_valid. Data values are unsigned modulo 2**40.
    """
    wa = [0, 0, 0, 0]
    wb = [0, 0, 0, 0]
    wl = [0, 0, 0, 0]
    pa = pb = mpar = 0
    pending = False
    a_lo = a_hi = 0
    b_lo = b_hi = 0
    l2_lo = l2_hi = 0
    out = []
    for ctx, en, x, rst in stim:
        va = vb = vl = 0
        if rst:
            wa = [0, 0, 0, 0]
            wb = [0, 0, 0, 0]
            wl = [0, 0, 0, 0]
            pa = pb = mpar = 0
            pending = False
            a_lo = a_hi = b_lo = b_hi = l2_lo = l2_hi = 0
        elif en:
            xs = s16(x)
            if ctx == 0:
                nw = [xs, wa[0], wa[1], wa[2]]
                wa = nw
                if pa:
                    a_lo, a_hi = _l1(nw)
                    va = 1
                pa ^= 1
            else:
                nw = [xs, wb[0], wb[1], wb[2]]
                wb = nw
                if pb:
                    b_lo, b_hi = _l1(nw)
                    vb = 1
                    wl = [q16(b_lo), wl[0], wl[1], wl[2]]
                    if mpar:
                        pending = True
                    mpar ^= 1
                elif pending:
                    l2_lo, l2_hi = _l1(wl)
                    vl = 1
                    pending = False
                pb ^= 1
        out.append((a_lo, a_hi, va, b_lo, b_hi, vb, l2_lo, l2_hi, vl))
    return out


def x_of(k: int) -> int:
    """Deterministic sample derivation used by the hidden/random streams."""
    return (k * 2654435761) & 0xFFFF


def random_stim(cycles: int, seed: int) -> list:
    """Randomized stimulus: resets, enable gaps, legal context switches,
    long suspensions, pending level-2 work, and full-range samples."""
    import random

    rng = random.Random(seed)
    stim = []
    ctx = 0
    pending_switch = False
    with_gaps = seed == PUBLIC_SEED
    for k in range(cycles):
        if with_gaps:
            rst = 1 if k in (0, 1, 250, 251, 777, 1003, 1004) else 0
            if rng.random() < 0.03:
                pending_switch = True
            en = 0 if rng.random() < 0.12 else 1
            if pending_switch and en == 0 and not rst:
                ctx ^= 1
                pending_switch = False
        else:
            rst = 1 if (k == 0 or rng.random() < 0.004) else 0
            if rng.random() < 0.02:
                pending_switch = True
            en = 1 if rng.random() < 0.55 else 0
            if pending_switch and en == 0 and not rst:
                ctx ^= 1
                pending_switch = False
        if rng.random() < 0.5:
            x = x_of(k)
        else:
            x = rng.randrange(1 << 16)
        stim.append((ctx, en, x, rst))
    stim.append((0, 0, 0, 1))
    stim.append((1, 0, 0, 0))
    return stim


def directed_stim() -> list:
    """Directed corners per spec Section 6 Gate 3."""
    s = []
    s += [(0, 0, 0, 1), (0, 0, 0, 0)]
    # A impulse response (two-sample impulse to exercise tap 0 and tail)
    s += [(0, 1, 1, 0), (0, 1, 1, 0)] + [(0, 1, 0, 0)] * 6
    # B impulse with level-2 fill, steady cadence, and drain
    s += [(1, 0, 0, 0)]
    s += [(1, 1, 1, 0), (1, 1, 0, 0)] + [(1, 1, 0, 0)] * 14
    # alternation with distinct histories: A accumulates, switch to B, back
    s += [(0, 1, 100, 0), (0, 1, 200, 0), (0, 1, 300, 0)]
    s += [(1, 0, 0, 0)]
    s += [(1, 1, 0x7FFF, 0), (1, 1, 0x8000, 0), (1, 1, 0, 0), (1, 1, 0, 0)]
    s += [(0, 0, 0, 0)]
    s += [(0, 1, 0x8000, 0), (0, 1, 1, 0), (0, 1, 0xFFFF, 0), (0, 1, 0, 0)]
    # en=0 at each phase with a pending level-2 job (three B samples then gap)
    s += [(1, 0, 0, 1)]
    s += [(1, 1, 0x1234, 0), (1, 1, 0x2345, 0), (1, 1, 0x3456, 0)]
    s += [(1, 0, 0, 0)] * 5
    s += [(1, 1, 0x4567, 0), (1, 1, 0x5678, 0)]
    # reset at a decimation phase with pending work, then resume
    s += [(1, 1, 0x6789, 0)]
    s += [(1, 0, 0, 1)]
    s += [(1, 1, 0x7FFF, 0), (1, 1, 0x8000, 0)]
    # mutant-4 corner: B window at odd index 3 has bit31 != bit15
    s += [(0, 0, 0, 1)]
    for v in MUTANT_CORNER_B_SAMPLES:
        s.append((1, 1, v & 0xFFFF, 0))
    s += [(1, 1, 0, 0)]
    # extreme wrap stress both contexts, then final reset and idle
    s += [(0, 1, 0x7FFF, 0), (0, 1, 0x7FFF, 0), (0, 1, 0x7FFF, 0)]
    s += [(1, 0, 0, 0)]
    s += [(1, 1, 0x8000, 0)] * 6
    s += [(0, 0, 0, 1), (0, 0, 0, 0)]
    return s


def stim_files(stim, work: Path, tag: str):
    work.mkdir(parents=True, exist_ok=True)
    stim_path = work / f"stim_{tag}.txt"
    rows = []
    for ctx, en, x, rst in stim:
        ctl = (ctx & 1) | ((en & 1) << 1) | ((rst & 1) << 2)
        rows.append(f"{ctl:02x} {(x >> 8) & 0xFF:02x} {x & 0xFF:02x}")
    stim_path.write_text("\n".join(rows) + "\n")
    cap_path = work / f"cap_{tag}.txt"
    return stim_path, cap_path


def parse_capture(text: str) -> list:
    """Parse TB capture lines.

    Each line is nine whitespace-separated fields in this order:
    a_l1_lo(hex) a_l1_hi(hex) a_l1_valid(dec) b_l1_lo(hex) b_l1_hi(hex)
    b_l1_valid(dec) b_l2_lo(hex) b_l2_hi(hex) b_l2_valid(dec).
    """
    out = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 9:
            raise ValueError(f"capture line has {len(parts)} fields: {line!r}")
        out.append((int(parts[0], 16), int(parts[1], 16), int(parts[2]),
                    int(parts[3], 16), int(parts[4], 16), int(parts[5]),
                    int(parts[6], 16), int(parts[7], 16), int(parts[8])))
    return out


def compare(captured, expected):
    """Return (mismatches, first_note) comparing unsigned oracle tuples."""
    mism = 0
    first = ""
    for i, (got, exp) in enumerate(zip(captured, expected)):
        if tuple(got) != tuple(exp):
            mism += 1
            if not first:
                fields = ("a_lo", "a_hi", "a_v", "b_lo", "b_hi", "b_v",
                          "l2_lo", "l2_hi", "l2_v")
                diffs = [f"{fields[j]} {got[j]:x}/{exp[j]:x}"
                         for j in range(9) if got[j] != exp[j]]
                first = f"cyc{i} " + " ".join(diffs)
    return mism, first
