# ATM Negotiation — Airbus challenge #2

> **Hackathon project.** Built solo by Marlène Menoire in one day for **Autonomous SG 2026** (Acacia Hackathon Society
> × NUS Product Club, AI & Aerospace track, Airbus challenge #2, National University of Singapore, 31 October 2026).
> It is a research prototype, not an operational tool: the flight data is the public 2015 US DOT delay dataset, the
> airport limits are synthetic values provided by the organisers, and no real air traffic decision relies on it.

Three independent AI agents (ATC, pilot, ground ops) negotiate one disrupted flight from the 2015 DOT data in at most
three turns. Each agent is a separate Claude call that sees only its own domain. **Deterministic rules from the
challenge workbook decide what is legal**; a solver decides when the agents disagree and logs why; the approach
supervisor approves.

## See it in your browser

| | |
|---|---|
| ✈️ **[Same flight, two evenings](https://marl75.github.io/atm-negotiation/pitch/two-evenings.html)** | Animated replay: phone tree vs agents on a real late flight, a "try to break it" rule sandbox, limits, and a Changi what-if |
| 🎞️ **[Pitch deck](https://marl75.github.io/atm-negotiation/pitch/deck/)** | 9 slides (← → to move, N for speaker notes) |
| 🔎 **[Negotiation viewer](https://marl75.github.io/atm-negotiation/viewer/)** | Every turn, check and rule source of the recorded demo flights · [scorecard](https://marl75.github.io/atm-negotiation/viewer/scorecard.html) |
| 🗓️ **[Monday morning at DFW](https://marl75.github.io/atm-negotiation/pitch/monday-morning.html)** | What adoption would look like for each team |
| 📐 **[Workbook deviations](https://marl75.github.io/atm-negotiation/pitch/workbook-deviations.html)** | The 7 places where I depart from the official constraints workbook, and why |
| 🎤 **[Pitch script](https://marl75.github.io/atm-negotiation/pitch/pitch.html)** | The spoken 2:45 script |

Sources are in [`pitch/`](pitch/) and [`viewer/`](viewer/); the deck is rebuilt with `python3 pitch/deck/build.py`.

## Results at a glance

| | Result |
|---|---|
| Uncoordinated plans breaking a hard rule (rules-only audit, 10,000 flights) | **5.1 %** [4.7–5.6]; 2.6 % have no legal plan |
| Safe plans kept (255 evaluated flights, 3 samples × 2 populations) | **200 / 200** |
| Agents accepting a plan that breaks a rule of their own domain (450+ flights checked) | **0** |
| Ordinary flights: consensus within 3 turns (planned slot kept as is: 89 %) | 96 % (92–100 %) |
| Flights under stress: consensus / escalated to a human (crew > 13 h) | 54 % (43–69 %) / 47 % (31–57 %) |
| Departure-delay error after per-airline turnaround calibration (Jul–Dec, unseen) | 16.7 → **14.4 min** (−14 %) |
| Cost and latency | $0.04–0.09, 8–14 s per flight |

Details: [Final results](#final-results--official-workbook-limits), [audit](#rules-only-audit-of-10000-flights),
[calibration](#calibration), raw evidence in [`results/`](results/), submission text in [`SUBMISSION.md`](SUBMISSION.md).

## Contents
- [Quick start](#quick-start)
- [The challenge](#the-challenge)
- [What the data shows](#what-the-data-shows)
- [Architecture](#architecture)
- [Constraints and where each value comes from](#constraints-and-where-each-value-comes-from)
- [No information leak](#no-information-leak)
- [Final results — official workbook limits](#final-results--official-workbook-limits)
- [Rules-only audit of 10,000 flights](#rules-only-audit-of-10000-flights)
- [Calibration](#calibration)
- [Earlier run (before the workbook)](#earlier-run-before-the-workbook)
- [Project status](#project-status)
- [Limits](#limits)
- [Beyond the hackathon](#beyond-the-hackathon)

## Quick start

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env       # then set ANTHROPIC_API_KEY (never commit .env)
```

Put the provided `flights.csv` (plus `airlines.csv`, `airports.csv`) in `data/raw/`. The challenge data is the DOT 2015
flight delays set from the organisers' Google Drive (`Challenge #2\DATA`); rows kept: `WEATHER_DELAY > 15` or
`LATE_AIRCRAFT_DELAY > 20`. Optional: the FAA aircraft registry
(`https://registry.faa.gov/database/ReleasableAircraft.zip`) unzipped into `data/raw/faa/` gives real aircraft types.

| Command | What it does | API cost |
|---|---|---|
| `uv run atm check` | Checks the API key and the data | none |
| `uv run pytest -q` | 54 offline tests with fake agents | none |
| `uv run atm run --row 356` | One negotiation, then the supervisor approves or rejects (`--auto-approve` to skip) | ~$0.05 |
| `uv run atm check-proposal --row 356 --holding 40 --gap 1.0` | Runs the deterministic checks on any proposal, as JSON: try to break the rules | none |
| `uv run atm eval --population prev_leg --n 50 --samples 3` | Evaluation bench (populations `stratified`, `prev_leg`, `stress`; `--max-cost` caps spend) | ~$0.05 per flight |
| `uv run atm eval-report results/eval/*_prev_leg_s0-*` | Aggregates several eval runs into markdown | none |
| `uv run atm audit --n 10000` | Rules-only audit of the uncoordinated plan | none |
| `uv run atm calibrate` | Refits the turnaround and compares prediction models | none |

Offline viewer: `python3 viewer/bundle.py`, then open `viewer/index.html` (replay) and `viewer/scorecard.html`.

## The challenge

> *How can AI help air traffic controllers, pilots and ground staff decide faster and better?*

What the brief asks for:
- **3 independent agents**, one LLM call each, never a single prompt:
  - **ATC**: runway wake-turbulence separation, taxiway blocks, maximum sector throughput;
  - **Pilot**: fuel reserves, safety, turbulence, passenger connections;
  - **Ground**: gate use, no overtime for ground crews, shorter turnarounds.
- Structured messages, **explicit constraint checks**, a **traceable consensus log**, a **deterministic non-AI
  fallback**.
- Converge on the revised arrival time, gate or flight plan **in 3 turns or fewer**.
- Avoid: one prompt for everything, endless loops, accepting a solution outside safety margins.
- Use the official constraints workbook; **any limit you change must be stated**.

Judging rubric: problem realism 20 %, technical soundness 25 %, honest evaluation 20 %, trust and traceability 20 %,
impact 10 %, time discipline 5 %. [`SUBMISSION.md`](SUBMISSION.md) maps each criterion to the evidence.

## What the data shows

On the rows kept, the average departure delay (84.1 min) already equals the arrival delay (82.4 min), and the actual
flight time is 1.7 min **shorter** than scheduled. The delay is taken **on the ground, before take-off**; nothing in
the data shows airborne holding. So the negotiation works first on ground levers: **ground hold** at origin rather
than holding in the air, **gate**, **turnaround**, **crew duty**. Airborne holding only appears when the reconstructed
arrival queue overflows.

**Who negotiates.**
- **ATC** = approach control (TRACON) and its traffic management unit.
- **Pilot** = the crew **and** the airline's dispatch / operations control centre, which in practice sets the departure
  time.
- **Ground** = the airline's ground operations at the destination.

**Current practice, and where this fits.** In the US, large disruptions already go through FAA Collaborative Decision
Making: ground delay programmes with assigned take-off times (EDCT), and arrival sequencers (AMAN / TBFM). This tool
does not replace them. It handles **last-minute tactical cases when no ground delay programme is in force**: a late
inbound aircraft, a closed runway, an occupied gate. Today these are settled by phone between the approach room,
dispatch and ground coordination. The user is the approach supervisor, who approves the plan.

## Architecture

```
data.py          DOT row -> Disruption + what is known before departure (previous leg, queue, crew duty)
aircraft.py      aircraft type from the tail number (FAA registry) -> FAA wake category
traffic.py       arrival queue at destination (first ready, first served) and gate occupancy
workbook.py      reads the official challenge workbook (limits) and lists the deviations
rules.py         workbook limits + published rules (FAA wake, curfews, Part 117 as a variant)
context.py       operational context; every field carries its provenance (DATA / ASSUMPTION / REGULATORY)
agents/          ATCAgent / PilotAgent / GroundAgent: separate prompts and separate Claude calls
protocol.py      Proposal, Evaluation, ConstraintResult, Turn, Outcome (pydantic)
constraints.py   deterministic hard/soft checks per domain (no LLM)
negotiation.py   orchestrator: MAX_ROUNDS=3, checks every turn, JSONL log
fallback.py      deterministic solver when there is no consensus
cli.py           atm check / run / check-proposal / eval / eval-report / audit / calibrate
```

**One turn.** Each agent receives only its domain's context and the deterministic checks of its domain, and answers
with one structured message, validated by schema: accept or reject, which constraints are violated, concerns, and an
optional counter-proposal. The orchestrator then chooses the next proposal deterministically, ranking candidates by
hard failures, then soft failures, then airborne holding, then delay. Candidates include each agent's counter, a
merge of counters on each role's own levers, a ground hold, and the solver's plan. When an agreed plan still flies
airborne holding, the same plan with the holding moved to a ground hold at origin is put to a vote if the rules score
it better. After 3 turns without agreement, the solver decides and **the log says why** (`fallback_reason`: who
refused, which rules failed, the plan kept or the escalation).

### A human decides (`atm run`)
The agents and the solver **propose**; the approach supervisor **decides**. After the negotiation, `atm run --row N`
shows the final plan (delay, airborne holding, ground hold, runway, gate), every check on that plan (hard/soft,
pass/fail, basis, source) and each agent's remaining concerns, then asks to approve or reject with a free-text reason.
The decision (`approved` / `rejected`, reason, UTC timestamp, `decided_by: "approach supervisor"`) is written to the
`human_decision` field of the last line of the JSONL log (`null` = pending). If the solver finds no safe plan
(`final: null`), the case is never silent: it is shown as "ESCALATED: no safe option" and recorded as `escalated`,
with the supervisor's instruction. `--auto-approve` records an approval without asking (`auto: true`, so it is visibly
not human); `atm eval` and `atm audit` stay non-interactive and leave `human_decision` as `null`.

### Try the rules yourself (`atm check-proposal`)
Runs the real Python rules (`check_all`) on any proposal, without an LLM: useful to try to break the system. The
scenario comes from a DOT row (`--row N`) or from a log (`--log logs/....jsonl`, without reading the CSV again). The
proposal starts from the status quo; JSON on stdin, then the options `--delay --holding --gap --runway --gate`, replace
its fields. Output: `proposal`, `hard_ok`, `all_ok`, and every check with `passed`, `hard`, `detail`, `basis`,
`source`.

```bash
echo '{"holding_min": 90, "revised_arrival_delay_min": 120}' | uv run atm check-proposal --log logs/<flight>.jsonl --gate G9
```

## Constraints and where each value comes from

Every operational limit comes from the **official challenge workbook**
([`data/constraints/challenge2_operational_constraints.xlsx`](data/constraints/), read by `workbook.py`). Its airport
values are **synthetic**, scaled to the traffic in `flights.csv` (no real airport data). Every check in the log
carries `hard` (safety, not negotiable) or soft (cost, negotiable), a `basis` (REGULATORY / DATA / ASSUMPTION) and a
`source`.

| Check | Agent | Type | Value (source) |
|---|---|---|---|
| `runway_open` | ATC | hard | Active runways from the workbook (4 at a large hub → 1 at a non-hub); weather rows close one runway (assumption: the DOT data does not say where the weather was) |
| `wake_separation` | ATC | hard | Workbook wake table (simplified FAA JO 7110.65): Heavy→Large 5 NM, Heavy→Small 6, Super→Large 7…, 3 NM otherwise. Converted at 140 kt (assumption) |
| `landing_slot_available` | ATC | hard | First-ready, first-served queue of the flights in the file, spaced by max(wake, capacity interval). Capacity = workbook `max_runway_ops_per_hour`, half of it arrivals (assumption) |
| `airport_curfew` | ATC | hard | SNA / LGB curfews (not in the workbook, cited) |
| `final_reserve_fuel` | Pilot | hard | Workbook: **30 min** final reserve, **45 min** of holding fuel on arrival → **15 min** usable for holding (conservative reading) |
| `departure_feasible` | Pilot | hard | The aircraft cannot leave before it is ready (known delay of the inbound aircraft) |
| `flight_crew_duty` | Pilot | hard | Workbook: **13 h** maximum duty from sign-on (simplified Part 117). Sign-on 1 h before the aircraft's first departure (assumption); full Table B available as a variant (`rules.CREW_DUTY_MODEL`) |
| `gate_available` | Ground | hard | Workbook gates × the airline's share of arrivals at that airport (from the file); the workbook's `spare_gates_at_any_time` (3 or 2) are `SPARE` gates, always free |
| `gate_change_notice` | Ground | hard | Workbook: a gate change is decided **≥ 20 min** before arrival |
| `crew_shift` | Ground | soft | Workbook: **8 h** ground shifts, overtime at **1.5×**; shifts start at 06:00 / 14:00 / 22:00 (assumption) |
| `turnaround_next_leg` | Ground | soft | Workbook minimum turnaround at the destination (45 min at a large hub, 35 otherwise) before the same aircraft's next flight |

Holding fuel burn used for fuel savings: workbook, 2.4 t/h short/medium haul, 6.5 t/h long haul.

### Deviations from the workbook
The rules of play say *"any limit you change must be stated"*. They are stated in the demo, on the
[deviations page](https://marl75.github.io/atm-negotiation/pitch/workbook-deviations.html), and in code
(`workbook.DEVIATIONS`):

1. **Forecast turnaround ≠ limit turnaround.** The time the aircraft is ready uses the airline's median observed
   turnaround (fit Jan–Jun, tested Jul–Dec), **never below** the workbook minimum, which stays the limit.
2. **Wake.** The FAA B757 category is kept; all workbook pairs are identical (checked by a test).
3. **Airport curfews** added (not in the workbook).
4. **Fuel.** "45 min on arrival" is read as total holding fuel, so 15 min usable above the 30-min reserve
   (conservative; the other reading would give 45 min).
5. **Capacity.** Half of the runway operations per hour are arrivals.
6. **Ground crews.** 8-hour shifts starting at 06:00, 14:00 and 22:00.
7. **Airline gates.** Airport gates × the airline's share of arrivals there (from the file).

## No information leak

The `WEATHER_DELAY`, `LATE_AIRCRAFT_DELAY`, `AIRLINE_DELAY`… minutes are **attributed by the DOT after the flight**,
and the 5 cause columns add up exactly to `ARRIVAL_DELAY` on 100 % of the file.

**Following the brief.** The brief asks to *"pass the row parameters to the 3 agents"*. This is done: the cause
minutes are in the scenario's `dot_delay_causes_min`, which all three agents receive, labelled "DOT attribution after
the flight, not used by the checks". Agents use them to understand the kind of disruption. But **no deterministic part
reads them**: not the slot, not the checks, not the status quo, not the solver, not the audit. A test checks this
(inflating those minutes to 999 changes no deterministic result). Consequence for evaluation: when a proposal
**written by an agent** is compared with reality, the leak can enter; comparisons on the slot and the solver do not
depend on it.

What the rules use instead:
- **Inbound aircraft delay**: the previous flight of the same aircraft (same tail number) arriving late, plus the
  **per-airline calibrated** turnaround (27 min Hawaiian → 54 min United, see [Calibration](#calibration)); available
  for 40 % of rows. Otherwise `LATE_AIRCRAFT_DELAY` is used as a proxy for the inbound arrival time, and the log says
  so. Evaluation reports these proxy rows separately.
- **Landing slot**: arrival queue rebuilt from the other flights in the file, spaced by max(FAA wake, workbook
  capacity interval). Closing a runway removes its share of capacity.
- **Aircraft type**: FAA registry by tail number, registration valid in 2015 (60 % of rows); otherwise an airline +
  distance heuristic.

Actual `ARRIVAL_DELAY` / `DEPARTURE_DELAY` are never given to the agents; they are only used to measure the model's
error.

### Biases of the data provided
- The file has 358,774 rows, against about 5.8 M for the full DOT 2015 set: it only keeps delayed flights. On-time
  traffic is therefore invisible (hence the background-load assumption), and so are the same aircraft's on-time legs
  (previous leg, next leg, and the first departure of the day for Part 117, which makes that check optimistic).
- **October is missing** entirely.
- Only 2.6 % of rows have both a weather cause and a late-aircraft cause; they are classified as weather.
- The sample is of flights known to be delayed: results say nothing about flights without incident.

## Final results — official workbook limits

31 Oct 2026. `atm eval --population prev_leg --n 50 --samples 3` and `atm eval --population stress --n 35 --samples 3`
(seed 0, 3 disjoint samples per population), Opus 5.5, effort `low`. **Leak-free** = flights whose inbound delay comes
from the previous leg. **Under stress** = flights where the uncoordinated plan breaks a rule or flies airborne
holding, found by the rules alone on a random draw. Range = min–max over the 3 samples. Raw files in
[`results/eval/`](results/eval/).

| Metric | Leak-free (3 × 50 = 150 flights) | Under stress (3 × 35 = 105 flights) |
|---|---|---|
| Uncoordinated status quo breaking a safety rule | 10/150 (2–6 per sample) | 85/105 (23–33 of 35) |
| Final plans safe when a safe plan exists | **144/144** | **56/56** |
| No safe plan → escalated to the supervisor, reason logged | 6/150 (0–4) | **49/105 (31–57 %)**, almost all: crew > 13 h |
| Consensus of the 3 agents in ≤ 3 turns | **96 %** (92–100 %), 1.07 turns | 54 % (43–69 %), 1.65 turns; the rest are escalations |
| Agent accepting an unsafe plan **in its own domain** | **0** | **0** |
| Out-of-domain acceptances (by design), caught by the rules | 22 | 191 |
| Who wrote the plan kept | status quo accepted 89 % (82–96 %) | Ground 29 %, ground hold 21 %, Pilot 4 %, escalation 46 % |
| Airborne holding (status quo → negotiated) | 0.3 → 0 min | 0.7 → 0 min |
| Predicted slot vs actual delay, mean error | 38.2 min (36.9–39.7) | 18.0 min (leak-free rows, 72 flights) |
| Cost / latency | $6.73 ($0.045/flight), 8–9 s/flight | $8.97 ($0.085/flight), 14 s/flight |

**Honest reading**
- **Safety: 200/200 safe plans, 0 unsafe acceptance in the agent's own domain** on these 255 flights, and on more than
  450 flights checked in the logs counting earlier runs.
- **Day to day, little to negotiate**: about 9 ordinary flights in 10 keep the planned slot, accepted in turn 1.
- **On flights under stress, negotiation really helps** where a solution exists: the ground agent finds a free gate
  (29 % of flights), the orchestrator puts a ground hold to a vote (21 %), the pilot corrects (4 %).
- **The main failure case is crew duty**: 31 % to 57 % of flights under stress have no legal plan because the crew
  would exceed 13 h whatever is done. The system forces nothing; it escalates with the reason. The workbook's 13-h
  limit is stricter than Part 117 Table B in the morning (14 h), so this rate depends on that simplified rule.
- **Variability**: from one sample to another, consensus under stress ranges from 43 to 69 % and escalations from 31
  to 57 %. The safety guarantees do not vary: they come from the rules.
- Limits: synthetic airport limits from the workbook, non-deterministic LLM, only 3 samples.

**Demo flights** (logs in [`results/logs/`](results/logs/)): MQ3439 (Envoy, Mobile → Dallas, 45 min late) — the ground
agent sees gate G10 still busy, moves the flight to G12, consensus at turn 2, about 34 min of gate wait avoided.
WN1347 (Southwest) — the crew would end 10 min past its 13-h limit whatever the plan; escalated with the reason.

## Rules-only audit of 10,000 flights

`atm audit --n 10000`: random draw of 10,000 disrupted flights (seed 0), about 1 min, $0. For each flight: does the
uncoordinated plan (leave as soon as ready, hold in the air for the slot, keep the planned gate) break a *hard* rule?
95 % confidence intervals (Wilson). Raw files in [`results/audit/`](results/audit/).

| Measure | Workbook (current) | Before the workbook (4 gates/airline, 70 % load, 45-min reserve, Part 117) |
|---|---|---|
| Uncoordinated plan breaking a safety rule | **5.1 %** [4.7–5.6] | 18.1 % |
| of which occupied gate | 2.6 % [2.3–3.0] | 15.7 % |
| of which crew duty (13 h) exceeded | **2.5 %** [2.2–2.9] | 2.7 % |
| of which fuel reserve used | 0.1 % | 0.5 % |
| No safe plan, escalated to a human | 2.6 % [2.3–2.9] | 3.4 % |
| Flights with airborne holding | 1.6 % (median 3 min) | 4.2 % |
| Fuel saved by the solver | 2 kg/flight on average, median 0 | 16 kg/flight |

Out of 358,774 delayed flights, that is about **18,000** illegal uncoordinated plans and about **9,000** flights with
no legal plan at all.

**Honest reading**
- With the official limits, **about 1 disrupted flight in 20** has an illegal uncoordinated plan: half crew duty
  (13 h exceeded), half occupied gate. Gate conflicts are no longer concentrated at hubs (ATL 5.7 %, DFW 7.3 %, ORD
  6.4 %): with 150 gates, the earlier "4 gates per airline" assumption inflated them.
- **2.6 % of flights have no safe plan** (almost all because the crew would exceed 13 h whatever is done): they go to
  the supervisor with the reason.
- **Airborne holding is not the problem** on this data (1.6 % of flights, a few minutes): the value is in gates and
  crew, not fuel.
- The `--planned-gate random` variant is no longer a valid sensitivity check: it draws the planned gate among the gates
  shown to the agent, which are mostly busy ones (12.5 %, overstated).

## Calibration

`atm calibrate`, no LLM. Fit on **January–June 2015**, test on **July–December** (time split), only on rows whose
inbound delay comes from the previous leg (no leak): 83,171 fit rows, 60,542 test rows.

| Model (on the test months) | Departure-delay error | Departure bias | Arrival-delay error | Arrival within ±15 min |
|---|---|---|---|---|
| M0 fixed 35-min turnaround (before) | 16.7 min | −12.2 | 18.8 min | 62.8 % |
| M1 per-airline turnaround only | 14.0 min (−16 %) | −7.6 | 18.5 min | 61.9 % |
| **Adopted: max(M1, workbook minimum at origin)** | **14.4 min (−14 %)** | **−5.4** | — | — |
| M2 = M1 + historical residual delay by airline × airport × hour | 13.3 min | −6.4 | 18.3 min | 60.7 % |
| M3 = M2 + historical median on the arrival side | 13.3 min | −6.4 | 17.8 min | 65.1 % |

- **Per-airline turnaround** = median time between the inbound aircraft's landing and the flight's actual departure, when the
  departure waits for the aircraft (`LATE_AIRCRAFT_DELAY > 0`): from 27 min (HA) to 54 min (UA). Used for the time the
  aircraft is ready and for gate occupancy, **never below the workbook minimum** at the airport: this adopted model
  gives 14.4 min (−14 %, bias reduced to −5.4). Values are frozen in `calibration.py`; a test checks they match a fresh
  fit.
- **M2 / M3 measured, not adopted**: small gains (−0.7 min on departure, −0.7 min on arrival) for a less explainable
  model made of historical averages.
- **What stays unpredictable before departure**: on average 14.6 min of departure delay do not come from the inbound
  aircraft (airline, system, weather at origin). On the arrival side, schedule padding absorbs the queue (−3 min on
  average), so the 70 % background load **cannot be calibrated with this data**: FAA ASPM rates would be needed.
- The LLM evaluation draws flights over the whole year, including the fit months: with only 14 turnaround values, the
  risk of overfitting is low, but it exists.
- This is a comparison with a naive fixed-turnaround baseline, not with the tools airlines use today.

## Earlier run (before the workbook)

31 Oct 2026, `atm eval --n 20 --seed 0`, model v2: stratified sample of 10 weather + 10 late-aircraft rows (the file is
91 % late aircraft), Opus 5.5, effort `low`, own assumptions instead of the workbook limits.

| Metric | Negotiated (3 agents) | Deterministic fallback only | Status quo (uncoordinated) | DOT reality |
|---|---|---|---|---|
| Consensus | 20/20: 15 in turn 1, 5 in turn 2 | — | — | — |
| Safe final plans (hard checks) | **20/20** | 20/20 | **16/20** (measured) | — |
| Status quo failures | — | — | occupied gate ×4, fuel reserve ×1 | — |
| Mean airborne holding | 0.4 min | **0 min** | 5.6 min | unknown |
| Plan author | ATC 75 % (status quo accepted), Ground 15 %, Pilot 5 %, `GROUND_HOLD` 5 % | | | |
| Cost / latency | 75 calls, **$1.04** ($0.05/flight), 10 s/flight | ~0 s | | |

What it taught, and what changed since:
- The status quo is no straw man: 16/20 of its plans were already safe, and the agents accepted them in turn 1.
- **The problem is on the ground** (gates), not in the sky: only 5 of 20 flights had airborne holding.
- **The leak, found and isolated.** When the same aircraft's previous leg is not in the file, `LATE_AIRCRAFT_DELAY`
  stands in for the inbound arrival time. Because the cause columns add up exactly to `ARRIVAL_DELAY`, the input then
  contains part of the answer: on those rows the slot matched the actual delay exactly 31 % of the time, against 0 %
  on previous-leg rows. On the final runs the gap is 21 % vs 3 %. Since then, accuracy is only claimed on leak-free
  rows, and the final evaluation uses a leak-free population.
- **AA204** kept 8 min of airborne holding accepted in turn 1 although the solver would have moved it to the ground.
  Fixed: a consensus that still holds in the air is now upgraded to a ground hold when the rules score it better
  (`ground_hold_upgrade`).
- **MQ3174** was wrongly escalated by the first Part 117 version, which assumed the crew follows the aircraft all day.
  Now, if the schedule itself already exceeds the limit, a crew change is assumed.
- **Weather**: 5 of 10 weather flights had a predicted slot of 0 min for 49 min of actual delay on average. Nothing
  known before departure forecasts the weather; METARs or ground delay programmes would be needed (challenge #5).

## Project status

**Complete for the hackathon.** Every requirement of the brief is delivered:

- [x] Three independent agents (ATC, pilot, ground), one Claude call each, each seeing only its own domain
- [x] Structured, schema-validated messages
- [x] Explicit deterministic constraint checks, each with its basis and source
- [x] Traceable consensus log (JSONL, one line per turn, then the outcome and the human decision)
- [x] Deterministic non-AI fallback that logs why it decided
- [x] Consensus in 3 turns or fewer, otherwise the solver decides or escalates
- [x] Official constraints workbook used; every changed limit stated
- [x] The approach supervisor approves or rejects every plan
- [x] Honest evaluation: baselines, 3 samples per population, leak found and isolated, failure cases shown
- [x] Rules-only audit of 10,000 flights and turnaround calibration on unseen months
- [x] 54 offline tests, viewer, interactive page, pitch deck

Also done along the way: sourced constraints (FAA wake, curfews, tail-number turnaround), a realistic status quo,
arrival queue and gates rebuilt from the data, aircraft types from the FAA registry, ground hold proposed even after
an immediate consensus (AA204).

## Limits

- Airport limits are the workbook's synthetic values; the 13-h crew rule is simplified (Part 117 Table B is coded as a
  variant).
- The data only contains delayed flights, so on-time traffic and on-time legs are invisible.
- LLM outputs vary from run to run (about 10 % of flights); safety does not, because it comes from the rules.

## Beyond the hackathon

Ideas for a real pilot, outside the scope of the challenge:
- Shadow mode at one hub: run on every disrupted arrival, show nothing, compare with what was decided.
- Real data from one airline: live gate plan, crew pairings, declared arrival rates.
- Weather forecasts as an input (challenge #5), so the agents see the storm coming.
- Passenger connections and taxiway constraints.
- A larger leak-free sample to measure prediction accuracy more precisely.
