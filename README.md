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
workbook.py      lecture du classeur officiel du challenge (limites) et liste des écarts
rules.py         limites du classeur + règles publiées (sillage FAA, couvre-feux, Part 117 en variante)
context.py       contexte opérationnel, chaque champ avec sa provenance (DATA / ASSUMPTION / REGULATORY)
agents/          ATCAgent / PilotAgent / GroundAgent : prompt + appel Claude séparés
protocol.py      Proposal, Evaluation, ConstraintResult, Turn, Outcome (pydantic)
constraints.py   contraintes dures déterministes par domaine (pas de LLM)
negotiation.py   orchestrateur : MAX_ROUNDS=3, contrôles à chaque tour, log JSONL
fallback.py      solveur déterministe si pas de consensus
cli.py           `atm check`, `atm run --row N` (+ décision du superviseur), `atm check-proposal`
```

### Un humain décide (`atm run`)
Les agents et le solveur **proposent** ; le superviseur d'approche **décide**. Après la négociation, `atm run --row N`
affiche le plan final (retard, attente en vol, retenue au sol, piste, porte), chaque contrôle du plan final
(dur/souple, OK/échec, base REGULATORY/DATA/ASSUMPTION, source) et les réserves de chaque agent au dernier tour, puis
demande d'approuver ou de rejeter avec un motif libre. La décision (`approved` / `rejected`, motif, horodatage UTC,
`decided_by: "approach supervisor"`) est écrite dans le champ `human_decision` de la dernière ligne du log JSONL
(`null` = en attente). Si le solveur ne trouve aucun plan sûr (`final: null`), le cas n'est jamais silencieux : il est
affiché « ESCALATED: no safe option » et enregistré `escalated`, avec la consigne du superviseur.
`--auto-approve` enregistre une approbation sans question (`auto: true`, donc visible comme non humaine) ;
`atm eval` et `atm audit` restent non interactifs et laissent `human_decision` à `null`.

### Tester les règles soi-même (`atm check-proposal`)
Les vraies règles Python (`check_all`), sans LLM, sur n'importe quelle proposition : utile pour essayer de casser le
système. Le scénario vient d'une ligne DOT (`--row N`) ou d'un log (`--log logs/....jsonl`, sans relire le CSV). La
proposition part du statu quo ; le JSON sur stdin puis les options (`--delay --holding --gap --runway --gate`)
remplacent ses champs. Sortie JSON : `proposal`, `hard_ok`, `all_ok`, et chaque contrôle avec `passed`, `hard`,
`detail`, `basis`, `source`.
```bash
echo '{"holding_min": 90, "revised_arrival_delay_min": 120}' | uv run atm check-proposal --log logs/<vol>.jsonl --gate G9
```
Le viewer (`viewer/`, hors ligne, sans serveur) ne l'appelle pas encore : il faudrait un petit serveur local.

## Contraintes et provenance des valeurs
Toutes les limites opérationnelles viennent du **classeur officiel du challenge**
(`data/constraints/challenge2_operational_constraints.xlsx`, lu par `workbook.py`). Ses valeurs d'aéroport sont
**synthétiques**, mises à l'échelle du trafic de `flights.csv` (pas de vraies données d'aéroport). Chaque contrôle du log
porte `hard` (sécurité, non négociable) ou soft (coût, négociable), une `basis` et une `source`.

| Contrôle | Agent | Type | Valeur (source) |
|---|---|---|---|
| `runway_open` | ATC | hard | Pistes actives du classeur (4 grand hub → 1 non-hub) ; ligne météo → une piste fermée (hypothèse : le DOT ne dit pas où était la météo) |
| `wake_separation` | ATC | hard | Table de sillage du classeur (FAA JO 7110.65 simplifiée) : Heavy→Large 5 NM, Heavy→Small 6, Super→Large 7…, 3 NM sinon. Conversion à 140 kt (hypothèse) |
| `landing_slot_available` | ATC | hard | File « premier prêt, premier servi » des vols du fichier, espacés de max(sillage, intervalle de capacité). Capacité = `max_runway_ops_per_hour` du classeur, moitié en arrivées (hypothèse) |
| `airport_curfew` | ATC | hard | Couvre-feux SNA / LGB (hors classeur, cités) |
| `final_reserve_fuel` | Pilote | hard | Classeur : réserve finale **30 min**, carburant à l'arrivée **45 min** d'attente → **15 min** utilisables en attente (lecture prudente) |
| `departure_feasible` | Pilote | hard | L'avion ne part pas avant d'être prêt (retard connu de l'avion entrant) |
| `flight_crew_duty` | Pilote | hard | Classeur : **13 h** de service max depuis la prise de service (Part 117 simplifiée). Prise de service 1 h avant le premier départ de l'avion (hypothèse) ; Table B complète disponible en variante (`rules.CREW_DUTY_MODEL`) |
| `gate_available` | Sol | hard | Portes du classeur × part de la compagnie dans les arrivées de l'aéroport (fichier) ; les `spare_gates_at_any_time` du classeur (3 ou 2) sont des portes `SPARE` toujours libres |
| `gate_change_notice` | Sol | hard | Classeur : changement de porte décidé **≥ 20 min** avant l'arrivée |
| `crew_shift` | Sol | soft | Classeur : service au sol de **8 h**, heures sup à **1,5×** ; prises de service 06:00 / 14:00 / 22:00 (hypothèse) |
| `turnaround_next_leg` | Sol | soft | Rotation minimale du classeur à destination (45 min grand hub, 35 sinon) avant le vol suivant du même avion |

Consommation en attente pour les gains carburant : classeur, 2,4 t/h moyen-courrier, 6,5 t/h long-courrier.
Après 3 tours sans accord, le solveur décide et **le log dit pourquoi** (`fallback_reason` : qui a refusé, quelles règles
échouaient, plan retenu ou escalade).

### Écarts au classeur, à annoncer dans la démo (règle du jeu : « Any limit you change must be stated »)
1. **Rotation prévue ≠ rotation limite** : l'heure où l'avion est prêt utilise la rotation médiane observée de la
   compagnie (calibrée janv.–juin, testée juil.–déc.), **jamais en dessous** du minimum du classeur, qui reste la limite.
2. **Sillage** : la catégorie FAA B757 est conservée ; les paires du classeur sont identiques (vérifié par un test).
3. **Couvre-feux** d'aéroport ajoutés (hors classeur).
4. **Carburant** : « 45 min à l'arrivée » lu comme carburant total d'attente, donc 15 min utilisables au-dessus des
   30 min de réserve (lecture prudente ; l'autre lecture donnerait 45 min).
5. **Capacité** : la moitié des mouvements de piste par heure sont des arrivées.
6. **Équipes au sol** : services de 8 h commençant à 06:00, 14:00, 22:00.
7. **Portes de la compagnie** : portes de l'aéroport × part de la compagnie dans ses arrivées (fichier).

### Ce qui est connu au moment de décider (pas de fuite d'information)
Les minutes `WEATHER_DELAY`, `LATE_AIRCRAFT_DELAY`, `AIRLINE_DELAY`… sont **attribuées par le DOT après le vol**, et
les 5 colonnes de cause s'additionnent exactement à `ARRIVAL_DELAY` sur 100 % du fichier.

**Conformité à la consigne.** Le PDF demande de *« passer les paramètres de la ligne aux 3 agents »*. On le fait : les
minutes de cause sont dans `dot_delay_causes_min` du scénario, que les 3 agents reçoivent, avec la mention
« attribution DOT après le vol, non utilisée par les contrôles ». Les agents s'en servent pour comprendre le type de
perturbation. En revanche, **aucune partie déterministe ne les lit** : ni le créneau, ni les contrôles, ni le statu
quo, ni le solveur, ni l'audit. Un test le vérifie (gonfler ces minutes à 999 ne change aucun résultat déterministe).
Conséquence pour l'évaluation : quand on compare à la réalité une proposition **écrite par un agent**, la fuite peut
y entrer ; les comparaisons faites sur le créneau et le solveur, elles, n'en dépendent pas.

Ce que les règles utilisent à la place :
- **Retard de l'avion entrant** : vol précédent du même avion (même immatriculation) arrivé en retard + rotation
  **calibrée par compagnie** (27 min Hawaiian → 54 min United, voir « Calibration ») (40 % des lignes). Sinon `LATE_AIRCRAFT_DELAY` sert d'approximation de l'heure d'arrivée prévue de l'avion
  entrant, et c'est signalé dans le log.
- **Créneau d'atterrissage** : file d'arrivée reconstituée à partir des autres vols du fichier, espacés de
  max(sillage FAA, intervalle de capacité du classeur). Fermer une piste retire sa part de capacité.
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

## Résultats finaux — limites du classeur officiel (31/10/2026)
`atm eval --population prev_leg --n 50 --samples 3` et `atm eval --population stress --n 35 --samples 3` (seed 0,
3 échantillons disjoints par population), Opus 5.5, effort `low`. **Sans fuite** = vols dont le retard entrant vient du
vol précédent. **Sous tension** = vols où le plan non coordonné enfreint une règle ou attend en vol, repérés par les
règles seules sur un tirage aléatoire. Fourchette = min–max sur les 3 échantillons.

| Métrique | Sans fuite (3 × 50 = 150 vols) | Sous tension (3 × 35 = 105 vols) |
|---|---|---|
| Statu quo (sans coordination) qui enfreint une règle de sécurité | 10/150 (2–6 par échantillon) | 85/105 (23–33 sur 35) |
| Solutions finales sûres quand un plan sûr existe | **144/144** | **56/56** |
| Aucun plan sûr → escalade au superviseur, raison dans le log | 6/150 (0–4) | **49/105 (31–57 %)**, presque toutes : équipage > 13 h |
| Consensus des 3 agents en ≤ 3 tours | **96 %** (92–100 %), 1,07 tour | 54 % (43–69 %), 1,65 tour ; le reste = escalades |
| Acceptations d'un plan dangereux **dans le domaine de l'agent** | **0** | **0** |
| Acceptations hors domaine (voulues), rattrapées par les règles | 22 | 191 |
| Qui a écrit la solution retenue | statu quo accepté 89 % (82–96 %) | Sol 29 %, retenue au sol 21 %, Pilote 4 %, escalade 46 % |
| Attente en vol (statu quo → négocié) | 0,3 → 0 min | 0,7 → 0 min |
| Erreur du créneau prédit vs retard réel | 38,2 min (36,9–39,7) | 14,5 min (1er échantillon, lignes sans fuite) |
| Coût / latence | 6,73 $ (0,045 $/vol), ~9 s/vol | 8,97 $ (0,085 $/vol), 14 s/vol |

**Lecture honnête**
- **Sécurité : 200/200 solutions sûres, 0 acceptation dangereuse dans le domaine de l'agent** sur ces 255 vols, et
  sur plus de 450 vols vérifiés dans les logs en comptant les runs précédents.
- **Au quotidien, peu à négocier** : environ 9 vols ordinaires sur 10 gardent le plan prévu, accepté au tour 1.
- **Dans les vols sous tension, la négociation sert vraiment** sur les cas solubles : l'agent sol trouve une porte
  libre (29 % des vols), l'orchestrateur fait voter une retenue au sol (21 %), le pilote corrige (4 %).
- **Le cas d'échec dominant est l'équipage** : de 31 % à 57 % des vols sous tension n'ont aucun plan légal parce que
  l'équipage dépasserait 13 h quoi qu'on fasse. Le système ne force rien, il escalade avec la raison. La limite de 13 h
  du classeur est plus stricte que la Table B Part 117 le matin (14 h) : le taux dépend de cette règle simplifiée.
- **Variabilité** : d'un échantillon à l'autre, le consensus sous tension varie de 43 à 69 % et les escalades de
  31 à 57 %. Les garanties de sécurité, elles, ne varient pas : elles viennent des règles.
- Limites : limites d'aéroport synthétiques du classeur, LLM non déterministe, 3 échantillons seulement.

## Résultats d'évaluation — run du 31/10/2026 (`atm eval --n 20 --seed 0`), modèle v2 (avant le classeur officiel)
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

## Audit du statu quo sur 10 000 vols — règles seules, sans LLM (`atm audit --n 10000`)
Tirage aléatoire de 10 000 vols perturbés (seed 0), ~1 min, 0 $. Pour chaque vol : le plan sans coordination (partir
dès que prêt, attendre en vol le créneau, garder la porte prévue) enfreint-il une règle *hard* ? Intervalles de
confiance à 95 % (Wilson). **Limites du classeur officiel.**

| Mesure | Classeur (actuel) | Avant le classeur (4 portes/compagnie, 70 % de charge, réserve 45 min, Part 117) |
|---|---|---|
| Plan sans coordination qui enfreint une règle de sécurité | **5,1 %** [4,7–5,6] | 18,1 % |
| dont porte occupée | 2,6 % [2,3–3,0] | 15,7 % |
| dont temps de service équipage (13 h) dépassé | **2,5 %** [2,2–2,9] | 2,7 % |
| dont réserve carburant entamée | 0,1 % | 0,5 % |
| Aucun plan sûr, escalade vers un humain | 2,6 % [2,3–2,9] | 3,4 % |
| Vols avec attente en vol | 1,6 % (médiane 3 min) | 4,2 % |
| Carburant économisé par le solveur | 2 kg/vol en moyenne, médiane 0 | 16 kg/vol |

**Lecture honnête**
- Avec les limites officielles, **environ 1 vol perturbé sur 20** a un plan non coordonné illégal : moitié équipage
  (13 h dépassées), moitié porte occupée. Les conflits de porte ne sont plus concentrés sur les hubs (ATL 5,7 %,
  DFW 7,3 %, ORD 6,4 %) : avec 150 portes, l'hypothèse « 4 portes par compagnie » les gonflait.
- **2,6 % des vols n'ont aucun plan sûr** (presque tous : l'équipage dépasserait 13 h quoi qu'on fasse) : ils
  remontent au superviseur avec la raison. C'est le résultat le plus solide pour le pitch.
- **L'attente en vol n'est pas le problème** sur ces données (1,6 % des vols, quelques minutes) : la valeur est dans
  les portes et l'équipage, pas le carburant.
- La variante `--planned-gate random` n'est plus une sensibilité valable : elle tire la porte prévue parmi les portes
  montrées à l'agent, qui sont surtout les portes occupées (12,5 %, surestimé).

## Calibration des prédictions (`atm calibrate`, sans LLM)
Ajustement sur **janvier–juin 2015**, test sur **juillet–décembre** (séparation dans le temps), uniquement sur les
lignes dont le retard entrant vient du vol précédent (pas de fuite) : 83 171 lignes d'ajustement, 60 542 de test.

| Modèle (sur les mois de test) | Erreur retard départ | Biais départ | Erreur retard arrivée | Arrivée à ±15 min |
|---|---|---|---|---|
| M0 rotation fixe 35 min (avant) | 16,7 min | −12,2 | 18,8 min | 62,8 % |
| **M1 rotation par compagnie (adopté)** | **14,0 min (−16 %)** | **−7,6** | 18,5 min | 61,9 % |
| M2 = M1 + retard résiduel historique compagnie × aéroport × heure | 13,3 min | −6,4 | 18,3 min | 60,7 % |
| M3 = M2 + médiane historique côté arrivée | 13,3 min | −6,4 | 17,8 min | 65,1 % |

- **Rotation par compagnie** = médiane du temps entre l'atterrissage de l'avion entrant et notre départ réel, quand
  le départ attend l'avion (`LATE_AIRCRAFT_DELAY > 0`) : de 27 min (HA) à 54 min (UA). Utilisée pour l'heure où
  l'avion est prêt, l'occupation des portes et le contrôle de rotation. Valeurs figées dans `calibration.py`, un test
  vérifie qu'elles correspondent à un nouvel ajustement.
- **M2 / M3 mesurés, pas adoptés** : gains faibles (−0,7 min au départ, −0,7 min à l'arrivée) pour un modèle moins
  explicable, fait de moyennes historiques.
- **Ce qui reste imprévisible avant le départ** : en moyenne 14,6 min de retard au départ ne viennent pas de l'avion
  entrant (compagnie, système, météo au départ). Côté arrivée, la marge de l'horaire absorbe la file (−3 min en
  moyenne), donc la charge de fond à 70 % **ne peut pas être calibrée avec ces données** : il faudrait les débits FAA ASPM.
- L'éval LLM tire des vols sur toute l'année, y compris les mois d'ajustement : 14 valeurs de rotation seulement, le
  risque de sur-ajustement est faible, mais il existe.

## Démarrage
```bash
cp .env.example .env      # puis mettre ANTHROPIC_API_KEY
uv run atm check          # vérifie la clé API et les données
uv run pytest             # tests hors ligne (agents factices, aucun coût)
uv run atm run --row 0    # une négociation (appelle l'API), puis approbation du superviseur (--auto-approve sinon)
uv run atm check-proposal --row 0 --delay 40 --holding 30   # contrôles déterministes en JSON, 0 $
uv run atm eval --n 20    # banc d'éval (~0,05 $ par vol)
uv run atm audit --n 10000   # audit du statu quo (limites du classeur), sans LLM, 0 $
uv run atm calibrate      # recalibre la rotation et compare les modèles de prédiction, 0 $
```

## TODO
- [x] Contraintes sourcées (sillage FAA, couvre-feux, rotation via tail number)
- [x] Choix déterministe de la contre-proposition, solveur et retenue au sol parmi les candidats
- [x] Banc d'éval avec baselines ; statu quo réaliste (départ dès que prêt, attente en vol, porte prévue)
- [x] File d'arrivée et portes reconstituées depuis les données ; type d'avion par registre FAA
- [x] Limites du classeur officiel (pistes, capacité, portes, carburant, équipage, préavis de porte)
- [ ] Proposer la retenue au sol même en cas de consensus immédiat (AA204)
- [ ] Éval de précision sur un échantillon restreint aux vols dont le vol précédent est connu
- [ ] Correspondances passagers, taxiways
- [ ] UI de démo (journal de consensus lisible)
