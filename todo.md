# Paramedic Michelin — suivi des tâches



Dernière revue : état du dépôt (code, scripts, README, config).



---



## Fait



### Projet & configuration

- [x] Structure (`src/`, `config/`, `sql/`, `data/`, `scripts/`)

- [x] `requirements.txt` — Playwright, pymongo, python-dotenv

- [x] `docker-compose.yml` — MongoDB **8** (`mongo:8`), port `27017`, volume `data/dumps` monté en lecture

- [x] `config/settings.py` + `.env` / `.env.example` (SQLite, deux bases Mongo, source trajets, délais, navigateur)

- [x] `README.md` + `data/dumps/README.md` (installation, restauration dump ~356k transports)

- [x] `.gitignore` — `.env`, `.venv/`, `trajets.db`, `browser_state.json`, `data/dumps/`

- [x] Lanceurs **`run.cmd`** / **`run.ps1`** — Python du `.venv` sans activation manuelle



### Données d’entrée (patron + test)

- [x] Dump patron `paramedic.transports` — restauration via `scripts/restore-transports.ps1` / `.sh`

- [x] `scripts/setup-transports.ps1` — setup + comptage des paires (`count-transport-routes.py`)

- [x] `TransportsRepository` — lecture `departure.city` / `arrival.city`, agrégation paires uniques

- [x] **Déduplication aller-retour** — Paris↔Bordeaux = un seul trajet (`src/route_pairs.py` + Mongo `$min`/`$max`)

- [x] CSV de test `data/trajets.csv` (9 lignes ; doublons sens inverse ignorés au chargement)

- [x] Source par défaut : `TRAJETS_SOURCE=transports` (configurable : `csv`)



### Calcul ViaMichelin (km + minutes)

- [x] **Mode rapide par défaut** — sans navigateur (`src/scraper/viamichelin_api.py`)

  - Géocodage GraphQL (`bff.viamichelin.com`) + itinéraire **vmrest** (`iti.json`)

  - Template `data/viamichelin_search_address.json`

- [x] **Mode secours** — Playwright Edge (`--visible`) : cookies `data/browser_state.json`, capture vmrest sur la page

- [x] Façade `ViaMichelinScraper` — API ou navigateur selon `use_browser`

- [x] Extraction `src/extract.py` — `totalDist` / `totalTime` (JSON vmrest `summaryList`) + repli page
- [x] Itinéraires **sans péages** par défaut — `avoidTolls=true` ; option CLI `--avec-peages`

- [x] Filtre distance plausible `0,5`–`2000` km (plus de seuil fixe à 80 km)

- [x] Modèle `RouteResult` + statut `ok` / `erreur` + `raw_response` (Mongo)

- [x] Pause entre trajets (`SCRAPE_DELAY_SECONDS`)
- [x] **Parallèle API** — `SCRAPE_WORKERS` / `--workers` (1–10, défaut 5) + `scripts/bench_workers.py`



### Stockage des résultats

- [x] SQLite `data/trajets.db` — schéma `sql/schema.sql`, index `(depart, arrivee)`

- [x] `SqlRepository` — insert + `list-sql`

- [x] MongoDB résultats — base `paramedic_michelin`, collection `trajets` (`MongoRepository`, index départ/arrivée + date)

- [x] Double enregistrement à chaque `run` (SQL + Mongo)



### CLI

- [x] `run` — `--source transports|csv`, `--limit N`, `--visible`, `--csv`

- [x] `list-sql` — derniers trajets SQLite

- [x] Messages d’aide si Mongo vide ou venv absent



### Scripts utilitaires

- [x] `scripts/test_vmrest.py` — test vmrest / coords

- [x] `scripts/count-transport-routes.py` — nombre de paires uniques (sans aller-retour)



---



## À faire / améliorations



### Priorité métier (scraping & données)

- [x] **Reprise intelligente** — ne pas re-scraper un couple déjà en SQL/Mongo (même sens) ; `run --force` pour forcer

- [ ] **Réutiliser l’inverse** — si A→B existe, remplir B→A avec les mêmes km/min sans appel ViaMichelin

- [ ] Valider la **durée** (`duree_minutes`) sur un lot réel (souvent remplie via vmrest)

- [ ] Géocodage plus robuste (homonymes, « ville, France » implicite, échecs GraphQL)



### CLI & bases

- [ ] Commande **`list-mongo`** (équivalent `list-sql` pour `paramedic_michelin.trajets`)

- [x] Reprise par defaut au `run` ; option **`run --force`** pour re-scraper

- [ ] Exposer `raw_response` ou un résumé en SQL (optionnel, aujourd’hui Mongo seulement)



### Projet & qualité

- [x] Nettoyage artefacts debug (`debug_graphql_*.json`, `debug_body.txt`, `debug_page_body.txt`) + script `debug-viamichelin.py` supprimé ; `debug_gql_request.txt` conservé (template GraphQL)

- [ ] Rendre **`setup-transports.ps1`** portable (chemin en dur `c:\Users\alexa\Documents\DEV\transports`)

- [ ] Aligner **README** (table fichiers : `viamichelin_api.py`, `transports_repository.py`, `route_pairs.py`)

- [ ] Tests automatisés (dedupe, extract, mock vmrest) — optionnel



---



## Référence rapide



| Commande | Effet |

|----------|--------|

| `.\run.cmd run --limit 10` | 10 paires depuis `paramedic.transports` (API) |

| `.\run.cmd run` | Toutes les paires uniques (aller-retour fusionnés) |

| `.\run.cmd run --source csv` | `data/trajets.csv` |

| `.\run.cmd run --visible` | Navigateur Edge (lent) |

| `.\run.cmd list-sql` | Derniers enregistrements SQLite |

| `.\scripts\setup-transports.ps1` | Docker + restore dump + comptage |



**Bases MongoDB**



| Base | Collection | Rôle |

|------|------------|------|

| `paramedic` | `transports` | Entrée (dump patron, lecture seule) |

| `paramedic_michelin` | `trajets` | Sortie scraping (km, min, statut) |


