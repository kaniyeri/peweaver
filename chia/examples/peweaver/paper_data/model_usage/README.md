# Model Usage / Token-Cost Data Pack

Aggregated: 2026-09-24, from the project VM (`peweaver-vm`) under
`/work/peweaver/runs/`. Sources are per-call usage records written by the
OpenCode CHIA adapter (`*.usage.jsonl`, one JSON object per call attempt) and
the model-neutral shim ledgers (`ledger-*.jsonl`, nested `usage` objects).

## Files

| File | Grain |
|---|---|
| `usage_per_call.csv` | One row per call attempt: run, role, model, timestamp, attempt, tokens, cache, cost, failure reason |
| `usage_per_run.csv` | Aggregated per run (loop), with planner/worker model names when known |
| `usage_per_run_model.csv` | Aggregated per run x model |
| `usage_per_model.csv` | Aggregated per model string across all runs |
| `usage_per_cell.csv` | Aggregated per settle-matrix cell (prefix before `-rN`) |

## What is covered

- Settle-matrix model sweeps: `msweep2-impl-*` (worker-only cells), `msweep3-*`
  (adviser -> worker cells), `msweep4-impl-*`, `msweep-free-union`,
  `msweep-codex-luna` (2026-09-17).
- Model-neutral lead/worker ledgers: `merged-e2e-gemini-1..7`,
  `diag-capture-1` (2026-08/09).
- Secondary deepseek implementation probes:
  `chia-generated-deepseek*` (2026-09-19).

## What is NOT covered (no token records exist)

- Canonical accepted-candidate campaigns: `merge-clean-1/2/3` (FFT discovery +
  3 reproductions), `ps-fft-6` (ChiaPowerSave), `mac-merge-1/2/3`, `fir-merge-1`,
  `dwt-merge-1`, `merge-clean-20260919-newarch` (precursor), and
  `power-opt-20260920`. These recorded advice text and manifests but not
  per-call token usage. Do not extrapolate token counts for them.

## Honest caveats

- 230 of 601 rows are failed calls (zero tokens, e.g. `run_failed`,
  route failures in `msweep3-g2g*` and `msweep4-impl-luna-*`); they contribute 0
  tokens and are retained in `usage_per_call.csv` for failure accounting.
- Claude rows capture output tokens but recorded almost no input tokens
  (adapter capture limitation for that provider): 51/36 input tokens vs
  480,882 output tokens.
- `cost_usd` is present only where the opencode export reported it
  (kimi, claude, glm, minimax, deepseek variants, grok). Sol/terra/luna
  (internal openai route) rows report 0.00 and are billable but not
  cost-instrumented.
- `reasoning_tokens` and `cache_read`/`cache_write` are provider-reported and
  sparse: cache_write appears only for claude/kimi-style providers.
- Roles: `advise` = ChiaMerge adviser call, `implement` = ChiaMerge
  implementer call, `lead`/`worker` = model-neutral shim roles, `model` =
  single-call deepseek probes.

## Headline totals (all recorded calls)

| Metric | Value |
|---|---|
| Call rows | 601 (371 with tokens; 230 zero-token failures) |
| Input tokens | 10,554,747 |
| Output tokens | 5,539,538 |
| Reasoning tokens | 1,843,531 |
| Cache read tokens | 21,735,804 |
| Cache write tokens | 1,439,228 |
| Recorded cost (USD) | 24.89 (partial; see caveat above) |
