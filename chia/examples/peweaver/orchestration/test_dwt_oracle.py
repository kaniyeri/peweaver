"""Fast model-free tests for the DWT benchmark oracle (no tools required)."""

import dwt_oracle as O


def test_coefficient_symmetry_qmf():
    assert O.COEF_G == tuple(
        (-1) ** n * O.COEF_H[3 - n] for n in range(4))


def test_q16_is_signed_bit_slice():
    for value in (0x0, 0xFFFB9F19A7, 0x0000000001, 0xFFFFFFFFFF,
                  0x0000400000, 0x7FFFFFFFFF):
        u = value & (O.MOD - 1)
        expected = (u >> 15) & 0xFFFF
        expected = expected - 65536 if expected >= 32768 else expected
        assert O.q16(value) == expected


def test_dot40_wraps_modulo():
    window = [0x7FFF, 0x7FFF, 0x8000, 0x8000]
    lo = O.dot40(window, O.COEF_H)
    hi = O.dot40(window, O.COEF_G)
    assert 0 <= lo < O.MOD and 0 <= hi < O.MOD
    raw = sum(O.COEF_H[i] * O.s16(window[i]) for i in range(4))
    assert lo == raw % O.MOD


def test_mutant_corner_forces_differing_slices():
    window = [0] * 4
    low = None
    for sample in O.MUTANT_CORNER_B_SAMPLES:
        window = [O.s16(sample)] + window[:3]
    low = O.dot40(window, O.COEF_H)
    assert ((low >> 31) & 1) != ((low >> 15) & 1)
    assert O.q16(low) != ((low >> 16 & 0xFFFF) - 65536
                          if (low >> 16) & 0xFFFF >= 32768
                          else (low >> 16) & 0xFFFF)


def test_directed_stream_first_level2_cycle():
    stim = O.directed_stim()
    out = O.oracle_stream(stim)
    b_samples = 0
    first_l2 = None
    for i, (ctx, en, x, rst) in enumerate(stim):
        if rst:
            b_samples = 0
        elif en and ctx == 1:
            b_samples += 1
            if out[i][8]:
                first_l2 = b_samples
                break
    assert first_l2 == 5  # accepted-sample index 4 is the 5th B sample
    assert out[i][6] != 0 and out[i][7] != 0


def test_stimulus_files_round_trip(tmp_path):
    stim = [(0, 1, 0x1234, 0), (1, 0, 0xABCD, 1)]
    sp, cp = O.stim_files(stim, tmp_path, "t")
    lines = sp.read_text().strip().splitlines()
    assert len(lines) == 2
    ctl, hi, lo = (int(v, 16) for v in lines[0].split())
    assert ctl & 1 == 0 and (ctl >> 1) & 1 == 1
    assert ((hi << 8) | lo) & 0xFFFF == 0x1234
    assert str(cp).endswith("cap_t.txt")
