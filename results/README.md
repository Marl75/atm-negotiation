# Results kept as evidence

Final runs with the official challenge workbook limits (31 Oct 2026). Everything else in `eval/` and `logs/` is
regenerated locally and not versioned.

| Folder | What | Command |
|---|---|---|
| `eval/*_prev_leg_s0-*` | 3 disjoint samples of 50 leak-free flights (inbound delay from the previous leg) | `atm eval --population prev_leg --n 50 --samples 3` |
| `eval/*_stress_s0-*` | 3 disjoint samples of 35 flights where the uncoordinated plan breaks a rule or flies holding | `atm eval --population stress --n 35 --samples 3` |
| `audit/*_n10000_gwb_first` | Rules-only audit of the uncoordinated plan on 10,000 random disrupted flights (no LLM) | `atm audit --n 10000` |
| `logs/MQ3439-…` | Demo flight: ground rejects busy gate G10, proposes G12, consensus at turn 2 | — |
| `logs/WN1347-…` | Failure case: crew would exceed 13 h whatever the plan, escalated with the reason | — |

Each `results.csv` has one row per flight; `summary.md` has the metrics. Aggregate with
`uv run atm eval-report results/eval/*_prev_leg_s0-*`. Each log is JSONL: one line per turn (proposal, the three
agents' structured messages, every deterministic check with its source), then the outcome (final plan,
`fallback_reason`, `human_decision`).
