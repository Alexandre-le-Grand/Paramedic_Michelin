# Paramedic Michelin

Calcul de distances routieres **ViaMichelin** (API GraphQL) avec stockage **MongoDB** (et SQLite optionnel).

## Structure du projet

```
Paramedic_Michelin/
├── config/
│   ├── settings.py          # Variables d'environnement
│   └── graphql/             # Templates requetes ViaMichelin
├── data/
│   ├── dumps/               # Dump patron (non versionne, ~100 Mo)
│   └── samples/trajets.csv  # CSV de test (9 lignes)
├── scripts/
│   ├── restore-transports.ps1 / .sh
│   ├── setup-transports.ps1
│   ├── count_transports_pairs.py
│   ├── inspect_paris_marseille.py
│   └── probe_viamichelin.py
├── sql/schema.sql
├── src/
│   ├── main.py              # CLI (run.cmd)
│   ├── db/                  # Mongo, SQL, transports patron
│   └── scraper/             # ViaMichelin, OSRM, navigateur
├── docker-compose.yml
└── run.cmd
```

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
python -m playwright install msedge
copy .env.example .env
docker compose up -d
```

Placer le dump patron dans `data/dumps/transports` (voir `data/dumps/README.md`).

```powershell
.\scripts\setup-transports.ps1
```

## Workflow MongoDB

```powershell
.\run.cmd seed-mongo                    # Inscrire les paires (expansion Paris/Marseille)
.\run.cmd run --source mongo            # Calculer les km (affichage detaille par defaut)
.\run.cmd run --source mongo --quiet    # Une ligne par trajet
.\run.cmd run --source mongo --workers 3
.\run.cmd list-mongo
```

## Autres commandes

```powershell
.\run.cmd run --source csv              # data/samples/trajets.csv
.\run.cmd run --source mongo --osrm     # Secours OSRM si API saturee
.\run.cmd run --source mongo --browser  # Secours navigateur
.\run.cmd test Paris Lyon               # Test sans ecriture en base
.\run.cmd patch-departments
.\run.cmd clean-bad-mongo
.\.venv\Scripts\python.exe scripts\count_transports_pairs.py
.\.venv\Scripts\python.exe scripts\probe_viamichelin.py
```

## Bases MongoDB

| Base | Collection | Role |
|------|------------|------|
| `paramedic` | `transports` | Donnees patron (dump, lecture seule) |
| `paramedic_michelin` | `trajets` | Resultats km / statut pending / ok |

## Depannage

- **Edge introuvable** : `python -m playwright install msedge`
- **Cookies navigateur** : supprimer `data/browser_state.json`
- **API 503** : relancer plus tard ou `.\run.cmd run --source mongo --osrm`
- **ViaMichelin down** : `.\run.cmd monitor`
