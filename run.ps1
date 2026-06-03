# Lance le scraper avec le Python du projet (pas besoin d'activer le venv)
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    Write-Error "Environnement absent. Lancez : python -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt"
}
& $Python (Join-Path $Root "src\main.py") @args
