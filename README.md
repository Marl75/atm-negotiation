# Challenge #2 — Négociation multi-agents ATC / Pilote / Sol

Autonomous SG 2026 · Airbus Track · 31 oct 2026, NUS

> *Comment l'IA peut-elle aider les contrôleurs aériens, les pilotes et le personnel au sol à décider plus vite et mieux ?*

## Ce que le jury attend
- **3 agents indépendants** (un appel LLM chacun, jamais un seul prompt) :
  - **ATC** : séparation de turbulence de sillage sur piste, blocages de taxiway, débit max du secteur
  - **Pilote** : réserves carburant, sécurité, turbulences, correspondances passagers
  - **Sol** : utilisation des portes, pas d'heures sup pour les équipes au sol, délais de rotation réduits
- Messages structurés, **vérification explicite des contraintes**, **journal de consensus traçable**, **repli déterministe sans IA**
- Converger sur l'heure d'arrivée révisée, la porte ou le plan de vol **en moins de 3 tours**
- À éviter : un seul prompt pour tout, des boucles sans fin, accepter une solution hors marges de sécurité

## Données
DOT 2015 flight delays → Google Drive `Challenge #2\DATA`
(https://drive.google.com/drive/u/1/folders/13h0JZnSqhYTX3rV8dGDGy5AiwaADQvJR)
Mettre `flights.csv` (+ `airlines.csv`, `airports.csv`) dans `data/raw/`.
Lignes retenues : `WEATHER_DELAY > 15` ou `LATE_AIRCRAFT_DELAY > 20`.

## Grille du jury (pondérations)
| Critère | Poids | Ce qu'on doit montrer |
|---|---|---|
| Réalisme du problème | 20 % | Un utilisateur nommé (ex. superviseur de salle approche DFW), la pratique actuelle (appels téléphoniques), le coût (min de retard, carburant) |
| Solidité technique | 25 % | Le LLM négocie et explique ; **les règles et le solveur décident de ce qui est légal** |
| Évaluation honnête | 20 % | Taux de convergence sur N lignes, comparaison avec le repli seul, au moins un cas d'échec montré |
| Confiance et traçabilité | 20 % | Journal JSONL de chaque tour, contrôles passés ou échoués, un humain valide |
| Impact | 10 % | Avant/après en minutes de retard ou de holding |
| Respect du temps | 5 % | Rendu tôt, pitch ≤ 3 min |

## Architecture
```
data.py          ligne DOT -> Disruption (protocol.py)
agents/          ATCAgent / PilotAgent / GroundAgent : prompt + appel Claude séparés
protocol.py      Proposal, Evaluation, ConstraintResult, Turn, Outcome (pydantic)
constraints.py   contraintes dures déterministes par domaine (pas de LLM)
negotiation.py   orchestrateur : MAX_ROUNDS=3, contrôles à chaque tour, log JSONL
fallback.py      solveur déterministe si pas de consensus
cli.py           `atm check`, `atm run --row N`
```

## Contraintes et provenance des valeurs
Chaque contrôle du log porte `hard` (sécurité, non négociable) ou soft (coût, négociable), une `basis` et une `source`.

| Contrôle | Agent | Type | Base | Valeur / source |
|---|---|---|---|---|
| `runway_open` | ATC | hard | ASSUMPTION | Ligne météo → une piste fermée (simulé) |
| `wake_separation` | ATC | hard | REGULATORY | ICAO Doc 4444 : H→M 5 NM, H→L 6 NM, J→M 7 NM…, sinon 3 NM radar. Conversion à 140 kt (hypothèse) |
| `landing_slot_available` | ATC | hard | DATA | `WEATHER_DELAY + LATE_AIRCRAFT_DELAY` de la ligne (le PDF demande de passer ces paramètres) |
| `final_reserve_fuel` | Pilote | hard | REGULATORY | 14 CFR 121.639 : dégagement + 45 min (ICAO/EASA : 30 min). Carburant au-dessus des réserves : 20 min (**hypothèse**, le DOT n'a pas de carburant) |
| `gate_available` | Sol | hard | ASSUMPTION | Ligne late aircraft → porte prévue encore occupée (simulé) |
| `crew_shift` | Sol | soft | ASSUMPTION | Fin de service équipe au sol 23:00 (simulé) |
| `turnaround_next_leg` | Sol | soft | DATA | Prochain départ du même `TAIL_NUMBER` le même jour ; rotation mini 35 min (hypothèse) |

Supprimé de la v0 : `max_holding` (pas de limite réglementaire, c'est le carburant qui limite) et `crew_overtime` sur le retard total (faux : dépend de l'heure d'arrivée vs fin de service).

**Évaluation :** `ARRIVAL_DELAY` réel du DOT n'est jamais donné aux agents ; il sert de référence « sans le système ».

## Démarrage
```bash
cp .env.example .env      # puis mettre ANTHROPIC_API_KEY
uv run atm check          # vérifie la clé API et les données
uv run pytest             # tests hors ligne
uv run atm run --row 0    # une négociation (appelle l'API)
```

## TODO
- [ ] Vraies contraintes : catégories de sillage (minima ICAO), horaire de la prochaine rotation du même tail number, correspondances
- [ ] Scénario enrichi : piste fermée / porte en panne générée à partir de la ligne
- [ ] Choix du contre-proposition (celui qui passe le plus de contrôles durs)
- [ ] Banc d'éval : N lignes -> taux de consensus, tours moyens, delta vs repli
- [ ] UI de démo (journal de consensus lisible)
