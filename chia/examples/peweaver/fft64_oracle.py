"""Independent bit-accurate arithmetic oracle for the FFT64 reference fixture.

Phase 1 deliverable of ``examples/peweaver/PHYSICAL_PPA_PLAN.md``: a
dependency-free Python model that consumes 64-sample Q1.15 input frames and
computes the fixture-compatible 16-bit complex outputs **without consulting
output golden files**.  This module performs no file I/O at all; the golden
vectors are used only by the unit tests that verify it.

All arithmetic and control rules below are derived from the pinned curated
``r22sdf`` RTL (upstream revision ``f7dca6e548e1370b69a09382d30609ee14ba4a57``,
see ``third_party/r22sdf/README.md``).  No upstream file was modified, and no
floating-point FFT is involved anywhere: the model is a cycle-accurate
fixed-point replica of the hardware dataflow.

Derived fixed-point semantics (all stored words are unsigned 16-bit; the
signed Q1.15 interpretation of a raw word ``w`` is ``w - 65536`` when
``w >= 32768``):

1. **Butterfly** (``Butterfly.v``, ``WIDTH=16``): exact signed add/sub
   evaluated into 17 bits, then ``(sum + RH) >>> 1``.  The arithmetic right
   shift floors toward negative infinity.  ``BF1`` uses ``RH=0`` (plain
   floor) and ``BF2`` uses ``RH=1`` (round half up), which is the
   alternating-bias scheme documented in ``SdfUnit.v``.  For 16-bit signed
   inputs ``floor((x0 +/- x1 + RH) / 2)`` always fits in signed 16 bits, so
   the shift path never wraps.
2. **Complex multiply** (``Multiply.v``): exact 16x16 signed products; each
   product is scaled by ``>>> 15`` with **no rounding bias** (floor), and the
   scaled products are then combined with **modulo-2^16** subtraction and
   addition on 16-bit wires:
   ``m_re = (sra(a_re*b_re, 15) - sra(a_im*b_im, 15)) mod 2^16`` and
   ``m_im = (sra(a_re*b_im, 15) + sra(a_im*b_re, 15)) mod 2^16``.
   (Truncating each scaled product to 16 bits before the add/sub is
   mathematically absorbed by the final mod-2^16 result.)
3. **Multiplication by -j** (``SdfUnit.v`` ``bf1_mj`` path):
   ``(re, im) -> (im, (-re) mod 2^16)``.
4. **Twiddle factors**: the exact literal Q1.15 entries of the pinned
   ``Twiddle64.v`` table (``wn[n] = cos/sin(-2*pi*n/64)`` rounded by upstream,
   not re-derived here).  Entries the upstream source fills with ``1'bx``
   resolve to zero under the fixture's documented two-state simulation policy
   (``--x-assign 0 --x-initial 0``); the R2^2SDF addressing never selects any
   of them, which the unit tests assert directly.
5. **Control/dataflow**: a cycle-accurate replica of the three cascaded
   ``SdfUnit`` instances of ``FFT64.v`` (``N=64``; ``M=64, 16, 4``): the
   input counter, the two radix-2 butterflies with delay-line depths
   ``2^(LOG_M-1)`` and ``2^(LOG_M-2)``, the registered twiddle ROM read, the
   registered multiplier-bypass enable (bypass when twiddle address is 0),
   and the registered output pipeline.  The model therefore reproduces the
   hardware's 71-cycle output latency and emits outputs in the hardware's
   bit-reversed order.

Power-on state is all-zero, matching the two-state policy above; the
transaction helpers additionally follow the directed regression's reset
convention (asynchronous active-high reset, idle drain before streaming).
"""

from __future__ import annotations

__all__ = [
    "DOCUMENTED_LATENCY",
    "FRAME_SAMPLES",
    "Fft64Oracle",
    "bitrev6",
    "natural_order",
    "run_frame",
    "run_frames_streaming",
    "to_signed16",
    "to_unsigned16",
]

FRAME_SAMPLES = 64
DOCUMENTED_LATENCY = 71

_U16_MASK = 0xFFFF


def to_signed16(value: int) -> int:
    """Signed Q1.15 interpretation of a raw 16-bit word."""
    value &= _U16_MASK
    return value - 0x10000 if value & 0x8000 else value


def to_unsigned16(value: int) -> int:
    """Raw 16-bit word of a signed value (modulo wrap, as the RTL wires do)."""
    return value & _U16_MASK


def bitrev6(value: int) -> int:
    """6-bit bit reversal used by the fixture's output-order mapping."""
    if not 0 <= value < FRAME_SAMPLES:
        raise ValueError(f"bitrev6 expects 0..63, got {value}")
    reversed_value = 0
    for bit in range(6):
        if (value >> bit) & 1:
            reversed_value |= 1 << (5 - bit)
    return reversed_value


def _butterfly(x0_re: int, x0_im: int, x1_re: int, x1_im: int, rh: int) -> tuple[int, int, int, int]:
    """Butterfly.v with WIDTH=16: (sum +/- with RH bias) >>> 1, floor shift."""
    x0r, x0i, x1r, x1i = (to_signed16(v) for v in (x0_re, x0_im, x1_re, x1_im))
    y0_re = (x0r + x1r + rh) >> 1
    y0_im = (x0i + x1i + rh) >> 1
    y1_re = (x0r - x1r + rh) >> 1
    y1_im = (x0i - x1i + rh) >> 1
    return (to_unsigned16(y0_re), to_unsigned16(y0_im),
            to_unsigned16(y1_re), to_unsigned16(y1_im))


def _complex_multiply(a_re: int, a_im: int, b_re: int, b_im: int) -> tuple[int, int]:
    """Multiply.v: per-product >>>15 (floor, unbiased), then mod-2^16 sub/add."""
    ar, ai, br, bi = (to_signed16(v) for v in (a_re, a_im, b_re, b_im))
    sc_arbr = (ar * br) >> 15
    sc_arbi = (ar * bi) >> 15
    sc_aibr = (ai * br) >> 15
    sc_aibi = (ai * bi) >> 15
    m_re = (sc_arbr - sc_aibi) & _U16_MASK
    m_im = (sc_arbi + sc_aibr) & _U16_MASK
    return m_re, m_im


def _verilog_log2(points: int) -> int:
    """The ``log2`` function literal from SdfUnit.v."""
    value = points - 1
    result = 0
    while value > 0:
        result += 1
        value >>= 1
    return result


# Exact Twiddle64.v entries (re, im) as raw 16-bit words, in address order.
# Addresses listed in _TWIDDLE_UNSELECTED hold 16'hxxxx upstream; under the
# fixture's two-state policy they resolve to zero, and the R2^2SDF addressing
# never selects them (asserted by the unit tests).
_TWIDDLE_UNSELECTED = frozenset({
    17, 19, 23, 25, 29, 31, 32, 34, 35, 37, 38, 40, 41, 43, 44, 46, 47,
    48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63,
})
_TWIDDLE_TABLE: tuple[tuple[int, int], ...] = (
    (0x0000, 0x0000),  #  0  1.000 -0.000 (bypassed: address 0)
    (0x7F62, 0xF374),  #  1  0.995 -0.098
    (0x7D8A, 0xE707),  #  2  0.981 -0.195
    (0x7A7D, 0xDAD8),  #  3  0.957 -0.290
    (0x7642, 0xCF04),  #  4  0.924 -0.383
    (0x70E3, 0xC3A9),  #  5  0.882 -0.471
    (0x6A6E, 0xB8E3),  #  6  0.831 -0.556
    (0x62F2, 0xAECC),  #  7  0.773 -0.634
    (0x5A82, 0xA57E),  #  8  0.707 -0.707
    (0x5134, 0x9D0E),  #  9  0.634 -0.773
    (0x471D, 0x9592),  # 10  0.556 -0.831
    (0x3C57, 0x8F1D),  # 11  0.471 -0.882
    (0x30FC, 0x89BE),  # 12  0.383 -0.924
    (0x2528, 0x8583),  # 13  0.290 -0.957
    (0x18F9, 0x8276),  # 14  0.195 -0.981
    (0x0C8C, 0x809E),  # 15  0.098 -0.995
    (0x0000, 0x8000),  # 16  0.000 -1.000 (the -j twiddle)
    (0x0000, 0x0000),  # 17  xxxx (two-state zero; never selected)
    (0xE707, 0x8276),  # 18 -0.195 -0.981
    (0x0000, 0x0000),  # 19  xxxx
    (0xCF04, 0x89BE),  # 20 -0.383 -0.924
    (0xC3A9, 0x8F1D),  # 21 -0.471 -0.882
    (0xB8E3, 0x9592),  # 22 -0.556 -0.831
    (0x0000, 0x0000),  # 23  xxxx
    (0xA57E, 0xA57E),  # 24 -0.707 -0.707
    (0x0000, 0x0000),  # 25  xxxx
    (0x9592, 0xB8E3),  # 26 -0.831 -0.556
    (0x8F1D, 0xC3A9),  # 27 -0.882 -0.471
    (0x89BE, 0xCF04),  # 28 -0.924 -0.383
    (0x0000, 0x0000),  # 29  xxxx
    (0x8276, 0xE707),  # 30 -0.981 -0.195
    (0x0000, 0x0000),  # 31  xxxx
    (0x0000, 0x0000),  # 32  xxxx
    (0x809E, 0x0C8C),  # 33 -0.995  0.098
    (0x0000, 0x0000),  # 34  xxxx
    (0x0000, 0x0000),  # 35  xxxx
    (0x89BE, 0x30FC),  # 36 -0.924  0.383
    (0x0000, 0x0000),  # 37  xxxx
    (0x0000, 0x0000),  # 38  xxxx
    (0x9D0E, 0x5134),  # 39 -0.773  0.634
    (0x0000, 0x0000),  # 40  xxxx
    (0x0000, 0x0000),  # 41  xxxx
    (0xB8E3, 0x6A6E),  # 42 -0.556  0.831
    (0x0000, 0x0000),  # 43  xxxx
    (0x0000, 0x0000),  # 44  xxxx
    (0xDAD8, 0x7A7D),  # 45 -0.290  0.957
    (0x0000, 0x0000),  # 46  xxxx
    (0x0000, 0x0000),  # 47  xxxx
    (0x0000, 0x0000),  # 48  xxxx
    (0x0000, 0x0000),  # 49  xxxx
    (0x0000, 0x0000),  # 50  xxxx
    (0x0000, 0x0000),  # 51  xxxx
    (0x0000, 0x0000),  # 52  xxxx
    (0x0000, 0x0000),  # 53  xxxx
    (0x0000, 0x0000),  # 54  xxxx
    (0x0000, 0x0000),  # 55  xxxx
    (0x0000, 0x0000),  # 56  xxxx
    (0x0000, 0x0000),  # 57  xxxx
    (0x0000, 0x0000),  # 58  xxxx
    (0x0000, 0x0000),  # 59  xxxx
    (0x0000, 0x0000),  # 60  xxxx
    (0x0000, 0x0000),  # 61  xxxx
    (0x0000, 0x0000),  # 62  xxxx
    (0x0000, 0x0000),  # 63  xxxx
)


class _DelayBuffer:
    """DelayBuffer.v: plain shift register of the given depth, no reset."""

    __slots__ = ("_depth", "_re", "_im")

    def __init__(self, depth: int):
        self._depth = depth
        self._re = [0] * depth
        self._im = [0] * depth

    @property
    def out(self) -> tuple[int, int]:
        return self._re[-1], self._im[-1]

    def shift(self, re: int, im: int) -> None:
        if self._depth == 1:
            self._re[0] = re
            self._im[0] = im
            return
        for index in range(self._depth - 1, 0, -1):
            self._re[index] = self._re[index - 1]
            self._im[index] = self._im[index - 1]
        self._re[0] = re
        self._im[0] = im


class _SdfUnit:
    """Cycle-accurate replica of SdfUnit.v for the pinned 16-bit FFT64.

    Register updates follow the RTL exactly: asynchronous-active-high reset
    for the listed registers, plain posedge updates for the rest, and all
    updates read pre-edge (nonblocking-assignment) state.
    """

    def __init__(self, points: int, twiddle_resolution: int,
                 twiddle_table: tuple = _TWIDDLE_TABLE):
        self._log_n = _verilog_log2(points)
        self._log_m = _verilog_log2(twiddle_resolution)
        if self._log_n < 3 or self._log_m < 2 or self._log_m > self._log_n:
            raise ValueError("unsupported SdfUnit parameters")
        self._n_mask = (1 << self._log_n) - 1
        self._has_multiply = self._log_m > 2
        self._twiddle_table = twiddle_table
        self._db1 = _DelayBuffer(1 << (self._log_m - 1))
        self._db2 = _DelayBuffer(1 << (self._log_m - 2))
        # Asynchronously reset registers.
        self.di_count = 0
        self.bf1_sp_en = 0
        self.bf1_count = 0
        self.bf2_sp_en = 0
        self.bf2_count = 0
        self.bf2_do_en = 0
        self.mu_do_en = 0
        # Power-on zero registers without reset (two-state policy).
        self.bf1_do_re = 0
        self.bf1_do_im = 0
        self.bf2_bf = 0
        self.bf2_start = 0
        self.bf2_do_re = 0
        self.bf2_do_im = 0
        self.tw_ff_re = 0
        self.tw_ff_im = 0
        self.mu_en = 0
        self.mu_do_re = 0
        self.mu_do_im = 0
        self.twiddle_addresses: set[int] = set()

    def reset(self) -> None:
        """Asynchronous reset assertion: listed registers clear immediately."""
        self.di_count = 0
        self.bf1_sp_en = 0
        self.bf1_count = 0
        self.bf2_sp_en = 0
        self.bf2_count = 0
        self.bf2_do_en = 0
        self.mu_do_en = 0

    def output_registers(self) -> tuple[int, int, int]:
        """Current (pre-edge) registered outputs, as the next stage sees them."""
        if self._has_multiply:
            return self.mu_do_en, self.mu_do_re, self.mu_do_im
        return self.bf2_do_en, self.bf2_do_re, self.bf2_do_im

    def step(self, di_en: int, di_re: int, di_im: int, reset: bool = False) -> None:
        """Advance one posedge using the input presented at that edge."""
        di_re &= _U16_MASK
        di_im &= _U16_MASK
        log_n, log_m = self._log_n, self._log_m

        # ---- combinational logic from pre-edge state ----
        bf1_bf = (self.di_count >> (log_m - 1)) & 1
        db1_out = self._db1.out
        bf1_y0_re, bf1_y0_im, bf1_y1_re, bf1_y1_im = _butterfly(
            db1_out[0], db1_out[1], di_re, di_im, rh=0)
        db1_in = (bf1_y1_re, bf1_y1_im) if bf1_bf else (di_re, di_im)
        bf1_mj = ((self.bf1_count >> (log_m - 2)) & 3) == 3
        if bf1_bf:
            bf1_sp = (bf1_y0_re, bf1_y0_im)
        elif bf1_mj:
            bf1_sp = (db1_out[1], to_unsigned16(-to_signed16(db1_out[0])))
        else:
            bf1_sp = db1_out
        bf1_start = self.di_count == (1 << (log_m - 1)) - 1
        bf1_end = self.bf1_count == self._n_mask

        bf2_bf_next = (self.bf1_count >> (log_m - 2)) & 1
        db2_out = self._db2.out
        bf2_y0_re, bf2_y0_im, bf2_y1_re, bf2_y1_im = _butterfly(
            db2_out[0], db2_out[1], self.bf1_do_re, self.bf1_do_im, rh=1)
        db2_in = (bf2_y1_re, bf2_y1_im) if self.bf2_bf else (self.bf1_do_re, self.bf1_do_im)
        bf2_sp = (bf2_y0_re, bf2_y0_im) if self.bf2_bf else db2_out
        bf2_end = self.bf2_count == self._n_mask

        bf2_start_next = 1 if (self.bf1_count == (1 << (log_m - 2)) - 1
                               and self.bf1_sp_en) else 0

        if self._has_multiply:
            tw_sel = (((self.bf2_count >> (log_m - 2)) & 1) << 1) \
                | ((self.bf2_count >> (log_m - 1)) & 1)
            tw_num = (self.bf2_count << (log_n - log_m)) & ((1 << (log_n - 2)) - 1)
            tw_addr = (tw_num * tw_sel) & self._n_mask
            self.twiddle_addresses.add(tw_addr)
            mu_product = _complex_multiply(self.bf2_do_re, self.bf2_do_im,
                                           self.tw_ff_re, self.tw_ff_im)
            mu_en_next = 1 if tw_addr != 0 else 0
            mu_do_next = mu_product if self.mu_en else (self.bf2_do_re, self.bf2_do_im)
            tw_ff_next = self._twiddle_table[tw_addr]

        # ---- next-state values (all read pre-edge registers) ----
        next_di_count = (self.di_count + 1) & self._n_mask if di_en else 0
        next_bf1_sp_en = 1 if bf1_start else (0 if bf1_end else self.bf1_sp_en)
        next_bf1_count = (self.bf1_count + 1) & self._n_mask if self.bf1_sp_en else 0
        next_bf2_sp_en = 1 if self.bf2_start else (0 if bf2_end else self.bf2_sp_en)
        next_bf2_count = (self.bf2_count + 1) & self._n_mask if self.bf2_sp_en else 0
        next_bf2_do_en = self.bf2_sp_en
        if self._has_multiply:
            next_mu_do_en = self.bf2_do_en

        # ---- commit ----
        self._db1.shift(*db1_in)
        self._db2.shift(*db2_in)
        self.bf1_do_re, self.bf1_do_im = bf1_sp
        self.bf2_bf = bf2_bf_next
        self.bf2_start = bf2_start_next
        self.bf2_do_re, self.bf2_do_im = bf2_sp
        if self._has_multiply:
            self.tw_ff_re, self.tw_ff_im = tw_ff_next
            self.mu_en = mu_en_next
            self.mu_do_re, self.mu_do_im = mu_do_next
        if reset:
            self.reset()
        else:
            self.di_count = next_di_count
            self.bf1_sp_en = next_bf1_sp_en
            self.bf1_count = next_bf1_count
            self.bf2_sp_en = next_bf2_sp_en
            self.bf2_count = next_bf2_count
            self.bf2_do_en = next_bf2_do_en
            if self._has_multiply:
                self.mu_do_en = next_mu_do_en


class Fft64Oracle:
    """Cycle-accurate FFT64 oracle (three cascaded SdfUnits, as in FFT64.v).

    ``step()`` advances one clock edge and returns the post-edge registered
    outputs ``(do_en, do_re, do_im)``.  With the regression's convention
    (sample k presented for edge k+1, i.e. ``di_en`` high for exactly 64
    consecutive edges starting at edge 1), the first ``do_en`` is returned
    after edge 71 and exactly 64 consecutive output samples follow.
    """

    def __init__(self):
        self._su1 = _SdfUnit(64, 64)
        self._su2 = _SdfUnit(64, 16)
        self._su3 = _SdfUnit(64, 4)
        self.cycles = 0

    def reset(self) -> None:
        """Assert the asynchronous active-high reset (immediate)."""
        self._su1.reset()
        self._su2.reset()
        self._su3.reset()

    def step(self, di_en: int, di_re: int, di_im: int, reset: bool = False) -> tuple[int, int, int]:
        # Inter-stage wiring reads pre-edge register values, so capture the
        # upstream outputs before that stage commits this edge.
        su1_out = self._su1.output_registers()
        su2_out = self._su2.output_registers()
        self._su1.step(di_en, di_re, di_im, reset)
        self._su2.step(*su1_out, reset)
        self._su3.step(*su2_out, reset)
        self.cycles += 1
        return self._su3.output_registers()

    def twiddle_addresses(self) -> set[int]:
        """Every twiddle ROM address the run has presented to the table."""
        return self._su1.twiddle_addresses | self._su2.twiddle_addresses


def _standard_prologue(oracle: Fft64Oracle, reset_cycles: int, drain_cycles: int) -> None:
    oracle.reset()
    for _ in range(reset_cycles):
        oracle.step(0, 0, 0, reset=True)
    for _ in range(drain_cycles):
        oracle.step(0, 0, 0)


def _collect_frame(oracle: Fft64Oracle) -> list[tuple[int, int]]:
    """Collect the 64 output samples of the frame now in flight (fail-closed)."""
    outputs: list[tuple[int, int]] = []
    for _ in range(FRAME_SAMPLES + DOCUMENTED_LATENCY + 32):
        do_en, do_re, do_im = oracle.step(0, 0, 0)
        if do_en:
            if len(outputs) == FRAME_SAMPLES:
                raise ValueError("oracle emitted more than 64 output-valid samples")
            outputs.append((do_re, do_im))
        elif len(outputs) == FRAME_SAMPLES:
            break
    if len(outputs) != FRAME_SAMPLES:
        raise ValueError(f"oracle captured {len(outputs)} of {FRAME_SAMPLES} output samples")
    for _ in range(8):
        if oracle.step(0, 0, 0)[0]:
            raise ValueError("unexpected output-valid cycle after the frame")
    return outputs


def run_frame(samples, *, reset_cycles: int = 16, drain_cycles: int = 96) -> list[tuple[int, int]]:
    """Run one reset-separated transaction and return the emitted outputs.

    ``samples`` is the 64-sample frame as ``(re, im)`` raw 16-bit words in
    natural order.  The returned 64 outputs are in the hardware's emission
    order: ``outputs[k]`` is natural bin ``bitrev6(k)``; use
    ``natural_order()`` for natural bin order.  Reset and drain follow the
    directed regression's convention.
    """
    if len(samples) != FRAME_SAMPLES:
        raise ValueError(f"expected {FRAME_SAMPLES} samples, got {len(samples)}")
    oracle = Fft64Oracle()
    _standard_prologue(oracle, reset_cycles, drain_cycles)
    for re, im in samples:
        oracle.step(1, re, im)
    return _collect_frame(oracle)


def run_frames_streaming(frames, *, reset_cycles: int = 16, drain_cycles: int = 96) -> list[list[tuple[int, int]]]:
    """Run back-to-back frames without reset between them (upstream usage).

    All frames share one oracle instance; the first frame gets the standard
    reset/drain prologue, later frames start after the 8 idle cycles the
    regression leaves between frames.  Frames must not overlap outputs.
    """
    for frame in frames:
        if len(frame) != FRAME_SAMPLES:
            raise ValueError(f"expected {FRAME_SAMPLES} samples per frame, got {len(frame)}")
    oracle = Fft64Oracle()
    _standard_prologue(oracle, reset_cycles, drain_cycles)
    results: list[list[tuple[int, int]]] = []
    for frame in frames:
        for re, im in frame:
            oracle.step(1, re, im)
        results.append(_collect_frame(oracle))
    return results


def natural_order(emission: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Reorder emitted samples into natural bin order: bin n at index n."""
    if len(emission) != FRAME_SAMPLES:
        raise ValueError(f"expected {FRAME_SAMPLES} emitted samples, got {len(emission)}")
    natural = [None] * FRAME_SAMPLES
    for emitted_index, sample in enumerate(emission):
        natural[bitrev6(emitted_index)] = sample
    return natural
