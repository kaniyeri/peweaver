# ccusage per-task cost probe (2026-09-25)

The existing PEWeaver VM was started for this read-only probe and stopped
afterward. Cached `ccusage` 20.0.21 was run with `session --json --offline`.
Its 958 OpenCode session IDs were joined to the read-only OpenCode SQLite
`session` table by ID. All 958 joined. Each session was assigned to the first
directory component after `/work/peweaver/runs/`; sessions outside that tree
were kept separate. No model calls were launched by the probe.

## Named paper campaigns

| Run | ccusage sessions | Estimated USD |
|---|---:|---:|
| `merge-clean-1` | 75 | 5.034178 |
| `merge-repro-1` | 21 | 3.759528 |
| `merge-repro-2` | 4 | 0.850796 |
| `merge-repro-3` | 27 | 5.657571 |
| `ps-fft-6` | 11 | 2.676040 |
| `mac-merge-1` | 1 | 0.034201 |
| `mac-merge-2` | 3 | 0.100633 |
| `mac-merge-3` | 3 | 0.106213 |
| `fir-merge-1` | 1 | 0.043599 |
| `dwt-merge-1` | 3 | 0.393221 |
| **Subtotal** | **149** | **18.655980** |

The paper groups the three FFT reproductions ($10.267896), three MAC runs
($0.241047), and the other named tasks. Totals are computed before rounding.

## Reconciliation to the VM-wide ccusage estimate

| Directory group | Sessions | Estimated USD |
|---|---:|---:|
| Named paper campaigns above | 149 | 18.655980 |
| Model sweeps (`msweep*`) | 641 | 75.165706 |
| Earlier FFT power pilots (`ps-fft-1` to `ps-fft-5`) | 31 | 6.997654 |
| Other PEWeaver run directories | 62 | 2.640979 |
| Outside `/work/peweaver/runs/` | 75 | 2.767257 |
| **All OpenCode sessions** | **958** | **106.227576** |

The earlier `usage_per_call.csv` export covers a subset of these model calls.
Its $24.89 is **not additive** to the $106.23 ccusage estimate.

## Coworker cost dataset

[`ccusage_per_task_and_experiment_20260925.csv`](ccusage_per_task_and_experiment_20260925.csv)
contains the full directory attribution from this probe: 113 named PEWeaver
run directories plus one pooled bucket outside the runs tree. Filter
`row_type=run` to sum the 958 sessions once. The other 47 rows are calculated
views of those same runs, so summing every CSV row double-counts them.

The `experiment_summary` rows provide a cost for one comparable experiment,
using the mean over clean starts or repeated pilots where available:

| Unit of analysis | Runs | Total est. USD | Mean est. USD per run | Range est. USD |
|---|---:|---:|---:|---:|
| FFT shared-core discovery | 1 | 5.034178 | 5.034178 | — |
| FFT merge reproduction | 3 | 10.267896 | 3.422632 | 0.850796–5.657571 |
| MAC six-gate clean start | 2 | 0.206846 | 0.103423 | 0.100633–0.106213 |
| MAC four-gate pilot, separate | 1 | 0.034201 | 0.034201 | — |
| FIR merge | 1 | 0.043599 | 0.043599 | — |
| DWT merge | 1 | 0.393221 | 0.393221 | — |
| Final FFT PowerSave | 1 | 2.676040 | 2.676040 | — |
| Earlier FFT power pilots | 5 | 6.997654 | 1.399531 | 0.921224–2.329630 |

The CSV also gives `sweep_cell_summary` rows for repeated model-sweep cells
and mutually exclusive `reconciliation_total` categories. The eight accepted
FFT/MAC/FIR/DWT merge campaigns cost an estimated $15.945739 together; no
pooled per-run average is given because their domains and protocols differ.
`total_tokens` is ccusage's reported session total. Across all sessions it is
8,537,980 higher than the sum of the four listed token components (input,
output, cache read, cache creation); the CSV exposes that difference as
`total_minus_listed_tokens` rather than guessing its meaning.
`unpriced_session_count` identifies sessions using a model for which ccusage
reported no price. The file does not label the difference as reasoning tokens
because ccusage's session report did not supply a separate reasoning field.

## Scope

These are ccusage estimates for OpenCode session records assigned by working
directory. A run's subtotal can include advice, implementation, retries, and
debugging sessions in that directory. They are not invoices or a complete
project cost. Native Gemini Developer API calls outside OpenCode, VM time,
physical-tool compute, and other work without an OpenCode session are not
included. The VM-wide report identified `union-alpha` and
`thinkingmachines/inkling:free` as models with missing pricing. Do not treat
their zero estimated cost as proof of zero expenditure.
