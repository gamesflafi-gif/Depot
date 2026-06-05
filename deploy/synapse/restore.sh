#!/usr/bin/env bash
# Synapse – Restore aus einem Backup-Snapshot.
#   bash deploy/synapse/restore.sh /root/synapse-backups/snapshot-20260101-030000
set -euo pipefail

SRC="${1:-}"
DATA_DIR="${SYNAPSE_DATA_DIR:-data/synapse}"
if [[ -z "$SRC" || ! -d "$SRC" ]]; then
  echo "Aufruf: bash deploy/synapse/restore.sh <snapshot-verzeichnis>"
  echo "Vorhandene Snapshots:"
  ls -1dt "${BACKUP_DIR:-/root/synapse-backups}"/snapshot-* 2>/dev/null || true
  exit 1
fi

echo "ACHTUNG: überschreibt ${DATA_DIR} mit ${SRC}."
read -r -p "Fortfahren? [j/N] " a
[[ "$a" == "j" || "$a" == "J" ]] || { echo "Abgebrochen."; exit 0; }

systemctl stop synapse-web 2>/dev/null || true
mkdir -p "$DATA_DIR"
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete "${SRC}/" "${DATA_DIR}/"
else
  rm -rf "${DATA_DIR:?}/"* && cp -a "${SRC}/." "${DATA_DIR}/"
fi
systemctl start synapse-web 2>/dev/null || true

echo "Restore abgeschlossen. Prüfe: python -m synapse.cli stats"
