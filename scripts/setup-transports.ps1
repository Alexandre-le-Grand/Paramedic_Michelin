# Docker + restauration du dump patron + comptage des paires
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Py = Join-Path $Root ".venv\Scripts\python.exe"

Set-Location $Root

if (-not (Test-Path $Py)) {
    Write-Error "venv absent. Executez : python -m venv .venv ; .venv\Scripts\pip install -r requirements.txt"
}

& (Join-Path $Root "scripts\restore-transports.ps1")

Write-Host ""
Write-Host "Statistiques des paires :"
& $Py (Join-Path $Root "scripts\count_transports_pairs.py")
