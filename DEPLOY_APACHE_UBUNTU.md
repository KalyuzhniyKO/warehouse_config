# Deploy warehouse_config on Ubuntu Server with Apache2, Gunicorn, and systemd

This guide deploys the Django warehouse system on Ubuntu `server01` with the production request flow:

```text
Apache reverse proxy -> Gunicorn managed by systemd -> Django -> MySQL
```

`python manage.py runserver 0.0.0.0:8000` is only a temporary test command. It is not a production application server. After Gunicorn/systemd is configured, stop any old `runserver` process and keep the application running through `warehouse-gunicorn.service`.

The examples use these server values:

- Project path: `/opt/warehouse_config`
- Runtime user: `warehouse`
- Sudo/admin user: `ilovewindows`
- Virtual environment: `/opt/warehouse_config/venv`
- Database: MySQL `warehouse_db`
- Gunicorn bind: `127.0.0.1:8001`
- Apache VirtualHost port: `8081`
- LAN URLs: `http://10.52.83.10/` and `http://100.111.213.115/`

The Apache example keeps the application on port `8081` so existing Apache sites can continue to use their current ports. If this warehouse site should be the only site on port `80`, change the VirtualHost/listen port consistently and update `.env` CSRF origins to match the real browser URL.

## 1. Install required OS packages

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip apache2 gettext
sudo a2enmod proxy proxy_http headers
```

The Python dependency list uses `PyMySQL`, so `mysqlclient` is not required. For packages that need MySQL headers later, install the development packages too:

```bash
sudo apt install pkg-config default-libmysqlclient-dev build-essential
```

## 2. Create the service user and project directory

Create the runtime user if it does not already exist:

```bash
id warehouse || sudo adduser --system --group --home /opt/warehouse_config warehouse
```

Create `/opt/warehouse_config`, clone or copy the repository there, and make the runtime user own it:

```bash
sudo mkdir -p /opt/warehouse_config
sudo chown warehouse:www-data /opt/warehouse_config
cd /opt/warehouse_config
# Example: sudo -u warehouse git clone <repo-url> /opt/warehouse_config
sudo chown -R warehouse:www-data /opt/warehouse_config
```

Create the Django/Gunicorn log directory required by the default production settings:

```bash
sudo mkdir -p /var/log/warehouse_config
sudo chown -R warehouse:www-data /var/log/warehouse_config
sudo chmod 750 /var/log/warehouse_config
```

Optional backup directory for the documented MySQL backup timer:

```bash
sudo mkdir -p /var/backups/warehouse_config
sudo chown -R warehouse:www-data /var/backups/warehouse_config
sudo chmod 750 /var/backups/warehouse_config
```

## 3. Create the virtual environment and install requirements

```bash
cd /opt/warehouse_config
sudo -u warehouse python3 -m venv /opt/warehouse_config/venv
sudo -u warehouse /opt/warehouse_config/venv/bin/pip install --upgrade pip
sudo -u warehouse /opt/warehouse_config/venv/bin/pip install -r requirements.txt
```

Do not skip `pip install -r requirements.txt`: it installs Django, PyMySQL, Gunicorn, and `cryptography`. Without `cryptography`, MySQL 8 authentication can fail for `sha256_password` or `caching_sha2_password` users.

## 4. Create and configure `.env`

Create `/opt/warehouse_config/.env` from the example file:

```bash
cd /opt/warehouse_config
sudo -u warehouse cp .env.example .env
sudo -u warehouse nano .env
```

Example production values for the current LAN deployment:

```env
DJANGO_SECRET_KEY=replace-with-a-long-random-secret
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=10.52.83.10,100.111.213.115,localhost,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=http://10.52.83.10:8081,http://100.111.213.115:8081
DJANGO_LANGUAGE_CODE=uk
DJANGO_TIME_ZONE=Europe/Kyiv
DJANGO_DB_CONN_MAX_AGE=60
DJANGO_ENABLE_PASSWORD_VALIDATORS=True

# Keep these disabled for LAN HTTP tests. Enable them only when the site is served over HTTPS.
# DJANGO_SESSION_COOKIE_SECURE=True
# DJANGO_CSRF_COOKIE_SECURE=True
# DJANGO_SECURE_SSL_REDIRECT=True

DB_ENGINE=django.db.backends.mysql
DB_NAME=warehouse_db
DB_USER=warehouse_user
DB_PASSWORD=change-me
DB_HOST=localhost
DB_PORT=3306
```

Do not commit real passwords or secrets. The `DB_PASSWORD` value in `.env` must exactly match the password of the MySQL user named in `DB_USER` for the configured host.

`DJANGO_CSRF_TRUSTED_ORIGINS` must include the URL scheme for every origin, for example `http://10.52.83.10:8081`. Django rejects scheme-less values such as `10.52.83.10:8081`.

For a LAN HTTP test on port `8081`, keep `DJANGO_SESSION_COOKIE_SECURE`, `DJANGO_CSRF_COOKIE_SECURE`, and `DJANGO_SECURE_SSL_REDIRECT` unset or set to `False`; secure cookies and SSL redirect require HTTPS. For HTTPS production behind Apache, enable those three flags with `True`.

Keep `.env` private but readable by the service:

```bash
sudo chmod 640 /opt/warehouse_config/.env
sudo chown warehouse:www-data /opt/warehouse_config/.env
```

## 5. Run Django setup commands

Run database, role, static asset, translation, and configuration checks before starting the service:

```bash
cd /opt/warehouse_config
sudo -u warehouse /opt/warehouse_config/venv/bin/python manage.py migrate
sudo -u warehouse /opt/warehouse_config/venv/bin/python manage.py init_roles
sudo -u warehouse /opt/warehouse_config/venv/bin/python manage.py collectstatic --noinput
sudo -u warehouse /opt/warehouse_config/venv/bin/python manage.py compilemessages
sudo -u warehouse /opt/warehouse_config/venv/bin/python manage.py check
```

Create an admin user if the deployment does not already have one:

```bash
sudo -u warehouse /opt/warehouse_config/venv/bin/python manage.py createsuperuser
```

Supported interface languages are `uk` — Українська and `en` — English. The repository stores gettext source files (`locale/*/LC_MESSAGES/django.po`), while compiled gettext binaries (`*.mo`) are intentionally not committed and must be generated on the server with `python manage.py compilemessages`.

## 6. Stop any temporary `runserver`

If a temporary test server is still running, stop it before enabling systemd/Gunicorn:

```bash
sudo pkill -f "manage.py runserver" 2>/dev/null || true
```

Use `runserver` only for short manual tests during troubleshooting. Production traffic should go through Apache and the `warehouse-gunicorn` systemd service.

## 7. Install and start the Gunicorn systemd service

The service example is `deploy/systemd/warehouse-gunicorn.service`. It runs as `warehouse`, reads `/opt/warehouse_config/.env`, starts in `/opt/warehouse_config`, and binds Gunicorn to `127.0.0.1:8001` with `config.wsgi:application`.

Install and start it:

```bash
cd /opt/warehouse_config
sudo cp deploy/systemd/warehouse-gunicorn.service /etc/systemd/system/warehouse-gunicorn.service
sudo systemctl daemon-reload
sudo systemctl enable warehouse-gunicorn
sudo systemctl start warehouse-gunicorn
sudo systemctl status warehouse-gunicorn
```

The service logs Gunicorn access/error output to journald with `--access-logfile -` and `--error-logfile -`.

## 8. Configure Apache2 reverse proxy

Apache must listen on the VirtualHost port used in the example. Add this line to `/etc/apache2/ports.conf` if it is not already present:

```apache
Listen 8081
```

Install the reverse proxy site:

```bash
cd /opt/warehouse_config
sudo cp deploy/apache/warehouse.conf.example /etc/apache2/sites-available/warehouse.conf
sudo a2enmod proxy proxy_http headers
sudo a2ensite warehouse.conf
sudo apache2ctl configtest
sudo systemctl reload apache2
```

The Apache example serves `/static/` directly from `STATIC_ROOT` at `/opt/warehouse_config/staticfiles/` and sends everything else to Gunicorn at `127.0.0.1:8001`:

```apache
Alias /static/ /opt/warehouse_config/staticfiles/
ProxyPass /static/ !
ProxyPass / http://127.0.0.1:8001/
ProxyPassReverse / http://127.0.0.1:8001/
```

Do not add aliases for `/manifest.webmanifest` or `/service-worker.js`. Those root-level PWA endpoints must reach Django/Gunicorn so Django can return the correct content type and service-worker headers. Only `/static/` is intercepted by Apache.

## 9. Verification commands

Check Gunicorn directly and Apache through the reverse proxy:

```bash
curl -I http://127.0.0.1:8001/uk/
curl -I http://127.0.0.1:8081/uk/
curl -I http://127.0.0.1:8081/manifest.webmanifest
curl -I http://127.0.0.1:8081/service-worker.js
```

Expected results:

- `curl -I http://127.0.0.1:8001/uk/` returns a Django response directly from Gunicorn.
- `curl -I http://127.0.0.1:8081/uk/` returns the same application through Apache.
- `/manifest.webmanifest` and `/service-worker.js` return through Apache but are proxied to Django/Gunicorn, not served from `/static/`.
- `sudo systemctl status warehouse-gunicorn` reports the service is active.
- `sudo apache2ctl configtest` returns `Syntax OK`.

For a LAN browser check, open the configured Apache URL, for example `http://10.52.83.10:8081/uk/` or `http://100.111.213.115:8081/uk/` if the host/firewall exposes port `8081`.

## 10. Install daily MySQL backups (optional but recommended)

The backup script stores compressed MySQL dumps in `/var/backups/warehouse_config`, writes operational logs to `/var/log/warehouse_config/backup.log`, keeps backups for 30 days, and targets RPO 24h / RTO 4h. See `docs/BACKUP_AND_RESTORE.md` for the full restore procedure.

```bash
cd /opt/warehouse_config
sudo cp docs/warehouse-backup.service.example /etc/systemd/system/warehouse-backup.service
sudo cp docs/warehouse-backup.timer.example /etc/systemd/system/warehouse-backup.timer
sudo systemctl daemon-reload
sudo systemctl enable --now warehouse-backup.timer
sudo systemctl list-timers | grep warehouse
```

Run a manual backup smoke test:

```bash
sudo systemctl start warehouse-backup.service
sudo systemctl status warehouse-backup.service
sudo tail -n 100 /var/log/warehouse_config/backup.log
```

## 11. Install logrotate for application logs

```bash
cd /opt/warehouse_config
sudo cp docs/logrotate-warehouse_config.example /etc/logrotate.d/warehouse_config
sudo logrotate -d /etc/logrotate.d/warehouse_config
```

## 12. Troubleshooting

View recent Gunicorn service logs:

```bash
journalctl -u warehouse-gunicorn -n 100 --no-pager
journalctl -u warehouse-gunicorn -f
```

Restart or reload services after changes:

```bash
sudo systemctl restart warehouse-gunicorn
sudo systemctl reload apache2
```

Check whether the old temporary runserver port, the Gunicorn port, or the Apache port is listening:

```bash
ss -ltnp | grep -E '8000|8001|8081'
```

Check Gunicorn directly:

```bash
curl -I http://127.0.0.1:8001/uk/
```

Check Apache:

```bash
curl -I http://127.0.0.1:8081/uk/
```

If `8000` is still listening for `manage.py runserver`, stop it:

```bash
sudo pkill -f "manage.py runserver" 2>/dev/null || true
```

## Password complexity setting

For a closed local warehouse network, password validators can be disabled only if that is an intentional administrative decision:

```env
DJANGO_ENABLE_PASSWORD_VALIDATORS=False
```

For production, keep the standard Django password validators enabled:

```env
DJANGO_ENABLE_PASSWORD_VALIDATORS=True
```

After changing `.env`, restart the application service:

```bash
sudo systemctl restart warehouse-gunicorn
```
