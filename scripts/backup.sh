#!/usr/bin/env bash
# AMATS Daily State Backup Script
set -e

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_DIR="backups"
ARCHIVE_NAME="${BACKUP_DIR}/amats_backup_${TIMESTAMP}.tar.gz"

mkdir -p "$BACKUP_DIR"

echo "Creating AMATS backup: $ARCHIVE_NAME"
tar -czf "$ARCHIVE_NAME" data/ models/ logs/ config.yaml

# Clean up backups older than 14 days
find "$BACKUP_DIR" -type f -name "amats_backup_*.tar.gz" -mtime +14 -delete
echo "Backup complete."
