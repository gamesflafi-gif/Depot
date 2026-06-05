#!/usr/bin/env bash
# Synapse – tägliches Backup des Daten-Lakes (DuckDB + Index + Parquet).
# Off-site empfohlen: BACKUP_DIR auf eine gemountete externe Platte/Storage legen.
#
#   BACKUP_DIR=/mnt/backup bash deploy/synapse/backup.sh
#
# Konsistenz: läuft am besten nachts bei geringer Last. Für ein 100% konsistentes
# Snapshot kann der Dienst kurz gestoppt werden (siehe STOP_SERVICE=1).
set -euo pipefail

DATA_DIR="${SYNAPSE_DATA_DIR:-data/synapse}"
BACKUP_DIR="${BACKUP_DIR:-/root/synapse-backups}"
KEEP="${KEEP:-14}"                       # so viele Snapshots behalten
STOP_SERVICE="${STOP_SERVICE:-0}"        # 1 = Dienst für konsistentes Snapshot pausieren
TS="$(date +%Y%m%d-%H%M%S)"
DEST="${BACKUP_DIR}/snapshot-${TS}"

mkdir -p "$DEST"

if [[ "$STOP_SERVICE" == "1" ]]; then
  systemctl stop synapse-web 2>/dev/null || true
fi

echo "[backup] kopiere ${DATA_DIR} -> ${DEST}"
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete "${DATA_DIR}/" "${DEST}/"
else
  cp -a "${DATA_DIR}/." "${DEST}/"
fi

if [[ "$STOP_SERVICE" == "1" ]]; then
  systemctl start synapse-web 2>/dev/null || true
fi

# Prüfsumme für Integritäts-Check beim Restore
( cd "$DEST" && find . -type f -exec sha256sum {} \; > "../checksums-${TS}.txt" ) || true

echo "[backup] aufräumen: behalte die letzten ${KEEP} Snapshots"
ls -1dt "${BACKUP_DIR}"/snapshot-* 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -rf

echo "[backup] fertig: ${DEST}"
echo "[backup] WICHTIG: Restore regelmäßig testen (restore.sh) – ein ungetestetes"
echo "         Backup ist kein Backup."
