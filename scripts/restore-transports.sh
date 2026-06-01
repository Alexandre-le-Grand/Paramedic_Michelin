#!/usr/bin/env bash
# Restaure le dump MongoDB du patron (base paramedic.*)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ARCHIVE="$ROOT/data/dumps/transports"

if [[ ! -f "$ARCHIVE" ]]; then
  echo "Archive introuvable : $ARCHIVE" >&2
  exit 1
fi

cd "$ROOT"
docker compose up -d mongodb
CONTAINER="$(docker compose ps -q mongodb)"
echo "Restauration depuis $ARCHIVE ..."
docker exec "$CONTAINER" mongorestore --gzip --archive=/dumps/transports --nsInclude="paramedic.*"
echo "Termine. Verif : docker exec $CONTAINER mongosh --eval \"db.getSiblingDB('paramedic').getCollectionNames()\""
