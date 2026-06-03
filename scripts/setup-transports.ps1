# Copie le dump patron (si besoin) + restaure MongoDB + affiche le nombre de trajets
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$SourceDump = "c:\Users\alexa\Documents\DEV\transports"
$TargetDump = Join-Path $Root "data\dumps\transports"

Set-Location $Root
New-Item -ItemType Directory -Force -Path (Split-Path $TargetDump) | Out-Null

if (-not (Test-Path $TargetDump)) {
    if (-not (Test-Path $SourceDump)) {
        Write-Error "Dump introuvable : $SourceDump ou $TargetDump"
    }
    Write-Host "Copie du dump vers data\dumps\transports ..."
    Copy-Item $SourceDump $TargetDump
}

& (Join-Path $Root "scripts\restore-transports.ps1")

Write-Host ""
Write-Host "Paires uniques disponibles :"
python (Join-Path $Root "scripts\count-transport-routes.py")
