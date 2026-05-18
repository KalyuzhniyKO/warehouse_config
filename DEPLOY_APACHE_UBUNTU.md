# Deploy warehouse_config on Ubuntu Server with Apache2 and Gunicorn

This guide deploys the Django warehouse system on Ubuntu Server with this request flow:

```text
Apache2 -> reverse proxy -> Gunicorn -> Django
```

The deployment uses Apache2 only. The examples below keep the application on a separate Apache VirtualHost at port `8081` so existing Apache sites such as Zabbix can continue to use their current ports and configuration.

## Assumptions

- Apache2 is already installed.
- MySQL is already installed and has a database/user prepared for the application.
- CUPS and GNU gettext are already installed.
- The application path is `/opt/warehouse_config`.
- The Linux service user is `warehouse`.
- The Django project module is `config`.
- The Gunicorn WSGI application is `config.wsgi:application`.

## 1. Install required OS packages

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip apache2 libapache2-mod-proxy-html gettext
sudo a2enmod proxy proxy_http headers
```

If you prefer to build or use packages that require MySQL headers later, install the development packages too:

```bash
sudo apt install pkg-config default-libmysqlclient-dev build-essential
```

The Python dependency list uses `PyMySQL`, so `mysqlclient` is not required by this project. For MySQL 8, PyMySQL also needs the `cryptography` package to authenticate with the default `caching_sha2_password` / `sha256_password` methods; install it through `requirements.txt` as shown below.

## 2. Create the service user and project directory

```bash
sudo adduser --system --group --home /opt/warehouse_config warehouse
sudo mkdir -p /opt/warehouse_config
sudo chown warehouse:www-data /opt/warehouse_config
```

Copy or clone the repository into `/opt/warehouse_config`, then ensure ownership is correct:

```bash
sudo chown -R warehouse:www-data /opt/warehouse_config
```

Create runtime directories for Django logs, Gunicorn logs, and MySQL backups:

```bash
sudo mkdir -p /var/log/warehouse_config
sudo mkdir -p /var/backups/warehouse_config
sudo chown -R warehouse:www-data /var/log/warehouse_config
sudo chown -R warehouse:www-data /var/backups/warehouse_config
sudo chmod 750 /var/log/warehouse_config
sudo chmod 750 /var/backups/warehouse_config
```

When `DEBUG=False`, Django writes production logs to `/var/log/warehouse_config/django.log` and `/var/log/warehouse_config/errors.log` under `LOG_DIR` (`/var/log/warehouse_config` by default). Gunicorn writes access and error logs to `/var/log/warehouse_config/gunicorn-access.log` and `/var/log/warehouse_config/gunicorn-error.log`. The Gunicorn process user `warehouse` must have write access to this directory; the `chown warehouse:www-data` and `chmod 750` commands above provide that access while keeping logs private from other users.

## 3. Create a virtual environment

```bash
cd /opt/warehouse_config
sudo -u warehouse python3 -m venv venv
sudo -u warehouse /opt/warehouse_config/venv/bin/pip install --upgrade pip
sudo -u warehouse /opt/warehouse_config/venv/bin/pip install -r requirements.txt
```

Do not skip `pip install -r requirements.txt`: it installs Django, PyMySQL, Gunicorn, and `cryptography`. Without `cryptography`, `python manage.py migrate` against MySQL 8 can fail with `RuntimeError: 'cryptography' package is required for sha256_password or caching_sha2_password auth methods`.

## 4. Configure environment variables

Create `/opt/warehouse_config/.env` from the example file:

```bash
cd /opt/warehouse_config
sudo -u warehouse cp .env.example .env
sudo -u warehouse nano .env
```

Example production values:

```env
DJANGO_SECRET_KEY=replace-with-a-long-random-secret
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=10.52.83.10,localhost,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=http://10.52.83.10:8081,http://10.52.83.10
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

The `DB_PASSWORD` value in `.env` must exactly match the password of the MySQL user named in `DB_USER` for the configured host. A mismatch in characters, letter case, whitespace, or using a password from another MySQL account will cause authentication failures during `python manage.py migrate` and other Django database commands.

`DJANGO_CSRF_TRUSTED_ORIGINS` must include the URL scheme for every origin, for example `http://10.52.83.10:8081` or `https://warehouse.example.com`. Django 4+ rejects scheme-less values such as `10.52.83.10:8081`.

For a LAN HTTP test on port `8081`, keep `DJANGO_SESSION_COOKIE_SECURE`, `DJANGO_CSRF_COOKIE_SECURE`, and `DJANGO_SECURE_SSL_REDIRECT` unset or set to `False`; secure cookies and SSL redirect require HTTPS. For HTTPS production behind Apache, enable those three flags with `True`.

`DJANGO_DB_CONN_MAX_AGE=60` enables persistent database connections for MySQL. Use `0` or leave it unset if you want Django to close database connections at the end of each request.

For production, enable the standard Django password validators with `DJANGO_ENABLE_PASSWORD_VALIDATORS=True`.

Keep `.env` private:

```bash
sudo chmod 640 /opt/warehouse_config/.env
sudo chown warehouse:www-data /opt/warehouse_config/.env
```

## 5. Run Django setup commands

```bash
cd /opt/warehouse_config
sudo -u warehouse /opt/warehouse_config/venv/bin/python manage.py check
sudo -u warehouse /opt/warehouse_config/venv/bin/python manage.py migrate
sudo -u warehouse /opt/warehouse_config/venv/bin/python manage.py compilemessages
sudo -u warehouse /opt/warehouse_config/venv/bin/python manage.py collectstatic
sudo -u warehouse /opt/warehouse_config/venv/bin/python manage.py createsuperuser
```

Supported interface languages are `uk` — Українська and `en` — English. The repository stores only gettext source files (`locale/*/LC_MESSAGES/django.po`). Compiled gettext binaries (`*.mo`) are intentionally ignored and must be generated on the server with `python manage.py compilemessages` after each `git pull` that changes translations.

## 6. Test Gunicorn manually

Run Gunicorn on localhost port `8001`:

```bash
cd /opt/warehouse_config
sudo -u warehouse /opt/warehouse_config/venv/bin/gunicorn --workers 3 --bind 127.0.0.1:8001 config.wsgi:application
```

In another shell, verify that Django responds:

```bash
curl http://127.0.0.1:8001/
```

Stop the manual Gunicorn process after this check.

## 7. Install the systemd service

Copy the example service file and start it:

```bash
sudo cp /opt/warehouse_config/docs/warehouse-gunicorn.service.example /etc/systemd/system/warehouse-gunicorn.service
sudo systemctl daemon-reload
sudo systemctl enable --now warehouse-gunicorn
sudo systemctl status warehouse-gunicorn
```

The service uses this WSGI application:

```text
config.wsgi:application
```

The example Gunicorn service also configures log files with these options:

```text
--access-logfile /var/log/warehouse_config/gunicorn-access.log
--error-logfile /var/log/warehouse_config/gunicorn-error.log
```

## 8. Install daily MySQL backups

The backup script stores compressed MySQL dumps in `/var/backups/warehouse_config`, writes operational logs to `/var/log/warehouse_config/backup.log`, keeps backups for 30 days, and targets RPO 24h / RTO 4h. See `docs/BACKUP_AND_RESTORE.md` for the full restore procedure.

Copy and enable the systemd timer:

```bash
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

## 9. Install logrotate for application logs

```bash
sudo cp docs/logrotate-warehouse_config.example /etc/logrotate.d/warehouse_config
sudo logrotate -d /etc/logrotate.d/warehouse_config
```

## 10. Configure Apache2 reverse proxy

Apache must listen on port `8081`. Add this line to `/etc/apache2/ports.conf` if it is not already present:

```apache
Listen 8081
```

Install the separate VirtualHost. This avoids changing existing Apache/Zabbix sites:

```bash
sudo cp /opt/warehouse_config/docs/apache-warehouse.conf.example /etc/apache2/sites-available/warehouse.conf
sudo a2ensite warehouse.conf
sudo apache2ctl configtest
sudo systemctl reload apache2
```

The VirtualHost proxies dynamic requests to Gunicorn at `127.0.0.1:8001` and serves collected static files from `/opt/warehouse_config/staticfiles/`.

## 11. Verification commands

Run the Django checks:

```bash
cd /opt/warehouse_config
sudo -u warehouse /opt/warehouse_config/venv/bin/python manage.py check
sudo -u warehouse /opt/warehouse_config/venv/bin/python manage.py migrate
sudo -u warehouse /opt/warehouse_config/venv/bin/python manage.py compilemessages
sudo -u warehouse /opt/warehouse_config/venv/bin/python manage.py collectstatic
sudo -u warehouse /opt/warehouse_config/venv/bin/python manage.py test
```

Check services and HTTP endpoints:

```bash
sudo systemctl status warehouse-gunicorn
sudo apache2ctl configtest
curl http://127.0.0.1:8001/
curl http://10.52.83.10:8081/
```

Expected results:

- `python manage.py check` reports no issues.
- Gunicorn service is active.
- `apache2ctl configtest` returns `Syntax OK`.
- `curl http://127.0.0.1:8001/` returns the Django homepage through Gunicorn.
- `curl http://10.52.83.10:8081/` returns the Django homepage through Apache2 reverse proxy.

## Налаштування складності паролів

Для локальної закритої мережі складу можна залишити прості паролі дозволеними:

```env
DJANGO_ENABLE_PASSWORD_VALIDATORS=false
```

Це також значення за замовчуванням, якщо змінна не задана. Якщо сайт доступний публічно або через інтернет, увімкніть стандартні валідатори Django:

```env
DJANGO_ENABLE_PASSWORD_VALIDATORS=true
```

Після зміни `.env` перезапустіть сервіс застосунку.

