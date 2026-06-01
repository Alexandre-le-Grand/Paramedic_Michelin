# Paramedic Michelin

Scraping **ViaMichelin** (Edge en arriere-plan par defaut) + stockage **SQL** (SQLite) et **MongoDB**.

## Installation

```bash
pip install -r requirements.txt
python -m playwright install msedge
copy .env.example .env
docker compose up -d
```

## Utilisation

```bash
# Scraper tous les trajets de data/trajets.csv (sans fenetre)
python src/main.py run

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
