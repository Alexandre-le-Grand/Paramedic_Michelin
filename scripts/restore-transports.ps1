# Restaure le dump MongoDB du patron (base paramedic.*)
# Prerequis : docker compose up -d

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Archive = Join-Path $Root "data\dumps\transports"

if (-not (Test-Path $Archive)) {
    Write-Error "Archive introuvable : $Archive"
}

Set-Location $Root
docker compose up -d mongodb | Out-Null

$container = (docker compose ps -q mongodb).Trim()
if (-not $container) {
    Write-Error "Conteneur MongoDB introuvable. Lancez : docker compose up -d"
}

Write-Host "Restauration depuis $Archive ..."
docker exec $container mongorestore --gzip --archive=/dumps/transports --nsInclude="paramedic.*"

Write-Host "Termine. Base restaurée : paramedic (collections paramedic.*)"
Write-Host "Verif : docker exec $container mongosh --eval ""db.getSiblingDB('paramedic').getCollectionNames()"""
