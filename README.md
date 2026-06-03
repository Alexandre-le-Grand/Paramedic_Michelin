# Paramedic Michelin

Calcul d'itineraires **ViaMichelin** (API GraphQL + vmrest, rapide) + stockage **SQL** (SQLite) et **MongoDB**.

## Installation

```bash
pip install -r requirements.txt
python -m playwright install msedge
copy .env.example .env
docker compose up -d
```

MongoDB **8** (`mongo:8` dans `docker-compose.yml`).

### Base MongoDB du patron (`paramedic.transports`)

Le dump est dans `data/dumps/transports` (copie de l’archive fournie).

```powershell
# Restauration (une fois, ou après reset du volume Docker)
.\scripts\restore-transports.ps1

# Ou à la main :
docker compose exec mongodb mongorestore --gzip --archive=/dumps/transports --nsInclude="paramedic.*"
```

Voir `data/dumps/README.md` pour le détail.

## Utilisation

**Une fois** : lancer Docker Desktop, puis restaurer le dump patron :

```powershell
.\scripts\setup-transports.ps1
```

```powershell
# ViaMichelin API — trajets depuis paramedic.transports (~3 s / trajet)
.\run.cmd run --limit 10

# Tous les couples uniques
.\run.cmd run

# Petit CSV de test
.\run.cmd run --source csv

# Mode navigateur Edge (lent, secours uniquement)
.\run.cmd run --visible

# Debug : voir Edge a l'ecran
python src/main.py run --visible

# Voir les derniers resultats SQL
python src/main.py list-sql
```

Par defaut le navigateur tourne en **headless** (`BROWSER_HEADLESS=true` dans `.env`).  
En base : `source=viamichelin` si le calcul reussit.

## Fichiers

| Fichier | Role |
|---------|------|
| `data/trajets.csv` | Liste depart / arrivee |
| `src/scraper/viamichelin.py` | Scraping Playwright |
| `src/db/sql_repository.py` | SQLite |
| `src/db/mongo_repository.py` | MongoDB |
| `data/browser_state.json` | Cookies (genere, ne pas committer) |

## CSV

```csv
depart,arrivee
Paris,Lyon
```

## Depannage

- **Edge introuvable** : `python -m playwright install msedge`
- **Erreur cookies** : supprimer `data/browser_state.json` et relancer
- **Distance vide** : verifier les noms de villes, laisser Edge finir le calcul
