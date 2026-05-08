# warehouse_config

`warehouse_config` is a Django-based warehouse management system prepared for Ukrainian-first deployments. The application supports multilingual URLs and is structured so the repository name stays `warehouse_config` while the internal Django project module is `config`.

## Supported languages

The default language is Ukrainian (`uk`). The configured languages are:

- Ukrainian: `/uk/`
- Russian: `/ru/`
- English: `/en/`

GNU gettext is used for translation files.

## Project structure

```text
warehouse_config/
├── manage.py
├── config/
│   ├── __init__.py
│   ├── settings.py
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
├── core/
│   ├── __init__.py
│   ├── apps.py
│   ├── views.py
│   ├── urls.py
│   └── tests.py
├── templates/
│   └── includes/
│       └── language_switcher.html
├── locale/
├── static/
├── requirements.txt
├── .env.example
└── README.md
```

Important Django entry points:

- Settings module: `config.settings`
- URL configuration: `config.urls`
- WSGI application: `config.wsgi:application`

## Local development

Create and activate a virtual environment:

```bash
python -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Create a local `.env` file:

```bash
cp .env.example .env
```

For local SQLite development, you may set these values in `.env`:

```env
DJANGO_SECRET_KEY=dev-only-secret-key
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
DB_ENGINE=django.db.backends.sqlite3
DB_NAME=db.sqlite3
DB_USER=
DB_PASSWORD=
DB_HOST=
DB_PORT=
```

Run Django commands:

```bash
python manage.py check
python manage.py migrate
python manage.py runserver
```

Open the application at:

```text
http://127.0.0.1:8000/
```

## Ubuntu Server deployment

Production deployment is documented in [DEPLOY_APACHE_UBUNTU.md](DEPLOY_APACHE_UBUNTU.md).

The target server flow is:

```text
Apache2 -> reverse proxy -> Gunicorn -> Django
```

Gunicorn must run Django with:

```bash
gunicorn --workers 3 --bind 127.0.0.1:8001 config.wsgi:application
```

Apache2 should expose a separate VirtualHost on port `8081` and proxy to Gunicorn on `127.0.0.1:8001`.

## Internationalization commands

Install GNU gettext before creating or compiling translation files:

```bash
sudo apt install gettext
```

Create message files for each supported language:

```bash
python manage.py makemessages -l uk
python manage.py makemessages -l ru
python manage.py makemessages -l en
```

Compile translations after editing `.po` files:

```bash
python manage.py compilemessages
```
