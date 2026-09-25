# Shared-FFT model sweep

Runs: 30  Accepted: 17

## Model as planner (impl = gemini-3.8-flash)

| model | n | accepted | success% | mean turns (accepted) |
|---|---:|---:|---:|---:|
| gemini/gemini-3.8-flash | 2 | 2 | 100.0 | 2 |
| openai/gpt-5.6-sol | 2 | 2 | 100.0 | 2 |
| openai/gpt-6-astra | 2 | 2 | 100.0 | 1 |
| opencode-go/deepseek-v4.1-flash | 2 | 2 | 100.0 | 2.5 |
| opencode-go/glm-5.3-flash | 2 | 1 | 50.0 | 2 |
| opencode-go/kimi-k2.7-code | 2 | 2 | 100.0 | 1.5 |
| opencode-go/minimax-m3 | 2 | 2 | 100.0 | 1 |
| openrouter/anthropic/claude-sonnet-4.6 | 2 | 2 | 100.0 | 2 |

## Model as implementer (planner = gemini-3.8-flash)

| model | n | accepted | success% | mean turns (accepted) |
|---|---:|---:|---:|---:|
| gemini/gemini-3.8-flash | 2 | 2 | 100.0 | 2 |
| openai/gpt-5.6-sol | 2 | 2 | 100.0 | 5.5 |
| openai/gpt-6-astra | 2 | 0 | 0.0 | None |
| opencode-go/deepseek-v4.1-flash | 2 | 0 | 0.0 | None |
| opencode-go/glm-5.3-flash | 2 | 0 | 0.0 | None |
| opencode-go/kimi-k2.7-code | 1 | 0 | 0.0 | None |
| opencode-go/minimax-m3 | 1 | 0 | 0.0 | None |
| openrouter/anthropic/claude-sonnet-4.6 | 2 | 0 | 0.0 | None |

## Per-run

| run | planner | worker | status | accepted | turn | area red.% |
|---|---|---|---|---:|---:|---:|
| msweep-adv-astra-r1 | openai/gpt-6-astra | gemini/gemini-3.8-flash | done | True | 1 | 37.99 |
| msweep-adv-astra-r2 | openai/gpt-6-astra | gemini/gemini-3.8-flash | done | True | 1 | 38.15 |
| msweep-adv-claude-r1 | openrouter/anthropic/claude-sonnet-4.6 | gemini/gemini-3.8-flash | done | True | 2 | 38.75 |
| msweep-adv-claude-r2 | openrouter/anthropic/claude-sonnet-4.6 | gemini/gemini-3.8-flash | done | True | 2 | 39.68 |
| msweep-adv-deepseek-r1 | opencode-go/deepseek-v4.1-flash | gemini/gemini-3.8-flash | done | True | 1 | 36.18 |
| msweep-adv-deepseek-r2 | opencode-go/deepseek-v4.1-flash | gemini/gemini-3.8-flash | done | True | 4 | 40.54 |
| msweep-adv-glm-r1 | opencode-go/glm-5.3-flash | gemini/gemini-3.8-flash | done | True | 2 | 38.0 |
| msweep-adv-glm-r2 | opencode-go/glm-5.3-flash | gemini/gemini-3.8-flash | done | False | None | None |
| msweep-adv-kimi-r1 | opencode-go/kimi-k2.7-code | gemini/gemini-3.8-flash | done | True | 2 | 38.02 |
| msweep-adv-kimi-r2 | opencode-go/kimi-k2.7-code | gemini/gemini-3.8-flash | done | True | 1 | 38.65 |
| msweep-adv-minimax-r1 | opencode-go/minimax-m3 | gemini/gemini-3.8-flash | done | True | 1 | 36.18 |
| msweep-adv-minimax-r2 | opencode-go/minimax-m3 | gemini/gemini-3.8-flash | done | True | 1 | 38.08 |
| msweep-adv-sol-r1 | openai/gpt-5.6-sol | gemini/gemini-3.8-flash | done | True | 2 | 38.02 |
| msweep-adv-sol-r2 | openai/gpt-5.6-sol | gemini/gemini-3.8-flash | done | True | 2 | 38.17 |
| msweep-impl-astra-r1 | gemini/gemini-3.8-flash | openai/gpt-6-astra | done | False | None | None |
| msweep-impl-astra-r2 | gemini/gemini-3.8-flash | openai/gpt-6-astra | done | False | None | None |
| msweep-impl-claude-r1 | gemini/gemini-3.8-flash | openrouter/anthropic/claude-sonnet-4.6 | unindexed | False | None | None |
| msweep-impl-claude-r2 | gemini/gemini-3.8-flash | openrouter/anthropic/claude-sonnet-4.6 | done | False | None | None |
| msweep-impl-deepseek-r1 | gemini/gemini-3.8-flash | opencode-go/deepseek-v4.1-flash | done | False | None | None |
| msweep-impl-deepseek-r2 | gemini/gemini-3.8-flash | opencode-go/deepseek-v4.1-flash | done | False | None | None |
| msweep-impl-glm-r1 | gemini/gemini-3.8-flash | opencode-go/glm-5.3-flash | done | False | None | None |
| msweep-impl-glm-r2 | gemini/gemini-3.8-flash | opencode-go/glm-5.3-flash | done | False | None | None |
| msweep-impl-kimi-r1 | gemini/gemini-3.8-flash | opencode-go/kimi-k2.7-code | done | False | None | None |
| msweep-impl-kimi-r2 | None | None | unindexed | False | None | None |
| msweep-impl-minimax-r1 | gemini/gemini-3.8-flash | opencode-go/minimax-m3 | done | False | None | None |
| msweep-impl-minimax-r2 | None | None | unindexed | False | None | None |
| msweep-impl-sol-r1 | gemini/gemini-3.8-flash | openai/gpt-5.6-sol | done | True | 8 | 37.53 |
| msweep-impl-sol-r2 | gemini/gemini-3.8-flash | openai/gpt-5.6-sol | done | True | 3 | 37.11 |
| msweep-ref-gemini-r1 | gemini/gemini-3.8-flash | gemini/gemini-3.8-flash | done | True | 2 | 38.06 |
| msweep-ref-gemini-r2 | gemini/gemini-3.8-flash | gemini/gemini-3.8-flash | done | True | 2 | 40.32 |
