# warehouse_config

## Internationalization

The project uses Ukrainian as the default language and supports Ukrainian, Russian, and English URL prefixes:

- `/uk/`
- `/ru/`
- `/en/`

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
