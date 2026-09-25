"""Independent bit-accurate arithmetic oracle for the FFT128 reference fixture.

Phase 2 deliverable of ``examples/peweaver/PHYSICAL_PPA_PLAN.md``: a
dependency-free Python model that consumes 128-sample Q1.15 input frames and
computes the fixture-compatible 16-bit complex outputs **without consulting
output golden files**. This module performs no file I/O at all; the golden
vectors are used only by the unit tests that verify it.

The arithmetic core is shared with the FFT64 oracle (``fft64_oracle.py``):
identical Butterfly (17-bit add/sub, ``(sum + RH) >>> 1`` floor shift,
``RH=0``/``RH=1`` alternating bias), identical Multiply (per-product
``>>> 15`` floor, then modulo-2^16 sub/add), identical two-state policy.
The FFT128-specific structure below is derived from the pinned upstream
``FFT128.v``/``Twiddle128.v``/``SdfUnit2.v`` (revision
``f7dca6e548e1370b69a09382d30609ee14ba4a57``):

1. **Pipeline**: four stages - ``SdfUnit(N=128, M=128)``, ``SdfUnit(N=128,
   M=32)``, ``SdfUnit(N=128, M=8)`` and ``SdfUnit2`` (the dedicated final
   radix-2 for twiddle resolution M=2). ``SdfUnit`` is the same cycle-accurate
   replica used for FFT64, parameterized over (N, M); with ``M=8`` the
   -j rotation condition reads ``bf1_count[2:1] == 3`` and the twiddle
   addressing is ``tw_num = (bf2_count << 4) & 0x1F``,
   ``tw_sel = 2*bf2_count[1] + bf2_count[2]`` (all literal from the RTL).
2. **SdfUnit2** (final radix-2, no twiddle multiply): a toggle-enable
   butterfly stage - ``bf_en <= di_en ? ~bf_en : 0`` - pairing each new
   sample with the previous one through a depth-1 delay buffer, butterfly
   ``RH=0``, and a two-register output enable (``bf_sp_en <= di_en``;
   ``do_en <= bf_sp_en``).
3. **Twiddle factors**: the exact literal entries of the pinned
   ``Twiddle128.v`` table. 64 of the 128 entries are ``16'hxxxx`` upstream
   and resolve to zero under the fixture's documented two-state policy; the
   R2^2SDF addressing never selects them (asserted by the unit tests).
4. **Reset**: asynchronous active-high for the listed registers, exactly as
   ``SdfUnit2.v``/``SdfUnit.v``; delay buffers have no reset and drain
   while ``di_en`` is low.

Power-on state is all-zero (two-state policy); the transaction helpers
follow the directed regression's convention (async reset, 16 reset cycles,
idle drain, then streaming). Outputs are emitted in the hardware's
bit-reversed order (emission sample k is natural bin ``bitrev7(k)``); the
first ``do_en`` appears after 137 clock edges (upstream header comment,
verified by the directed regression).
"""

from __future__ import annotations

try:
    from .fft64_oracle import (
        _DelayBuffer,
        _SdfUnit,
        _butterfly,
        _complex_multiply,
        _verilog_log2,
        to_signed16,
        to_unsigned16,
    )
except ImportError:  # Direct execution from examples/peweaver.
    from fft64_oracle import (
        _DelayBuffer,
        _SdfUnit,
        _butterfly,
        _complex_multiply,
        _verilog_log2,
        to_signed16,
        to_unsigned16,
    )

__all__ = [
    "DOCUMENTED_LATENCY",
    "FRAME_SAMPLES",
    "Fft128Oracle",
    "bitrev7",
    "natural_order",
    "run_frame",
    "run_frames_streaming",
]

_U16_MASK = 0xFFFF

FRAME_SAMPLES = 128
DOCUMENTED_LATENCY = 137


_TWIDDLE128_TABLE: tuple[tuple[int, int], ...] = (
    (0x0000, 0x0000), (0x7FD9, 0xF9B8), (0x7F62, 0xF374), (0x7E9D, 0xED38),  # 0
    (0x7D8A, 0xE707), (0x7C2A, 0xE0E6), (0x7A7D, 0xDAD8), (0x7885, 0xD4E1),
    (0x7642, 0xCF04), (0x73B6, 0xC946), (0x70E3, 0xC3A9), (0x6DCA, 0xBE32),
    (0x6A6E, 0xB8E3), (0x66D0, 0xB3C0), (0x62F2, 0xAECC), (0x5ED7, 0xAA0A),
    (0x5A82, 0xA57E), (0x55F6, 0xA129), (0x5134, 0x9D0E), (0x4C40, 0x9930),  # 16
    (0x471D, 0x9592), (0x41CE, 0x9236), (0x3C57, 0x8F1D), (0x36BA, 0x8C4A),
    (0x30FC, 0x89BE), (0x2B1F, 0x877B), (0x2528, 0x8583), (0x1F1A, 0x83D6),
    (0x18F9, 0x8276), (0x12C8, 0x8163), (0x0C8C, 0x809E), (0x0648, 0x8027),
    (0x0000, 0x8000), (0xF9B8, 0x8027), (0xF374, 0x809E), (0x0000, 0x0000),  # 32
    (0xE707, 0x8276), (0x0000, 0x0000), (0xDAD8, 0x8583), (0xD4E1, 0x877B),
    (0xCF04, 0x89BE), (0x0000, 0x0000), (0xC3A9, 0x8F1D), (0x0000, 0x0000),
    (0xB8E3, 0x9592), (0xB3C0, 0x9930), (0xAECC, 0x9D0E), (0x0000, 0x0000),
    (0xA57E, 0xA57E), (0x0000, 0x0000), (0x9D0E, 0xAECC), (0x9930, 0xB3C0),  # 48
    (0x9592, 0xB8E3), (0x0000, 0x0000), (0x8F1D, 0xC3A9), (0x0000, 0x0000),
    (0x89BE, 0xCF04), (0x877B, 0xD4E1), (0x8583, 0xDAD8), (0x0000, 0x0000),
    (0x8276, 0xE707), (0x0000, 0x0000), (0x809E, 0xF374), (0x8027, 0xF9B8),
    (0x0000, 0x0000), (0x0000, 0x0000), (0x809E, 0x0C8C), (0x0000, 0x0000),  # 64
    (0x0000, 0x0000), (0x83D6, 0x1F1A), (0x0000, 0x0000), (0x0000, 0x0000),
    (0x89BE, 0x30FC), (0x0000, 0x0000), (0x0000, 0x0000), (0x9236, 0x41CE),
    (0x0000, 0x0000), (0x0000, 0x0000), (0x9D0E, 0x5134), (0x0000, 0x0000),
    (0x0000, 0x0000), (0xAA0A, 0x5ED7), (0x0000, 0x0000), (0x0000, 0x0000),  # 80
    (0xB8E3, 0x6A6E), (0x0000, 0x0000), (0x0000, 0x0000), (0xC946, 0x73B6),
    (0x0000, 0x0000), (0x0000, 0x0000), (0xDAD8, 0x7A7D), (0x0000, 0x0000),
    (0x0000, 0x0000), (0xED38, 0x7E9D), (0x0000, 0x0000), (0x0000, 0x0000),
    (0x0000, 0x0000), (0x0000, 0x0000), (0x0000, 0x0000), (0x0000, 0x0000),  # 96
    (0x0000, 0x0000), (0x0000, 0x0000), (0x0000, 0x0000), (0x0000, 0x0000),
    (0x0000, 0x0000), (0x0000, 0x0000), (0x0000, 0x0000), (0x0000, 0x0000),
    (0x0000, 0x0000), (0x0000, 0x0000), (0x0000, 0x0000), (0x0000, 0x0000),
    (0x0000, 0x0000), (0x0000, 0x0000), (0x0000, 0x0000), (0x0000, 0x0000),  # 112
    (0x0000, 0x0000), (0x0000, 0x0000), (0x0000, 0x0000), (0x0000, 0x0000),
    (0x0000, 0x0000), (0x0000, 0x0000), (0x0000, 0x0000), (0x0000, 0x0000),
    (0x0000, 0x0000), (0x0000, 0x0000), (0x0000, 0x0000), (0x0000, 0x0000),
)

_TWIDDLE128_UNSELECTED = frozenset({
    35, 37, 41, 43, 47, 49, 53, 55, 59, 61, 64, 65, 67, 68, 70, 71, 73, 74,
    76, 77, 79, 80, 82, 83, 85, 86, 88, 89, 91, 92, 94, 95, 96, 97, 98, 99,
    100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 113,
    114, 115, 116, 117, 118, 119, 120, 121, 122, 123, 124, 125, 126, 127,
})


class _SdfUnit2:
    """Cycle-accurate replica of SdfUnit2.v: the final radix-2 stage (M=2).

    A toggle-enable butterfly over a depth-1 delay buffer, no twiddle
    multiply, and a two-register output enable. All updates read pre-edge
    state; ``bf_en``/``bf_sp_en``/``do_en`` have the asynchronous active-high
    reset; ``do_re``/``do_im`` and the delay buffer update on every posedge.
    """

    def __init__(self):
        # asynchronously reset registers
        self.bf_en = 0
        self.bf_sp_en = 0
        self.do_en = 0
        # power-on zero registers without reset
        self.do_re = 0
        self.do_im = 0
        self._db = _DelayBuffer(1)

    def reset(self) -> None:
        self.bf_en = 0
        self.bf_sp_en = 0
        self.do_en = 0

    def output_registers(self) -> tuple[int, int, int]:
        return self.do_en, self.do_re, self.do_im

    def step(self, di_en: int, di_re: int, di_im: int, reset: bool = False) -> None:
        di_re &= _U16_MASK
        di_im &= _U16_MASK

        # ---- combinational logic from pre-edge state ----
        db_out = self._db.out
        y0_re, y0_im, y1_re, y1_im = _butterfly(db_out[0], db_out[1], di_re, di_im, rh=0)
        db_in = (y1_re, y1_im) if self.bf_en else (di_re, di_im)
        bf_sp = (y0_re, y0_im) if self.bf_en else db_out

        # ---- next-state values ----
        next_bf_en = (1 - self.bf_en) if di_en else 0
        next_bf_sp_en = 1 if di_en else 0
        next_do_en = self.bf_sp_en

        # ---- commit ----
        self._db.shift(*db_in)
        self.do_re, self.do_im = bf_sp
        if reset:
            self.reset()
        else:
            self.bf_en = next_bf_en
            self.bf_sp_en = next_bf_sp_en
            self.do_en = next_do_en


class Fft128Oracle:
    """Cycle-accurate FFT128 oracle (three SdfUnits + SdfUnit2, as in FFT128.v).

    ``step()`` advances one clock edge and returns the post-edge registered
    outputs ``(do_en, do_re, do_im)``. With the regression's convention
    (sample k presented for edge k+1, i.e. ``di_en`` high for exactly 128
    consecutive edges starting at edge 1), the first ``do_en`` is returned
    after edge 137 and exactly 128 consecutive output samples follow.
    """

    def __init__(self):
        self._su1 = _SdfUnit(128, 128, _TWIDDLE128_TABLE)
        self._su2 = _SdfUnit(128, 32, _TWIDDLE128_TABLE)
        self._su3 = _SdfUnit(128, 8, _TWIDDLE128_TABLE)
        self._su4 = _SdfUnit2()
        self.cycles = 0

    def reset(self) -> None:
        self._su1.reset()
        self._su2.reset()
        self._su3.reset()
        self._su4.reset()

    def step(self, di_en: int, di_re: int, di_im: int, reset: bool = False) -> tuple[int, int, int]:
        # Inter-stage wiring reads pre-edge register values, so capture the
        # upstream outputs before that stage commits this edge.
        su1_out = self._su1.output_registers()
        su2_out = self._su2.output_registers()
        su3_out = self._su3.output_registers()
        self._su1.step(di_en, di_re, di_im, reset)
        self._su2.step(*su1_out, reset)
        self._su3.step(*su2_out, reset)
        self._su4.step(*su3_out, reset)
        self.cycles += 1
        return self._su4.output_registers()

    def twiddle_addresses(self) -> set[int]:
        """Every twiddle ROM address the run has presented to the tables."""
        return self._su1.twiddle_addresses | self._su2.twiddle_addresses \
            | self._su3.twiddle_addresses


def _standard_prologue(oracle: Fft128Oracle, reset_cycles: int, drain_cycles: int) -> None:
    oracle.reset()
    for _ in range(reset_cycles):
        oracle.step(0, 0, 0, reset=True)
    for _ in range(drain_cycles):
        oracle.step(0, 0, 0)


def _collect_frame(oracle: Fft128Oracle) -> list[tuple[int, int]]:
    """Collect the 128 output samples of the frame now in flight (fail-closed)."""
    outputs: list[tuple[int, int]] = []
    for _ in range(FRAME_SAMPLES + DOCUMENTED_LATENCY + 64):
        do_en, do_re, do_im = oracle.step(0, 0, 0)
        if do_en:
            if len(outputs) == FRAME_SAMPLES:
                raise ValueError("oracle emitted more than 128 output-valid samples")
            outputs.append((do_re, do_im))
        elif len(outputs) == FRAME_SAMPLES:
            break
    if len(outputs) != FRAME_SAMPLES:
        raise ValueError(f"oracle captured {len(outputs)} of {FRAME_SAMPLES} output samples")
    for _ in range(8):
        if oracle.step(0, 0, 0)[0]:
            raise ValueError("unexpected output-valid cycle after the frame")
    return outputs


def run_frame(samples, *, reset_cycles: int = 16, drain_cycles: int = 256) -> list[tuple[int, int]]:
    """Run one reset-separated transaction and return the emitted outputs.

    ``samples`` is the 128-sample frame as ``(re, im)`` raw 16-bit words in
    natural order. The returned 128 outputs are in the hardware's emission
    order: ``outputs[k]`` is natural bin ``bitrev7(k)``; use
    ``natural_order()`` for natural bin order. Reset and drain follow the
    directed regression's convention (drain exceeds the deepest 64-deep
    delay buffer).
    """
    if len(samples) != FRAME_SAMPLES:
        raise ValueError(f"expected {FRAME_SAMPLES} samples, got {len(samples)}")
    oracle = Fft128Oracle()
    _standard_prologue(oracle, reset_cycles, drain_cycles)
    for re_, im in samples:
        oracle.step(1, re_, im)
    return _collect_frame(oracle)


def run_frames_streaming(frames, *, reset_cycles: int = 16,
                         drain_cycles: int = 256) -> list[list[tuple[int, int]]]:
    """Run consecutive frames in one continuous stream (upstream usage).

    All frames share one oracle instance; the first frame gets the standard
    reset/drain prologue, later frames start after the 8 idle cycles the
    regression leaves between frames. Frames must not overlap outputs.
    """
    for frame in frames:
        if len(frame) != FRAME_SAMPLES:
            raise ValueError(f"expected {FRAME_SAMPLES} samples per frame, got {len(frame)}")
    oracle = Fft128Oracle()
    _standard_prologue(oracle, reset_cycles, drain_cycles)
    results: list[list[tuple[int, int]]] = []
    for frame in frames:
        for re_, im in frame:
            oracle.step(1, re_, im)
        results.append(_collect_frame(oracle))
    return results


def natural_order(emission: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Reorder emitted samples into natural bin order: bin n at index n."""
    if len(emission) != FRAME_SAMPLES:
        raise ValueError(f"expected {FRAME_SAMPLES} emitted samples, got {len(emission)}")
    natural = [None] * FRAME_SAMPLES
    for emitted_index, sample in enumerate(emission):
        natural[bitrev7(emitted_index)] = sample
    return natural


def bitrev7(value: int) -> int:
    """7-bit bit reversal used by the fixture's output-order mapping."""
    if not 0 <= value < FRAME_SAMPLES:
        raise ValueError(f"bitrev7 expects 0..127, got {value}")
    reversed_value = 0
    for bit in range(7):
        if (value >> bit) & 1:
            reversed_value |= 1 << (6 - bit)
    return reversed_value
