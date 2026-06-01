# Paramedic Michelin — suivi des tâches

## Fait

### Projet & configuration
- [x] Structure du projet (`src/`, `config/`, `sql/`, `data/`)
- [x] `requirements.txt` (Playwright, pymongo, python-dotenv)
- [x] `docker-compose.yml` pour MongoDB
- [x] `config/settings.py` + `.env` / `.env.example`
- [x] `README.md` (installation, utilisation, dépannage)
- [x] `.gitignore` (`.env`, `trajets.db`, `browser_state.json`, `__pycache__`)

### Scraping ViaMichelin
- [x] Scraper Playwright (`src/scraper/viamichelin.py`) — source `viamichelin` uniquement
- [x] Une session navigateur pour tout le CSV (pas une fenêtre par trajet)
- [x] Remplissage départ / arrivée + validation (Entrée, boutons de secours)
- [x] Fermeture du bandeau cookies Didomi
- [x] Sauvegarde des cookies dans `data/browser_state.json`
- [x] Extraction distance (`src/extract.py`) — vmrest + texte page, filtre km ≥ 80
- [x] Prise du km maximal plausible sur la page (évite les segments partiels)
- [x] Modèle `RouteResult` (`src/models.py`)
- [x] Reconnexion automatique si la fenêtre navigateur est fermée

### Corrections & fiabilité
- [x] Fix timeout bouton « Rechercher » (calcul via Entrée + lecture page)
- [x] Mode **headless** par défaut (`BROWSER_HEADLESS=true`) — pas de fenêtre Edge
- [x] Option debug `python src/main.py run --visible`
- [x] Nettoyage code mort (OSRM, `fetch_routes`, `find_by_route`, `trajets_one.csv`, anciens `__pycache__`)

### Bases de données
- [x] SQLite `data/trajets.db` + schéma `sql/schema.sql`
- [x] `SqlRepository` — insert + `list-sql`
- [x] `MongoRepository` — insert + `raw_response` (réponse brute)
- [x] Double enregistrement à chaque run (SQL + MongoDB)

### CLI & données
- [x] `python src/main.py run` — lit `data/trajets.csv`
- [x] `python src/main.py list-sql` — affiche les derniers trajets SQL
- [x] Pause entre trajets (`SCRAPE_DELAY_SECONDS`)
- [x] **9 trajets** dans `data/trajets.csv` (4 initiaux + 5 ajoutés)

---

## À faire / améliorations possibles

- [ ] Extraire la **durée** (`duree_minutes`) de façon fiable (souvent `None` aujourd’hui)
- [ ] Commande CLI pour lister / consulter **MongoDB** (comme `list-sql`)
- [ ] Éviter les **doublons** en base si on relance `run` sur les mêmes trajets
- [ ] Tests automatisés (optionnel)
- [ ] API officielle Michelin (si le patron valide un contrat développeur)
