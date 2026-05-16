#!/usr/bin/env bash
#
# Munwan Car Rental — nightly database backup
#
# Dumps the Postgres database from the running `db` container, compresses
# it, keeps the most recent 14 days locally, and uploads each backup to
# Backblaze B2 (off-server copy). Old backups are pruned both locally and
# on B2.
#
# ── PREREQUISITES ─────────────────────────────────────────────────
#   1. rclone installed:        sudo apt install -y rclone
#   2. rclone remote 'b2' set:  rclone config   (B2 application key)
#   3. Verify it works:         rclone lsd b2:
#      ^ this MUST list your bucket before the script will upload.
#
# ── INSTALL ───────────────────────────────────────────────────────
#   1. Place at /opt/munwan/scripts/backup-db.sh
#   2. chmod +x /opt/munwan/scripts/backup-db.sh
#   3. Test:  ./scripts/backup-db.sh
#   4. Cron:  crontab -e  then add:
#      15 3 * * * /opt/munwan/scripts/backup-db.sh >> /opt/munwan/backups/backup.log 2>&1
#
# ── RESTORE (when you ever need it) ───────────────────────────────
#   Download:  rclone copy b2:munwan-db-backups/munwan-db-YYYY-MM-DD-HHMM.sql.gz /tmp/
#   Restore :  gunzip -c /tmp/munwan-db-YYYY-MM-DD-HHMM.sql.gz \
#                | docker compose exec -T db psql -U munwan -d munwan
#   (Test restores on a SCRATCH database, never straight onto production.)
#
set -euo pipefail

# ── Config ────────────────────────────────────────────────────────
COMPOSE_DIR="/opt/munwan"
BACKUP_DIR="${COMPOSE_DIR}/backups"
DB_SERVICE="db"
DB_USER="munwan"
DB_NAME="munwan"
RETENTION_DAYS=14

# Backblaze B2 — rclone remote name and bucket.
# 'b2' is the remote created via `rclone config`.
B2_REMOTE="b2"
B2_BUCKET="munwan-db-backups"

# ── Run ───────────────────────────────────────────────────────────
cd "$COMPOSE_DIR"
mkdir -p "$BACKUP_DIR"

TIMESTAMP="$(date +%Y-%m-%d-%H%M)"
OUTFILE="${BACKUP_DIR}/munwan-db-${TIMESTAMP}.sql.gz"

echo "============================================================"
echo "[$(date)] Starting backup -> ${OUTFILE}"

# ── 1. Dump the database ──────────────────────────────────────────
# pg_dump inside the db container, piped straight to gzip on the host.
# --clean --if-exists makes the dump safe to restore over an existing DB.
if docker compose exec -T "$DB_SERVICE" \
     pg_dump --clean --if-exists -U "$DB_USER" "$DB_NAME" | gzip > "$OUTFILE"; then
  SIZE="$(du -h "$OUTFILE" | cut -f1)"
  echo "[$(date)] Database dump OK — ${SIZE}"
else
  echo "[$(date)] DATABASE DUMP FAILED" >&2
  # Remove the (likely empty/partial) file so it isn't mistaken for good
  rm -f "$OUTFILE"
  exit 1
fi

# Sanity check: a real backup should be more than a few hundred bytes.
# An almost-empty file usually means pg_dump errored silently.
MIN_BYTES=500
ACTUAL_BYTES="$(stat -c%s "$OUTFILE" 2>/dev/null || echo 0)"
if [ "$ACTUAL_BYTES" -lt "$MIN_BYTES" ]; then
  echo "[$(date)] WARNING: backup file is only ${ACTUAL_BYTES} bytes — looks empty/broken" >&2
  rm -f "$OUTFILE"
  exit 1
fi

# ── 2. Upload to Backblaze B2 (off-server copy) ───────────────────
# A backup on the same server protects against nothing — if the disk
# dies, both DB and backup die together. B2 is the real safety net.
if command -v rclone >/dev/null 2>&1; then
  echo "[$(date)] Uploading to B2 (${B2_REMOTE}:${B2_BUCKET})..."
  if rclone copy "$OUTFILE" "${B2_REMOTE}:${B2_BUCKET}/" --no-traverse; then
    echo "[$(date)] B2 upload OK"
  else
    # Don't exit non-zero here — the local backup still succeeded, and we
    # want the script to continue to pruning. But make the failure LOUD
    # in the log so a missed off-server copy gets noticed.
    echo "[$(date)] !! B2 UPLOAD FAILED — local backup exists but is NOT off-server !!" >&2
  fi
else
  echo "[$(date)] !! rclone not installed — backup is LOCAL ONLY, not safe !!" >&2
fi

# ── 3. Prune old LOCAL backups ────────────────────────────────────
DELETED_LOCAL="$(find "$BACKUP_DIR" -name 'munwan-db-*.sql.gz' -mtime "+${RETENTION_DAYS}" -print -delete | wc -l)"
if [ "$DELETED_LOCAL" -gt 0 ]; then
  echo "[$(date)] Pruned ${DELETED_LOCAL} local backup(s) older than ${RETENTION_DAYS} days"
fi

# ── 4. Prune old B2 backups ───────────────────────────────────────
# Keeps B2 storage small so you stay well inside the free tier.
if command -v rclone >/dev/null 2>&1; then
  if rclone delete "${B2_REMOTE}:${B2_BUCKET}/" --min-age "${RETENTION_DAYS}d" 2>/dev/null; then
    echo "[$(date)] Pruned B2 backups older than ${RETENTION_DAYS} days"
  fi
fi

# ── 5. Summary ────────────────────────────────────────────────────
echo "[$(date)] Done."
echo "Local backups in ${BACKUP_DIR}:"
ls -lh "$BACKUP_DIR"/munwan-db-*.sql.gz 2>/dev/null | tail -n 5 || echo "  (none)"
echo "============================================================"