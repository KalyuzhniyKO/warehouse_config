# Security hardening checklist

This checklist tracks production controls that cannot be fully validated from a
developer workstation. Apply it on the server and keep the checked commands with
deployment notes.

## Django production flags

Set these values in the production `.env` after HTTPS is working:

```dotenv
DJANGO_DEBUG=False
DJANGO_ENABLE_PASSWORD_VALIDATORS=True
DJANGO_SESSION_COOKIE_SECURE=True
DJANGO_CSRF_COOKIE_SECURE=True
DJANGO_SECURE_SSL_REDIRECT=True
DJANGO_SECURE_HSTS_SECONDS=31536000
DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS=True
DJANGO_SECURE_HSTS_PRELOAD=False
DJANGO_SECURE_REFERRER_POLICY=same-origin
```

Run:

```bash
./venv/bin/python manage.py check --deploy
```

Any remaining warnings must be either fixed or explicitly documented with the
reason they are acceptable for this installation.

## HTTPS

- Terminate HTTPS in Apache.
- Redirect HTTP to HTTPS.
- Add the Django host to `DJANGO_ALLOWED_HOSTS`.
- Add the HTTPS origin to `DJANGO_CSRF_TRUSTED_ORIGINS`.
- Enable secure cookies and HSTS only after the HTTPS endpoint is reachable.

## MySQL exposure and database users

- Bind MySQL to `127.0.0.1` or another private service interface only.
- Do not use a MySQL root account in Django.
- Grant the application account access only to the warehouse database.
- Keep `.env` readable only by the service account and root.
- Create a read-only account for reports if external reporting tools are needed.
- Create a dedicated backup account with the minimum permissions required for
  dumps.

Suggested checks:

```bash
sudo ss -ltnp | grep ':3306'
sudo mysql -e "SHOW GRANTS FOR 'warehouse_user'@'localhost';"
sudo stat -c '%a %U %G %n' /opt/warehouse_config/.env
```

## Django admin data integrity

`StockBalance` and `StockMovement` are read-only in Django admin. Operators must
change stock only through service-backed warehouse operations so every change is
represented by a movement and audit entry.

`AuditLog` is append-only from the UI/admin: add, edit, and delete permissions
are disabled in Django admin.

## AuditLog coverage

The application records:

- successful login, logout, and failed login;
- user creation, user update, and password change from the management UI;
- warehouse access changes;
- stock movement creation and cancellation.

Purchase request actions should continue to use service/view-level audit entries
when workflows are expanded.

## Backup and restore

- Keep the daily backup timer enabled.
- Restrict `/var/backups/warehouse_config` to root and the backup account.
- Test restore to a non-production database after backup changes.
- Consider a 6-hour timer if the warehouse is active enough that RPO 24h is too
  large.
- Consider encrypting backup archives before copying them off the server.

Suggested checks:

```bash
systemctl list-timers 'warehouse-backup*'
sudo systemctl status warehouse-backup.timer
sudo ls -ld /var/backups/warehouse_config
```

## systemd hardening

Add or verify the following controls in the Gunicorn service:

```ini
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=/opt/warehouse_config /var/log/warehouse_config /var/backups/warehouse_config
```

Use `ProtectSystem=strict` only after confirming all runtime write paths are
listed in `ReadWritePaths`.
