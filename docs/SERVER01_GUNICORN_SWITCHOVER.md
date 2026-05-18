# server01 Gunicorn switchover runbook

`python manage.py runserver 0.0.0.0:8000` is only a temporary test command. Use this checklist over SSH to switch the real Ubuntu `server01` to the production path:

```text
Apache -> Gunicorn -> Django -> MySQL
```

The server details used below are:

- sudo/admin user: `ilovewindows`
- runtime user: `warehouse`
- project path: `/opt/warehouse_config`
- virtualenv: `/opt/warehouse_config/venv`
- database: MySQL `warehouse_db`

## 1. Connect

```bash
ssh ilovewindows@10.52.83.10
```

Alternative Tailscale address:

```bash
ssh ilovewindows@100.111.213.115
```

## 2. Stop the temporary runserver and inspect ports

```bash
sudo pkill -f "manage.py runserver" 2>/dev/null || true
ps aux | grep manage.py
ss -ltnp | grep -E '8000|8001|8081' || true
```

## 3. Update the project

```bash
sudo -u warehouse git config --global --add safe.directory /opt/warehouse_config

sudo -u warehouse bash -lc '
cd /opt/warehouse_config
source venv/bin/activate

git checkout main
git pull --ff-only origin main

pip install -r requirements.txt

python manage.py migrate
python manage.py init_roles
python manage.py collectstatic --noinput
python manage.py compilemessages
python manage.py check
'
```

## 4. Prepare Django log directory

```bash
sudo mkdir -p /var/log/warehouse_config
sudo chown -R warehouse:www-data /var/log/warehouse_config
sudo chmod 750 /var/log/warehouse_config
```

## 5. Install and start the systemd Gunicorn service

```bash
sudo cp /opt/warehouse_config/deploy/systemd/warehouse-gunicorn.service /etc/systemd/system/warehouse-gunicorn.service
sudo systemctl daemon-reload
sudo systemctl enable warehouse-gunicorn
sudo systemctl restart warehouse-gunicorn
sudo systemctl status warehouse-gunicorn --no-pager
```

## 6. Install Apache config carefully

`deploy/apache/warehouse.conf.example` is currently an Apache VirtualHost on port `8081` that proxies to Gunicorn on `127.0.0.1:8001`.

Before copying, check the existing enabled sites. Do not overwrite a custom Apache config without a backup.

```bash
sudo ls -la /etc/apache2/sites-enabled/
sudo cp /etc/apache2/sites-available/warehouse.conf /etc/apache2/sites-available/warehouse.conf.bak.$(date +%Y%m%d_%H%M%S) 2>/dev/null || true
```

If port `8081` is still intended for this deployment, install the provided example:

```bash
sudo cp /opt/warehouse_config/deploy/apache/warehouse.conf.example /etc/apache2/sites-available/warehouse.conf
sudo a2enmod proxy proxy_http headers
sudo a2ensite warehouse.conf
sudo apache2ctl configtest
sudo systemctl reload apache2
```

## 7. Verify after start

Local Gunicorn and Apache checks:

```bash
curl -I http://127.0.0.1:8001/uk/
curl -I http://127.0.0.1:8081/uk/
curl -I http://127.0.0.1:8081/manifest.webmanifest
curl -I http://127.0.0.1:8081/service-worker.js
```

LAN checks:

```bash
curl -I http://10.52.83.10/uk/
curl -I http://10.52.83.10/manifest.webmanifest
curl -I http://10.52.83.10/service-worker.js
```

If the Apache VirtualHost is reachable on port `8081`, also check:

```bash
curl -I http://10.52.83.10:8081/uk/
curl -I http://10.52.83.10:8081/manifest.webmanifest
curl -I http://10.52.83.10:8081/service-worker.js
```

## 8. Troubleshooting

```bash
journalctl -u warehouse-gunicorn -n 100 --no-pager
journalctl -u warehouse-gunicorn -f
sudo systemctl restart warehouse-gunicorn
sudo systemctl reload apache2
ss -ltnp | grep -E '8000|8001|8081'
tail -100 /var/log/warehouse_config/django.log
tail -100 /var/log/warehouse_config/errors.log
```

## 9. Emergency temporary fallback to runserver

Use this only as an emergency temporary fallback while fixing Gunicorn/systemd/Apache. It returns to the non-production `runserver` command.

```bash
sudo systemctl stop warehouse-gunicorn

sudo -u warehouse bash -lc '
cd /opt/warehouse_config
source venv/bin/activate
nohup python manage.py runserver 0.0.0.0:8000 > /tmp/warehouse_runserver.log 2>&1 &
'

tail -100 /tmp/warehouse_runserver.log
```
