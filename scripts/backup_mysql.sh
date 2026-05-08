#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="/opt/warehouse_config/.env"
BACKUP_DIR="/var/backups/warehouse_config"
LOG_DIR="/var/log/warehouse_config"
LOG_FILE="${LOG_DIR}/backup.log"
RETENTION_DAYS=30

log() {
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "${LOG_FILE}"
}

fail() {
    log "ERROR: $*"
    exit 1
}

mkdir -p "${LOG_DIR}" "${BACKUP_DIR}"
touch "${LOG_FILE}"
trap 'status=$?; log "ERROR: MySQL backup failed with exit code ${status}"' ERR

if [[ ! -f "${ENV_FILE}" ]]; then
    fail "Environment file ${ENV_FILE} does not exist"
fi

set -a
# shellcheck source=/dev/null
source "${ENV_FILE}"
set +a

: "${DB_HOST:=localhost}"
: "${DB_PORT:=3306}"
: "${DB_PASSWORD:=}"

if [[ -z "${DB_NAME:-}" ]]; then
    fail "DB_NAME is required in ${ENV_FILE}"
fi

if [[ -z "${DB_USER:-}" ]]; then
    fail "DB_USER is required in ${ENV_FILE}"
fi

if ! command -v mysqldump >/dev/null 2>&1; then
    fail "mysqldump is not installed or is not available in PATH"
fi

if ! command -v gzip >/dev/null 2>&1; then
    fail "gzip is not installed or is not available in PATH"
fi

TIMESTAMP="$(date '+%Y-%m-%d_%H-%M-%S')"
BACKUP_FILE="${BACKUP_DIR}/warehouse_db_${TIMESTAMP}.sql.gz"

log "Starting MySQL backup for database ${DB_NAME} to ${BACKUP_FILE}"

MYSQL_PWD="${DB_PASSWORD}" mysqldump \
    --host="${DB_HOST}" \
    --port="${DB_PORT}" \
    --user="${DB_USER}" \
    --single-transaction \
    --routines \
    --triggers \
    --events \
    --default-character-set=utf8mb4 \
    "${DB_NAME}" | gzip > "${BACKUP_FILE}"

if [[ ! -s "${BACKUP_FILE}" ]]; then
    rm -f "${BACKUP_FILE}"
    fail "Backup file was not created or is empty: ${BACKUP_FILE}"
fi

log "Backup created successfully: ${BACKUP_FILE} ($(du -h "${BACKUP_FILE}" | awk '{print $1}'))"

find "${BACKUP_DIR}" -type f -name 'warehouse_db_*.sql.gz' -mtime +"${RETENTION_DAYS}" -print -delete | while read -r deleted_file; do
    log "Deleted old backup: ${deleted_file}"
done

log "MySQL backup finished successfully"
