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
