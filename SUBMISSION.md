# Submission kit — Autonomous SG 2026, Airbus track, Challenge #2

Solo project: **Marlène Menoire**. Copy-paste the blocks below into the submission form.

## Project name
ATM Negotiation: three agents, one checked plan

## Tagline (≤ 140 characters)
ATC, pilot and ground AI agents negotiate a disrupted flight in ≤ 3 turns; fixed rules decide legality, a supervisor approves.

## Short description (~100 words)
When a gate is blocked or a crew runs out of duty time, the approach supervisor still coordinates by phone. We built
three independent agents (ATC, pilot, ground), each a separate Claude call that sees only its own domain. They exchange
structured messages for at most three turns. Deterministic rules from the challenge workbook decide what is legal; a
solver decides when they disagree and logs why; the supervisor approves. On 10,000 disrupted 2015 DOT flights, 5.1 %
had an illegal uncoordinated plan. Across 255 evaluated flights, 200/200 kept plans were safe and no agent ever
accepted a plan breaking a rule of its own domain.

## Long description
**Problem.** The user is the approach supervisor at a hub (DFW in the demo). When a disruption hits, tower, airline
dispatch and ramp each see only their own constraints and coordinate by phone. A rules-only audit of 10,000 disrupted
flights from `flights.csv` finds that 5.1 % [4.7–5.6] of uncoordinated plans break a hard rule (crew duty 2.5 %,
occupied gate 2.6 %), and 2.6 % have no legal plan at all.

**Approach.** One row of `flights.csv` is the disruption. ATC, pilot and ground agents are three independent Claude
calls; each receives only its domain's context and the deterministic checks of its domain. One turn = each agent sends
one structured message (accept / violated constraints / concerns / counter-proposal, validated by schema). The
orchestrator picks the next proposal deterministically (safety first, then cost, then airborne holding, then delay),
can merge counters on each role's own levers, and puts a ground hold to a vote when an agreed plan still flies
holding. After 3 turns without agreement, a deterministic solver decides and the log says why. Nothing applies until
the approach supervisor approves; plans with no legal option are escalated, never forced.

**LLM / non-LLM split.** The LLM negotiates and explains. Legality is decided by code: wake separation, fuel reserve,
crew duty, gate availability and gate-change notice, curfews, all from the challenge workbook, each check carrying its
basis (regulatory / data / assumption) and source.

**Evaluation.** 3 disjoint samples per population. Leak-free flights (150): 96 % consensus, 144/144 safe plans.
Flights under stress (105): 56/56 safe plans; ground fixes gates (29 %), ground holds replace airborne holding (21 %),
and 31–57 % are escalated because the crew would exceed 13 h whatever the plan. Zero own-domain unsafe acceptances on
over 450 flights checked in the logs. Turnaround calibrated per airline (fit Jan–Jun, tested Jul–Dec) cut the
departure-delay error from 16.7 to 14.0 min. Cost $0.04–0.09 and 9–14 s per flight.

**Failure cases shown.** Crew-duty escalations; a data leak we found ourselves (a DOT delay column filled after the
flight explained our "perfect" predictions), isolated and excluded from accuracy claims; run-to-run LLM variability
(~10 % of flights).

**Limits and next steps.** Airport limits are the workbook's synthetic values; the 13-h crew rule is simplified (Part
117 Table B is coded as a variant). Next: live gate plan, crew pairings and declared arrival rates from one airline,
in shadow mode.

## Challenge
Challenge #2 — Multi-agent communication framework for ATC, pilots and ground operations.

## Built with
Python 3.12, Claude (Opus 5.5) via the Anthropic SDK with schema-validated outputs, pandas, pydantic, pytest (54
offline tests, no API cost), uv. Data: DOT 2015 `flights.csv` (provided), challenge constraints workbook, FAA aircraft
registry.

## Links to fill in
- Repository: `https://github.com/<you>/<repo>`
- Pitch script: https://claude.ai/artifact/EoRVEkVsGTZEc91nQ1Zjq9 (share it first)
- Adoption page: https://claude.ai/artifact/SgUFqbSEUWMSdPyVgEVJch (share it first)
- Deviations slide: https://claude.ai/artifact/7cLRCpXndiGV9hRumHaTg2 (share it first)
- Demo video (if asked): record the viewer replay of MQ3439 + `atm check-proposal`, ≤ 3 min

## Checklist before submitting
- [ ] Submit early: the recorded submission time counts in "time discipline".
- [ ] Repository pushed; README opens with the English overview.
- [ ] Artifact links shared (Share menu), or exported to PDF/screenshots for the deck.
- [ ] Deck includes the "Deviations from the workbook" slide (required by the rules of play).
- [ ] `uv run pytest -q` passes on a fresh clone (needs `data/raw/flights.csv`, see README).
- [ ] Pitch rehearsed and timed under 3 minutes.
- [ ] No API key in the repo (`.env` is ignored; checked in git history).

## Judging rubric mapping
| Criterion | Weight | Where to point the judges |
|---|---|---|
| Problem realism | 20 % | Named user (DFW approach supervisor), phone-tree status quo, 5.1 % audit figure |
| Technical soundness | 25 % | 3 separate calls, domain-only views, deterministic checks + solver, schema-validated messages, 54 tests |
| Honest evaluation | 20 % | Baselines (status quo, solver, DOT reality), 3 samples with ranges, leak found and isolated, failure cases |
| Trust & traceability | 20 % | Every check has basis + source, JSONL log per turn, `fallback_reason`, supervisor approval in the log |
| Impact | 10 % | Illegal plans caught before departure, escalations with reasons, ground holds instead of holding, cost per flight |
| Time discipline | 5 % | Submit early; 2:45 script |
