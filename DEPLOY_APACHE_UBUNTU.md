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

The Python dependency list uses `PyMySQL`, so `mysqlclient` is not required by this project.

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

## 3. Create a virtual environment

```bash
cd /opt/warehouse_config
sudo -u warehouse python3 -m venv venv
sudo -u warehouse /opt/warehouse_config/venv/bin/pip install --upgrade pip
sudo -u warehouse /opt/warehouse_config/venv/bin/pip install -r requirements.txt
```

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

DB_ENGINE=django.db.backends.mysql
DB_NAME=warehouse_db
DB_USER=warehouse_user
DB_PASSWORD=change-me
DB_HOST=localhost
DB_PORT=3306
```

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
sudo -u warehouse /opt/warehouse_config/venv/bin/python manage.py collectstatic
sudo -u warehouse /opt/warehouse_config/venv/bin/python manage.py createsuperuser
```

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

## 8. Configure Apache2 reverse proxy

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

## 9. Verification commands

Run the Django checks:

```bash
cd /opt/warehouse_config
sudo -u warehouse /opt/warehouse_config/venv/bin/python manage.py check
sudo -u warehouse /opt/warehouse_config/venv/bin/python manage.py migrate
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
