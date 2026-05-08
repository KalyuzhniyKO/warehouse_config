# Backup and restore for warehouse_config

This document describes production MySQL backup and restore for the `warehouse_config` Django project.

## Storage locations and policy

- Backup directory: `/var/backups/warehouse_config`
- Backup log: `/var/log/warehouse_config/backup.log`
- Backup file name format: `warehouse_db_YYYY-MM-DD_HH-MM-SS.sql.gz`
- Retention: 30 days
- RPO: 24 hours
- RTO: 4 hours
- Backups are runtime artifacts and must not be stored in git. The repository `.gitignore` excludes `.env`, logs, `.sql`, `.sql.gz`, `db.sqlite3`, and `staticfiles/`.

## Required directories and permissions

Create the runtime directories before running production services:

```bash
sudo mkdir -p /var/log/warehouse_config
sudo mkdir -p /var/backups/warehouse_config
sudo chown -R warehouse:www-data /var/log/warehouse_config
sudo chown -R warehouse:www-data /var/backups/warehouse_config
sudo chmod 750 /var/log/warehouse_config
sudo chmod 750 /var/backups/warehouse_config
```

The backup script reads database credentials from `/opt/warehouse_config/.env`. At minimum it requires `DB_NAME` and `DB_USER`; it also uses `DB_PASSWORD`, `DB_HOST`, and `DB_PORT`.

## Manual backup

Run a backup manually from the deployed project:

```bash
cd /opt/warehouse_config
sudo -u warehouse /opt/warehouse_config/scripts/backup_mysql.sh
```

Check the backup log:

```bash
sudo tail -n 100 /var/log/warehouse_config/backup.log
```

## Install and verify the systemd timer

Install the example service and timer:

```bash
sudo cp /opt/warehouse_config/docs/warehouse-backup.service.example /etc/systemd/system/warehouse-backup.service
sudo cp /opt/warehouse_config/docs/warehouse-backup.timer.example /etc/systemd/system/warehouse-backup.timer
sudo systemctl daemon-reload
sudo systemctl enable --now warehouse-backup.timer
```

Verify the timer:

```bash
sudo systemctl status warehouse-backup.timer
sudo systemctl list-timers | grep warehouse
systemctl cat warehouse-backup.service
systemctl cat warehouse-backup.timer
```

Run the service immediately for a smoke test:

```bash
sudo systemctl start warehouse-backup.service
sudo systemctl status warehouse-backup.service
sudo tail -n 100 /var/log/warehouse_config/backup.log
```

## View recent backups

List the most recent backups:

```bash
sudo find /var/backups/warehouse_config -maxdepth 1 -type f -name 'warehouse_db_*.sql.gz' -printf '%TY-%Tm-%Td %TH:%TM %s %p\n' | sort -r | head -n 20
```

Check one backup file before restore:

```bash
gzip -t /var/backups/warehouse_config/warehouse_db_YYYY-MM-DD_HH-MM-SS.sql.gz
```

## Restore production database from `.sql.gz`

> Warning: restoring into the production database overwrites current data. Confirm the backup file, maintenance window, and target database before running these commands.

1. Stop application traffic:

```bash
sudo systemctl stop warehouse-gunicorn
```

2. Optional but recommended: create an emergency backup before restore:

```bash
sudo -u warehouse /opt/warehouse_config/scripts/backup_mysql.sh
```

3. Load environment variables:

```bash
set -a
source /opt/warehouse_config/.env
set +a
```

4. Restore the selected backup:

```bash
gunzip -c /var/backups/warehouse_config/warehouse_db_YYYY-MM-DD_HH-MM-SS.sql.gz | \
  MYSQL_PWD="$DB_PASSWORD" mysql \
    --host="${DB_HOST:-localhost}" \
    --port="${DB_PORT:-3306}" \
    --user="$DB_USER" \
    --default-character-set=utf8mb4 \
    "$DB_NAME"
```

5. Run Django checks and migrations, then start the app:

```bash
cd /opt/warehouse_config
sudo -u warehouse /opt/warehouse_config/venv/bin/python manage.py check
sudo -u warehouse /opt/warehouse_config/venv/bin/python manage.py migrate
sudo systemctl start warehouse-gunicorn
sudo systemctl status warehouse-gunicorn
```

## Verify restore on a test database

Use a separate test database first whenever possible:

```bash
mysql -u root -p -e "CREATE DATABASE warehouse_restore_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
gunzip -c /var/backups/warehouse_config/warehouse_db_YYYY-MM-DD_HH-MM-SS.sql.gz | \
  MYSQL_PWD="$DB_PASSWORD" mysql \
    --host="${DB_HOST:-localhost}" \
    --port="${DB_PORT:-3306}" \
    --user="$DB_USER" \
    --default-character-set=utf8mb4 \
    warehouse_restore_test
mysql -u root -p -e "SHOW TABLES FROM warehouse_restore_test;"
```

To test Django against that restored database, temporarily copy `/opt/warehouse_config/.env` to a safe test-only environment file, set `DB_NAME=warehouse_restore_test`, and run:

```bash
cd /opt/warehouse_config
sudo -u warehouse env DJANGO_DEBUG=False DB_NAME=warehouse_restore_test /opt/warehouse_config/venv/bin/python manage.py check
```

Drop the test database after validation if it is no longer needed:

```bash
mysql -u root -p -e "DROP DATABASE warehouse_restore_test;"
```
