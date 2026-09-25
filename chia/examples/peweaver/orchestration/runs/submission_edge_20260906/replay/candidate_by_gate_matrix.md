# Evaluator Replay Matrix (Evidence-Scoped)

Records 31 candidates across 5 explicit strata. Only rows with complete local gate evidence are evaluated; partial or missing evidence is reported as NOT_EVALUATED and excluded from detection denominators:
- **Config 1:** Functional checks only (lint, random oracle, holdouts)
- **Config 2:** Functional + Mapped GLS
- **Config 3:** Full domain-specific gate ladder (FFT physical timing/DRC; MAC formal/structure; FIR structure/generic-cell area; provenance where applicable)

| Candidate ID | Stratum | Domain | Expected | Evidence | Config 1 | Config 2 | Config 3 | Earliest Catch | Primary Artifact Evidence |
|---|---|---|---|---|---|---|---|---|---|
| `nat_ps_turn1` | natural_failure | FFT | FAIL | PARTIAL | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | `evidence` | timing_met=False drc=0 |
| `nat_ps_turn2` | natural_failure | FFT | FAIL | PARTIAL | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | `evidence` | errors=3 burst_len=384 |
| `nat_ps_turn5` | natural_failure | FFT | FAIL | PARTIAL | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | `evidence` | timing_met=False drc=0 |
| `nat_ps_turn6` | natural_failure | FFT | FAIL | PARTIAL | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | `evidence` | assemble_results.py rejected empty reset-recovery reports (r |
| `nat_ps_turn7` | natural_failure | FFT | FAIL | PARTIAL | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | `evidence` | timing_met=False drc=0 |
| `acc_fft_s0` | accepted_legal | FFT | PASS | VERIFIED | ADVANCE | ADVANCE | ADVANCE | `None (Advance)` | Primary mapped-GLS/P&R result and independent repeat are has |
| `acc_fft_s1` | accepted_legal | FFT | PASS | PARTIAL | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | `evidence` | Placed area 282,963 um^2; physical flow passed; DRC 0 |
| `acc_fft_repro1` | accepted_legal | FFT | PASS | UNVERIFIED | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | `evidence` | Accepted turn 10; 32-33% placed area reduction; timing close |
| `acc_fft_repro2` | accepted_legal | FFT | PASS | UNVERIFIED | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | `evidence` | Accepted turn 2; 32-33% placed area reduction; timing closed |
| `acc_fft_repro3` | accepted_legal | FFT | PASS | UNVERIFIED | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | `evidence` | Accepted turn 13; 32-33% placed area reduction; timing close |
| `acc_mac_m2` | accepted_legal | MAC | PASS | VERIFIED | ADVANCE | ADVANCE | ADVANCE | `None (Advance)` | Passed 6/6 gates; generic cell count 531 (-44.0%); BMC depth |
| `acc_mac_m3` | accepted_legal | MAC | PASS | VERIFIED | ADVANCE | ADVANCE | ADVANCE | `None (Advance)` | Passed 6/6 gates; generic cell count 531 (-44.0%); BMC depth |
| `acc_fir_f1` | accepted_legal | FIR | PASS | UNVERIFIED | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | `evidence` | Passed 6/6 gates; 8 mults, 4484 generic cells (-11.6%); impu |
| `legal_mac_commutation` | accepted_legal | MAC | PASS | UNVERIFIED | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | `evidence` | mac-mutants-1: failed_gates=[], caught=False, as_expected=Tr |
| `ctrl_mac_two_mult` | architectural_control | MAC | FAIL | UNVERIFIED | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | `evidence` | Rejected by structure gate: 2 multiplier cells > 1 allowed |
| `ctrl_mac_double_prod` | architectural_control | MAC | FAIL | UNVERIFIED | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | `evidence` | Rejected by functional oracle: arithmetic mismatch on interl |
| `ctrl_fir_16_mult` | architectural_control | FIR | FAIL | UNVERIFIED | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | `evidence` | Rejected by generic area floor: 4.6% cell reduction < 10% re |
| `ctrl_fir_shared_delay` | architectural_control | FIR | FAIL | UNVERIFIED | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | `evidence` | Rejected by functional oracle: filter state contaminated acr |
| `mut_mac_signedness` | rtl_mutation | MAC | FAIL | PARTIAL | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | `evidence` | 1020/1200 mismatches; first: cyc8 got 61c5 exp fac5; cyc9 go |
| `mut_mac_acc_hold_mode1` | rtl_mutation | MAC | FAIL | PARTIAL | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | `evidence` | 425/1200 mismatches; first: cyc298 got 35ad exp 1524; cyc299 |
| `mut_mac_reset_ignored` | rtl_mutation | MAC | FAIL | PARTIAL | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | `evidence` | 407/1200 mismatches; first: cyc405 got 373c exp 0bf4; cyc406 |
| `mut_mac_enable_ignored` | rtl_mutation | MAC | FAIL | PARTIAL | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | `evidence` | 1116/1200 mismatches; first: cyc2 got 031b exp 0000; cyc3 go |
| `mut_mac_output_truncation` | rtl_mutation | MAC | FAIL | PARTIAL | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | `evidence` | 1188/1200 mismatches; first: cyc7 got 01ff exp 1ffe; cyc8 go |
| `mut_fft_twiddle_re` | rtl_mutation | FFT | FAIL | UNVERIFIED | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | `evidence` | Mismatches on non-zero twiddle frames; caught by hidden hold |
| `mut_fft_twiddle_im` | rtl_mutation | FFT | FAIL | UNVERIFIED | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | `evidence` | Mismatches on non-zero twiddle frames; caught by hidden hold |
| `mut_fft_scale_shift` | rtl_mutation | FFT | FAIL | UNVERIFIED | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | `evidence` | Dynamic range gain error; caught by random oracle and holdou |
| `mut_fft_counter_wrap` | rtl_mutation | FFT | FAIL | UNVERIFIED | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | `evidence` | First-valid latency assertion error (got 70, expected 71) |
| `flt_hash_mismatch` | infra_provenance | Cross-domain | FAIL | UNVERIFIED | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | `evidence` | Resume refuses changed inputs/contract (SHA-256 mismatch) |
| `flt_sta_1452` | infra_provenance | FFT | FAIL | UNVERIFIED | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | `evidence` | Halt on STA-1452: clock period mismatch between VCD and SDC |
| `flt_zero_activity` | infra_provenance | FFT | FAIL | UNVERIFIED | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | `evidence` | assemble_results.py die: VCD activity annotation must be non |
| `flt_stale_report` | infra_provenance | FFT | FAIL | UNVERIFIED | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | **NOT_EVALUATED** (evidence) | `evidence` | Driver rmtree(results/) before run; missing fresh artifact h |

## Detection Rate by Stratum

| Stratum | Total | Defects | Evaluated Defects | Unevaluated Defects | Config 1 | Config 2 | Config 3 | Legal | False Rejections |
|---|---|---|---|---|---|---|---|---|---|
| **natural_failure** | 5 | 5 | 0 | 5 | N/A | N/A | N/A | 0 | N/A |
| **accepted_legal** | 9 | 0 | 0 | 0 | N/A | N/A | N/A | 3 | 0/3 |
| **architectural_control** | 4 | 4 | 0 | 4 | N/A | N/A | N/A | 0 | N/A |
| **rtl_mutation** | 9 | 9 | 0 | 9 | N/A | N/A | N/A | 0 | N/A |
| **infra_provenance** | 4 | 4 | 0 | 4 | N/A | N/A | N/A | 0 | N/A |
| **Overall Total** | **31** | **22** | **0** | **22** | **N/A** | **N/A** | **N/A** | **3** | **0/3** |

### Key Findings:
1. **Evidence scope:** 0 defect records and 3 legal records have complete local gate evidence; 22 defect records and 6 legal records remain outside the detection denominators.
2. **Fail-closed behavior:** Any missing, invalid, UNKNOWN, or N/A status in a required gate blocks evaluation rather than advancing the candidate.
3. **No synthetic completeness claim:** Source-code guard descriptions and partial mutation reports remain visible in the ledger but do not count as full nested evaluator executions.
