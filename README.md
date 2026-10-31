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

## Résultats d'évaluation — run du 31/10/2026 (`atm eval --n 20 --seed 0`)
Échantillon stratifié : 10 lignes météo + 10 late aircraft (le fichier est à 91 % late aircraft). Opus 5.5, effort `low`.

| Métrique | Négocié (3 agents) | Repli déterministe seul | Statu quo (offre ATC seule) | Réalité DOT |
|---|---|---|---|---|
| Consensus | 20/20, toujours en 2 tours | — | — | — |
| Solutions finales sûres (contrôles hard) | **20/20** | 20/20 | **0/20** | — |
| Attente en vol moyenne | 6,4 min | **0 min** | 15 min | inconnue |
| Retard moyen à l'arrivée | 73,4 min | 73,4 min | 73,4 min | 89,2 min |
| Échecs soft moyens (rotation, équipe) | 0,5 | 0,5 | — | — |
| Retard du vol suivant : erreur moyenne (6 cas) | 36 min, sous-estimé de 25 min | | | |
| Coût / latence | 120 appels, **2,34 $** (0,12 $/vol), 32 s/vol | ~0 s | | |

**Ce que ça montre honnêtement**
- Les agents n'ont **jamais** accepté une proposition dangereuse, et le checker garantit 20/20 de solutions sûres.
- **Le solveur déterministe fait mieux que les LLM sur le coût** : 0 min d'attente en vol contre 6,4. Les agents restent ancrés sur les 15 min de l'offre initiale et les réduisent sans aller jusqu'à 0 (aucun ne propose de retenir l'avion au sol au départ).
- Le consensus à 100 % en 2 tours est **flatteur** : l'offre initiale échoue toujours sur le sillage (1,5 min derrière un Heavy), donc le tour 1 corrige une erreur évidente. Le statu quo « 0/20 sûr » est construit, ce n'est pas une mesure de la réalité.
- Les 16 min d'écart avec la réalité **ne sont pas un gain** : le créneau d'entrée = `WEATHER + LATE_AIRCRAFT` et ignore les retards compagnie / système (ex. B61152 : 49 min prévu, 229 réel).
- Le retard du vol suivant est **sous-estimé** (UA237 : 0 min prédit, 131 réel) : le modèle de rotation ne voit que notre arrivée, pas les autres causes.
- Limites : n=20, une seule graine, LLM non déterministe, contexte en grande partie simulé.

## Démarrage
```bash
cp .env.example .env      # puis mettre ANTHROPIC_API_KEY
uv run atm check          # vérifie la clé API et les données
uv run pytest             # tests hors ligne (agents factices, aucun coût)
uv run atm run --row 0    # une négociation (appelle l'API)
uv run atm eval --n 20    # banc d'éval (~0,12 $ par vol)
```

## TODO
- [x] Contraintes sourcées (sillage ICAO, réserve 45 min, rotation via tail number)
- [x] Choix déterministe de la contre-proposition
- [x] Banc d'éval avec baselines
- [ ] Mettre la solution du solveur dans les candidats + option « retenue au sol au départ » (holding 0)
- [ ] Offre initiale plus réaliste (pas un homme de paille) pour mesurer une vraie négociation
- [ ] Correspondances passagers, débit secteur (AAR), taxiways
- [ ] UI de démo (journal de consensus lisible)
