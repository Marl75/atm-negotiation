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

## Le problème que montrent les données
Sur les lignes retenues, le retard moyen au départ (84,1 min) vaut déjà le retard à l'arrivée (82,4 min), et le temps
de vol réel est 1,7 min **sous** l'horaire. Le retard est donc pris **au sol, avant le décollage** : rien dans les
données ne montre d'attente en vol. On négocie donc d'abord les leviers sol : **retenue au départ** plutôt qu'attente
en vol, **porte**, **rotation**, **service équipage**. L'attente en vol n'apparaît que quand la file d'arrivée
reconstituée déborde.

**Qui négocie.** ATC = contrôle d'approche (TRACON) et sa cellule de gestion des flux. Pilote = l'équipage **et** le
dispatch / centre de contrôle des opérations de la compagnie, qui décide en pratique de l'heure de départ.
Sol = opérations sol de la compagnie à destination.

**Pratique actuelle, et où on se place.** Aux États-Unis, les grosses perturbations passent déjà par la décision
collaborative (CDM) de la FAA : programmes de retard au sol (GDP) avec heure de décollage assignée (EDCT), et
séquenceurs d'arrivée (AMAN / TBFM). On ne les remplace pas. On traite le **tactique de dernière minute, quand aucun
GDP n'est en vigueur** : un avion arrivé en retard, une piste fermée, une porte prise. Aujourd'hui, ça se règle au
téléphone entre la salle d'approche, le dispatch et la coordination sol. Utilisateur : le superviseur de salle
d'approche, qui valide le plan.

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
data.py          ligne DOT -> Disruption + infos connues avant départ (vol précédent, file, service équipage)
aircraft.py      type d'avion par immatriculation (registre FAA) -> catégorie de sillage FAA
traffic.py       file d'arrivée à destination (premier prêt, premier servi) et occupation des portes
rules.py         règles publiées et sources : FAA 7110.65, 14 CFR 121.639, Part 117, couvre-feux
context.py       contexte opérationnel, chaque champ avec sa provenance (DATA / ASSUMPTION / REGULATORY)
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
| `runway_open` | ATC | hard | ASSUMPTION | Ligne météo → une piste fermée à destination (le DOT ne dit pas où était la météo : départ, route ou arrivée) |
| `wake_separation` | ATC | hard | REGULATORY | **FAA JO 7110.65 §5-5-4** (espace américain, pas ICAO) : Heavy→Large 5 NM, Heavy→Small 6, Super→Large 7…, sinon 3 NM radar. Avion devant = le vrai précédent dans la file. Conversion à 140 kt (hypothèse). Aéroports en RECAT : autres valeurs |
| `landing_slot_available` | ATC | hard | DATA | Créneau « premier prêt, premier servi » dans la file reconstituée (même aéroport, même jour). **Aucune minute de cause DOT utilisée** |
| `airport_curfew` | ATC | hard | REGULATORY | Couvre-feux SNA (arrivées 07:00–23:00) et LGB (07:00–22:00), à vérifier |
| `final_reserve_fuel` | Pilote | hard | REGULATORY | 14 CFR 121.639 : dégagement + 45 min (ICAO/EASA : 30 min). Carburant au-dessus des réserves : 20 min (**hypothèse**, le DOT n'a pas de carburant) |
| `departure_feasible` | Pilote | hard | DATA | L'avion ne part pas avant d'être prêt : retard − attente en vol ≥ retard connu de l'avion entrant |
| `flight_crew_duty` | Pilote | hard | REGULATORY | **14 CFR 117 Table B** : service max selon l'heure de prise de service et le nombre d'étapes. Prise de service = 1 h avant le premier départ de l'avion ce jour-là dans le fichier (hypothèse : l'équipage suit l'avion). Au-delà : un humain décide (extension 117.19 ≤ 2 h ou équipage de réserve) |
| `gate_available` | Sol | hard | DATA | 4 portes par compagnie (hypothèse) ; les arrivées de la même compagnie séquencées avant nous occupent une porte pendant une rotation |
| `crew_shift` | Sol | soft | ASSUMPTION | Fin de service équipe au sol 23:00 (simulé) |
| `turnaround_next_leg` | Sol | soft | DATA | Prochain départ du même `TAIL_NUMBER` le même jour ; rotation mini 35 min (hypothèse) |

Supprimé de la v0 : `max_holding` (pas de limite réglementaire, c'est le carburant qui limite) et `crew_overtime` sur le retard total (faux : dépend de l'heure d'arrivée vs fin de service).

### Ce qui est connu au moment de décider (pas de fuite d'information)
Les minutes `WEATHER_DELAY`, `LATE_AIRCRAFT_DELAY`, `AIRLINE_DELAY`… sont **attribuées par le DOT après le vol**. Elles
ne sont plus données aux agents ni utilisées pour le créneau. Ce qu'on utilise à la place :
- **Retard de l'avion entrant** : vol précédent du même avion (même immatriculation) arrivé en retard + 35 min de
  rotation (40 % des lignes). Sinon `LATE_AIRCRAFT_DELAY` sert d'approximation de l'heure d'arrivée prévue de l'avion
  entrant, et c'est signalé dans le log.
- **Créneau d'atterrissage** : file d'arrivée reconstituée à partir des autres vols du fichier, espacés selon le
  sillage FAA. Le trafic à l'heure, absent du fichier, charge chaque piste à 70 % (hypothèse, à caler sur les débits
  FAA ASPM). Fermer une piste sature donc l'aéroport.
- **Type d'avion** : registre FAA par immatriculation, enregistrement valide en 2015 (60 % des lignes). Sinon
  heuristique compagnie + distance. Le registre se télécharge sur
  `https://registry.faa.gov/database/ReleasableAircraft.zip` et se dézippe dans `data/raw/faa/`.

### Biais des données fournies
- Le fichier fait 358 774 lignes, contre environ 5,8 M pour le DOT 2015 complet : il ne garde que les vols retardés.
  On ne voit donc ni le trafic à l'heure (d'où l'hypothèse de charge de fond), ni les étapes à l'heure du même avion
  (vol précédent, vol suivant, et premier départ de la journée pour la Part 117, ce qui rend ce contrôle optimiste).
- **Octobre manque** entièrement.
- Seules 2,6 % des lignes ont à la fois une cause météo et une cause avion en retard ; elles sont classées météo.
- On échantillonne des vols dont on sait qu'ils ont été retardés : les résultats ne disent rien des vols sans incident.

**Évaluation :** `ARRIVAL_DELAY` / `DEPARTURE_DELAY` réels du DOT ne sont jamais donnés aux agents ; ils servent à mesurer l'erreur du modèle.

## Résultats d'évaluation — run du 31/10/2026 (`atm eval --n 20 --seed 0`), modèle v2
Échantillon stratifié : 10 lignes météo + 10 late aircraft (le fichier est à 91 % late aircraft). Opus 5.5, effort `low`.
v2 = file d'arrivée reconstituée, statu quo réaliste, règles FAA, Part 117, aucune minute de cause DOT en entrée.

| Métrique | Négocié (3 agents) | Repli déterministe seul | Statu quo (sans coordination) | Réalité DOT |
|---|---|---|---|---|
| Consensus | 20/20 : 15 au tour 1, 5 au tour 2 | — | — | — |
| Solutions finales sûres (contrôles hard) | **20/20** | 20/20 | **16/20** (mesuré) | — |
| Échecs du statu quo | — | — | porte occupée ×4, réserve carburant ×1 | — |
| Attente en vol moyenne | 0,4 min | **0 min** | 5,6 min | inconnue |
| Carburant économisé vs statu quo | ≈ 210 kg/vol, **dont un seul vol** (DL826, 98 min) ; **15 kg/vol sans lui** (40 kg/min d'attente, hypothèse) | | | |
| Auteur de la solution retenue | ATC 75 % (statu quo accepté), Sol 15 %, Pilote 5 %, `GROUND_HOLD` 5 %, `SOLVER` 0 % | | | |
| Acceptations d'un plan dangereux | 7, **toutes hors du domaine de l'agent** (0 dans son domaine) | | | |
| Retard moyen à l'arrivée | 56,8 min | 56,8 min | 56,8 min | 86,2 min |
| Erreur du créneau prédit vs retard réel | 41 min en moyenne, **sous-estimé de 34 min** | | | |
| Retard du vol suivant : erreur moyenne (6 cas) | 55 min, sous-estimé de 50 min | | | |
| Coût / latence | 75 appels, **1,04 $** (0,05 $/vol), 10 s/vol | ~0 s | | |

**Ce que ça montre honnêtement**
- Le statu quo n'est plus un homme de paille : 16/20 de ses plans sont déjà sûrs, et les agents les acceptent au
  tour 1. Les 4 échecs sont **mesurés** : porte prévue encore occupée par un avion de la même compagnie (4 cas), et
  DL826 (ATL, météo) qui aurait dû tourner 98 min en attente avec 20 min de carburant disponible.
- Sur ces données, le problème est **au sol** (portes), pas dans le ciel : 5 cas sur 20 seulement ont de l'attente en vol.
- **Qui a trouvé la solution :** sur les 5 vols où le statu quo est corrigé, 4 l'ont été par un agent (Sol ×3 en
  trouvant une porte libre, Pilote ×1 en supprimant 7 min d'attente) et 1 par l'orchestrateur (DL826 : 98 min
  d'attente en vol transformées en retenue au sol, `GROUND_HOLD<GROUND`). Le solveur n'a jamais gagné. La
  négociation n'a donc réellement servi que sur 5 vols sur 20 ; les 15 autres sont un statu quo déjà sûr accepté.
- Le solveur reste au moins aussi bon que les LLM : AA204 garde 8 min d'attente en vol acceptées au tour 1, alors
  que le solveur les aurait reportées au sol. Cause : `GROUND_HOLD` et `SOLVER` ne sont évalués que si un agent
  refuse ; un consensus immédiat ne passe pas par le classement. Les LLM servent à **expliquer** et à **négocier** ;
  ce sont les règles et le solveur qui garantissent la légalité.
- **Les 7 acceptations de plans dangereux sont voulues :** chaque agent ne voit que son domaine, donc l'ATC et le
  pilote acceptent une porte occupée qu'ils ne voient pas. Vérifié dans les logs : **aucun agent n'a accepté un plan
  qui viole une règle de son propre domaine**. Le contrôle déterministe rattrape les autres.
- Le créneau prédit **sous-estime** le retard réel de 34 min : on n'utilise plus les minutes de cause DOT, et les
  retards compagnie / système / météo au départ ne sont pas prévisibles avec ce qu'on sait avant le départ. Les
  retards météo réels ne s'expliquent presque pas par la file à destination (créneau médian +3 min, réel médian
  +79 min) : la météo du DOT agit surtout **avant le décollage**.
- **Fuite restante, isolée dans l'éval :** quand le vol précédent du même avion n'est pas dans le fichier (80 % de
  cet échantillon, 60 % du fichier), `LATE_AIRCRAFT_DELAY` sert d'approximation de l'heure d'arrivée de l'avion
  entrant. C'est une attribution faite après coup, et les 5 colonnes de cause s'additionnent **exactement** à
  `ARRIVAL_DELAY` sur 100 % du fichier : l'entrée contient une partie de la réponse. Le résumé d'éval sépare donc
  chaque comparaison avec la réalité par source, et seule la ligne « vol précédent » est annonçable :

  | Source du retard connu | Vols | Créneau = retard réel exactement | Erreur moyenne du créneau |
  |---|---|---|---|
  | Vol précédent (légitime) | 4 | **0 %** | 23,5 min |
  | `LATE_AIRCRAFT_DELAY` (fuite) | 16 | **31 %** (5 vols, ex. DL678 : 127 prédit, 127 réel) | 45,4 min |

  Les créneaux « parfaits » viennent tous de la fuite, pas du modèle. Avec 4 vols, la précision légitime n'est pas
  mesurable : il faut un échantillon plus grand, restreint aux vols dont le vol précédent est connu. Les 6 cas de
  vol suivant sont tous des lignes à fuite.
- **Météo :** 5 vols météo sur 10 ont un créneau prédit de 0 min pour 49 min de retard réel en moyenne. Rien de ce
  qu'on sait avant le départ ne prévoit la météo ; il faudrait des METAR / programmes de retard au sol (challenge 5).
- **Cas d'échec corrigé en cours de route :** la première version de la Part 117 supposait que l'équipage suit l'avion
  toute la journée. MQ3174 (5 étapes depuis 07:40) était alors escaladé à tort. Désormais, si l'horaire prévu
  dépasse déjà la limite, on suppose un changement d'équipage.
- Limites : n=20, une seule graine, LLM non déterministe, charge de fond à 70 % et 4 portes par compagnie non calées.

v1 (avant recadrage) : consensus 20/20 en 2 tours, mais le statu quo était construit pour échouer (0/20 sûr) et le
créneau utilisait `WEATHER_DELAY + LATE_AIRCRAFT_DELAY` connus après coup.

## Démarrage
```bash
cp .env.example .env      # puis mettre ANTHROPIC_API_KEY
uv run atm check          # vérifie la clé API et les données
uv run pytest             # tests hors ligne (agents factices, aucun coût)
uv run atm run --row 0    # une négociation (appelle l'API)
uv run atm eval --n 20    # banc d'éval (~0,05 $ par vol)
```

## TODO
- [x] Contraintes sourcées (sillage FAA, réserve 45 min, Part 117, couvre-feux, rotation via tail number)
- [x] Choix déterministe de la contre-proposition, solveur et retenue au sol parmi les candidats
- [x] Banc d'éval avec baselines ; statu quo réaliste (départ dès que prêt, attente en vol, porte prévue)
- [x] File d'arrivée et portes reconstituées depuis les données ; type d'avion par registre FAA
- [ ] Caler la charge de fond (70 %) sur les débits FAA ASPM par aéroport
- [ ] Proposer la retenue au sol même en cas de consensus immédiat (AA204)
- [ ] Éval de précision sur un échantillon restreint aux vols dont le vol précédent est connu
- [ ] Correspondances passagers, taxiways
- [ ] UI de démo (journal de consensus lisible)
