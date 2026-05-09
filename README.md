# warehouse_config — складський облік на Django

`warehouse_config` — веб-система складського обліку для українськомовного середовища з підтримкою декількох мов інтерфейсу. Проєкт призначений для обліку номенклатури, складів, локацій зберігання, залишків, рухів товару та штрихкодів.

Система вже має базову доменну модель складу, Django Admin для довідників і документів руху, transactional service layer для зміни залишків, а також серверну документацію для запуску на Ubuntu через схему `Apache2 -> Gunicorn -> Django`.

У майбутньому проєкт має підтримувати друк етикеток, роботу зі сканерами штрихкодів, інвентаризацію, імпорт/експорт і розширені звіти.

## Зміст

- [Що це за система](#що-це-за-система)
- [Що вже реалізовано](#що-вже-реалізовано)
- [Архітектура](#архітектура)
- [Складські моделі](#складські-моделі)
- [Сервісний шар залишків](#сервісний-шар-залишків)
- [Мови та URL-и](#мови-та-url-и)
- [Локальний запуск](#локальний-запуск)
- [Серверний запуск на Ubuntu](#серверний-запуск-на-ubuntu)
- [MySQL](#mysql)
- [Backup і restore](#backup-і-restore)
- [Logging](#logging)
- [Перевірки](#перевірки)
- [Поточний стан цільового сервера](#поточний-стан-цільового-сервера)
- [Що ще не реалізовано / TODO](#що-ще-не-реалізовано--todo)
- [Додаткова документація](#додаткова-документація)

## Що це за система

`warehouse_config` — це Django-проєкт для складського обліку, який покриває базові процеси:

- ведення номенклатури товарів і матеріалів;
- опис складів і локацій всередині складів;
- облік поточних залишків;
- фіксацію рухів товару: початковий залишок, прихід, видача, повернення, списання, переміщення, коригування;
- реєстр штрихкодів для номенклатури, складів, стелажів і локацій;
- підготовку до майбутнього друку етикеток;
- підготовку до майбутньої роботи зі сканерами штрихкодів.

Основна мова системи — українська. Додатково підтримуються російська, англійська, німецька, польська, французька, іспанська, італійська, португальська та турецька мови.

## Що вже реалізовано

- Django 6.0.5.
- Django project layout з внутрішнім модулем `config`.
- Django settings module: `config.settings`.
- WSGI application: `config.wsgi:application`.
- Основний Django-застосунок `core`.
- Підтримка i18n для 10 мов: `uk`, `ru`, `en`, `de`, `pl`, `fr`, `es`, `it`, `pt`, `tr`.
- Українська мова за замовчуванням.
- URL-и через `i18n_patterns`: `/uk/`, `/ru/`, `/en/`, `/de/`, `/pl/`, `/fr/`, `/es/`, `/it/`, `/pt/`, `/tr/` та відповідні URL-и адмін-панелі.
- Language switcher у шаблонах.
- Документація deployment для `Apache2 -> Gunicorn -> Django`.
- Приклади systemd unit-файлів для Gunicorn і backup timer.
- Конфігурація через `.env`, зокрема для MySQL у production і SQLite у локальній розробці.
- Документація backup/restore для MySQL.
- Скрипт `scripts/backup_mysql.sh` для резервного копіювання MySQL.
- Logging config для Django, Gunicorn і backup-скрипта.
- Приклад logrotate-конфігурації.
- Базові складські моделі: одиниці виміру, категорії, отримувачі, номенклатура, склади, локації, штрихкоди, залишки, рухи.
- Django Admin для складських моделей.
- Transactional Stock service layer для всіх змін залишків.
- Тести моделей і сервісного шару залишків.

## Архітектура

Ключові частини репозиторію:

- `config/` — внутрішній Django-модуль проєкту: settings, URLs, WSGI/ASGI.
- `core/` — основний застосунок з доменною логікою складу.
- `core/models.py` — моделі складського домену.
- `core/services/stock.py` — єдине місце для бізнес-логіки зміни залишків.
- `core/migrations/` — міграції бази даних для складських моделей.
- `docs/` — deployment, backup/restore, systemd-приклади, logrotate, майбутній audit logging.
- `scripts/backup_mysql.sh` — production-скрипт backup MySQL.
- `templates/` — HTML-шаблони, включно з перемикачем мов.
- `locale/` — gettext-переклади.
- `static/` — статичні файли застосунку.

Актуальна структура проєкту:

```text
warehouse_config/
├── manage.py
├── README.md
├── requirements.txt
├── .env.example
├── DEPLOY_APACHE_UBUNTU.md
├── config/
│   ├── __init__.py
│   ├── asgi.py
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── core/
│   ├── __init__.py
│   ├── admin.py
│   ├── apps.py
│   ├── models.py
│   ├── tests.py
│   ├── urls.py
│   ├── views.py
│   ├── migrations/
│   │   ├── __init__.py
│   │   └── 0001_initial.py
│   └── services/
│       ├── __init__.py
│       └── stock.py
├── docs/
│   ├── AUDIT_LOGGING_TODO.md
│   ├── BACKUP_AND_RESTORE.md
│   ├── apache-warehouse.conf.example
│   ├── logrotate-warehouse_config.example
│   ├── warehouse-backup.service.example
│   ├── warehouse-backup.timer.example
│   └── warehouse-gunicorn.service.example
├── scripts/
│   └── backup_mysql.sh
├── templates/
│   └── includes/
│       └── language_switcher.html
├── locale/
└── static/
```

## Складські моделі

Моделі знаходяться у `core/models.py`.

### Довідники та базові сутності

- `Unit` — одиниці виміру. Має унікальні `name` і `symbol`.
- `Category` — категорії номенклатури. Підтримує ієрархію через `parent`.
- `Recipient` — отримувачі товару для операцій видачі.
- `Item` — номенклатура. Має назву, опціональний внутрішній код, категорію, одиницю виміру, опціональний штрихкод і опис.
- `Warehouse` — склади. Має назву, адресу та опціональний штрихкод.
- `Location` — локації всередині складу. Підтримує типи `location` і `rack`, належить до складу, може мати батьківську локацію та штрихкод.

### Штрихкоди

- `BarcodeRegistry` — глобальний реєстр штрихкодів.
- `BarcodeSequence` — послідовності генерації штрихкодів за префіксами.

Важливі принципи:

- `BarcodeRegistry.barcode` глобально унікальний.
- Підтримані префікси:
  - `ITM` — номенклатура;
  - `WH` — склад;
  - `RCK` — стелаж;
  - `LOC` — локація.
- Модель перевіряє, що barcode починається з вибраного префікса.
- `Item`, `Warehouse` і `Location` використовують `OneToOneField` на `BarcodeRegistry`, щоб один штрихкод не міг бути привʼязаний до кількох сутностей.

### Залишки та рухи

- `StockBalance` — поточний залишок конкретної номенклатури у конкретній локації.
- `StockMovement` — історія рухів товару.

Важливі принципи залишків:

- `StockBalance` унікальний для пари `item + location`.
- Кількість зберігається як `DecimalField(max_digits=18, decimal_places=3)`.
- Всі базові доменні сутності успадковують `is_active`, `created_at`, `updated_at`; soft-delete/архівування виконується через `is_active`.
- `Item.internal_code` унікальний, якщо заповнений. Порожній рядок автоматично перетворюється на `NULL`, щоб можна було мати багато позицій без внутрішнього коду.
- Типи `StockMovement`:
  - `initial_balance` — початковий залишок;
  - `in` — прихід;
  - `out` — видача;
  - `return` — повернення;
  - `writeoff` — списання;
  - `transfer` — переміщення;
  - `adjustment` — коригування.

## Сервісний шар залишків

Вся бізнес-логіка зміни залишків зосереджена у `core/services/stock.py`. Залишки не потрібно змінювати напряму через `StockBalance.objects.update(...)` або ручне редагування кількості в різних частинах коду. Правильний шлях — викликати сервісну функцію.

Реалізовані функції:

- `create_initial_balance` — створює початковий залишок і рух типу `initial_balance`.
- `receive_stock` — збільшує залишок у локації та створює рух типу `in`.
- `issue_stock` — видає товар отримувачу, зменшує залишок і створює рух типу `out`.
- `return_stock` — повертає товар на склад і створює рух типу `return`.
- `writeoff_stock` — списує товар і створює рух типу `writeoff`.
- `transfer_stock` — переміщує товар між двома різними локаціями та створює рух типу `transfer`.
- `adjust_stock` — встановлює цільову кількість `target_qty` і створює рух типу `adjustment` на різницю.

Гарантії сервісного шару:

- всі зміни залишків виконуються тільки через сервіс;
- кожна операція виконується у `transaction.atomic()`;
- баланс блокується через `select_for_update()`, щоб уникнути race condition при паралельних операціях;
- відʼємний залишок заборонений;
- кожна успішна операція створює запис `StockMovement`;
- `transfer_stock` виконує списання з джерела та прихід у цільову локацію в одній транзакції;
- `adjust_stock` приймає `target_qty`, а не delta-значення, і сам рахує різницю.

## Мови та URL-и

Проєкт використовує Django i18n.

- Мова за замовчуванням: українська (`uk`).
- Підтримувані мови:
  - `uk` — Українська
  - `ru` — Русский
  - `en` — English
  - `de` — Deutsch
  - `pl` — Polski
  - `fr` — Français
  - `es` — Español
  - `it` — Italiano
  - `pt` — Português
  - `tr` — Türkçe
- URL-и побудовані через `i18n_patterns`, наприклад `/uk/`, `/ru/`, `/en/`, `/de/`, а також `/uk/admin/`, `/ru/admin/`, `/en/admin/`, `/de/admin/` тощо.
- У шаблонах є перемикач мов із прапорцями. Він передає в `set_language` URL з оновленим мовним префіксом, тому перехід з `/uk/items/?q=test` на English повертає користувача на `/en/items/?q=test`.

Команди для роботи з перекладами:

```bash
python manage.py makemessages -l uk -l ru -l en -l de -l pl -l fr -l es -l it -l pt -l tr
python manage.py compilemessages
```

У git зберігаються тільки текстові файли перекладів `.po` у каталозі `locale/`. Скомпільовані бінарні файли `.mo` не комітяться та ігноруються через `.gitignore`; після `git pull` на сервері потрібно виконати:

```bash
python manage.py compilemessages
```

> Для `makemessages` і `compilemessages` на сервері або локальній машині має бути встановлений GNU gettext.

## Локальний запуск

Локальна розробка може використовувати SQLite. Для production очікується MySQL.

```bash
python -m venv venv
source venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
cp .env.example .env
python manage.py check
python manage.py migrate
python manage.py test
python manage.py runserver
```

Для SQLite у локальному `.env` можна використати такий приклад:

```env
DJANGO_SECRET_KEY=dev-only-secret-key-change-me
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
DJANGO_LANGUAGE_CODE=uk
DJANGO_TIME_ZONE=Europe/Kyiv

DB_ENGINE=django.db.backends.sqlite3
DB_NAME=db.sqlite3
DB_USER=
DB_PASSWORD=
DB_HOST=
DB_PORT=
```

Після запуску dev-сервера застосунок буде доступний за адресою:

```text
http://127.0.0.1:8000/
```

Django перенаправить або сформує мовні URL-и, наприклад `/uk/`.

## Серверний запуск на Ubuntu

Детальна інструкція для production-розгортання описана в [`DEPLOY_APACHE_UBUNTU.md`](DEPLOY_APACHE_UBUNTU.md).

Цільова схема:

```text
Apache2 VirtualHost :8081 -> Gunicorn 127.0.0.1:8001 -> Django config.wsgi:application
```

Мінімальний quick start для підготовки коду:

```bash
sudo mkdir -p /opt/warehouse_config
sudo chown warehouse:www-data /opt/warehouse_config
git clone https://github.com/KalyuzhniyKO/warehouse_config.git /opt/warehouse_config
cd /opt/warehouse_config
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py check
python manage.py migrate
python manage.py collectstatic
```

Після цього потрібно:

- заповнити production `.env` реальними значеннями;
- налаштувати MySQL;
- підключити systemd unit для Gunicorn;
- налаштувати Apache VirtualHost на окремому порту, бажано `8081`;
- переконатися, що Gunicorn слухає `127.0.0.1:8001`;
- налаштувати директорії логів і backup;
- увімкнути backup timer.

## MySQL

У production використовується MySQL. Локально для розробки можна залишити SQLite.

Для MySQL 8 із драйвером PyMySQL обов'язково встановлюйте залежності з `requirements.txt`:

```bash
pip install -r requirements.txt
```

У цьому списку є пакет `cryptography`, який потрібен PyMySQL для MySQL 8 auth methods `caching_sha2_password` / `sha256_password`. Без нього `python manage.py migrate` може завершитися помилкою `RuntimeError: 'cryptography' package is required for sha256_password or caching_sha2_password auth methods`.

Приклад створення бази та користувача:

```sql
CREATE DATABASE IF NOT EXISTS warehouse_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'warehouse_user'@'localhost' IDENTIFIED BY 'Warehouse_2026_StrongPass!ChangeMe';
GRANT ALL PRIVILEGES ON warehouse_db.* TO 'warehouse_user'@'localhost';
FLUSH PRIVILEGES;
```

`Warehouse_2026_StrongPass!ChangeMe` — лише приклад достатньо складного пароля для проходження типової MySQL password policy. Для реального сервера потрібно згенерувати власний секретний пароль і не комітити його в репозиторій.

Той самий пароль потрібно прописати у production `.env`:

```env
DB_ENGINE=django.db.backends.mysql
DB_NAME=warehouse_db
DB_USER=warehouse_user
DB_PASSWORD=Warehouse_2026_StrongPass!ChangeMe
DB_HOST=localhost
DB_PORT=3306
```

> **Увага:** значення `DB_PASSWORD` у `.env` має точно збігатися з паролем MySQL-користувача `DB_USER` для відповідного `DB_HOST`. Будь-яка різниця у символах, регістрі, пробілах або використання пароля від іншого MySQL-користувача призведе до помилки автентифікації під час `python manage.py migrate` та інших команд Django.

> У README показані тільки приклади. Реальні секрети, паролі, ключі та токени не повинні зберігатися в Git.

## Backup і restore

Backup MySQL реалізований через `scripts/backup_mysql.sh`.

Основні параметри:

- backup-директорія: `/var/backups/warehouse_config`;
- лог backup-скрипта: `/var/log/warehouse_config/backup.log`;
- retention backup: 30 днів;
- RPO: 24 години;
- RTO: 4 години;
- systemd timer/service приклади знаходяться у `docs/warehouse-backup.timer.example` та `docs/warehouse-backup.service.example`;
- детальна процедура backup/restore описана у `docs/BACKUP_AND_RESTORE.md`.

Корисні команди перевірки backup timer і логів:

```bash
sudo systemctl status warehouse-backup.timer
sudo systemctl list-timers | grep warehouse
sudo tail -n 100 /var/log/warehouse_config/backup.log
```

## Logging

У production логи зберігаються в `/var/log/warehouse_config`.

Очікувані файли:

- `django.log` — основні Django-логи рівня `INFO` і вище;
- `errors.log` — помилки Django рівня `ERROR`;
- `gunicorn-access.log` — access log Gunicorn;
- `gunicorn-error.log` — error log Gunicorn;
- `backup.log` — лог виконання `scripts/backup_mysql.sh`.

Для ротації логів є приклад:

```text
docs/logrotate-warehouse_config.example
```

У локальній розробці при `DJANGO_DEBUG=True` Django може писати логи в консоль, щоб не вимагати наявності `/var/log/warehouse_config`.

## Internationalisation (i18n) - Updated Translations

Перевір: **branch** `fix-i18n-from-main` — виправлення системи локалізації та заповнення пустих перекладів.

### Зміни:
- **Російська мова (`locale/ru/LC_MESSAGES/django.po`)**: заповнено всі критичні пусті `msgstr` перекладів:
  - Повідомлення про валідацію форм (дублікати назв сутностей).
  - Типи вкладискладських операцій: `initial balance` → "Начальный баланс", `in` → "Прихід", `out` → "Відпуск", `return` → "Вернення", `write-off` → "Списання", `transfer` → "Перенесення", `adjustment` → "Коригування".
  - Назви полів моделей для Django Admin.
  - Мітки форм, шаблонів та UI-компонентів.
  - Повідомлення про успіх/помилку з views.

- **Українська мова (`locale/uk/LC_MESSAGES/django.po`)**: виправлено типи операцій, які були помилково заповнені англійськими термінами замість українських. Додано правильні переклади:
  - `initial balance` → "Початковий баланс", `in` → "Прихід", `out` → "Видача", та ін.

- **Англійська мова (`locale/en/LC_MESSAGES/django.po`)**: заповнено типи операцій:
  - `initial balance` → "Initial balance", `in` → "Incoming", `out` → "Outgoing", `return` → "Return", `write-off` → "Write-off", `transfer` → "Transfer", `adjustment` → "Adjustment".

- **Шаблони (`templates/base.html`)**: приховано пункт меню **«Отримувачі»** для звичайних користувачів. Ссилка видима тільки для суперюзера та користувачів групи "Адміністратор складу".

- **Довідка**: всі типи операцій (`get_movement_type_display`) вже правильно використовуються у `templates/core/stockmovement_list.html` для відображення читаних назв операцій замість "сирих" значень бази даних.

### Перевірки перед commit:
```bash
python -m compileall manage.py config core
python manage.py check
python manage.py test
python manage.py makemigrations --check --dry-run
python manage.py compilemessages
```

## Перевірки

Базові команди перед комітом або deployment:

```bash
python manage.py check
python manage.py test
python -m compileall manage.py config core
```

## Поточний стан цільового сервера

Узагальнений цільовий production-профіль без привʼязки до персональних даних:

- операційна система: Ubuntu Server;
- вебсервер: Apache2;
- application server: Gunicorn;
- база даних: MySQL;
- додаткові системні пакети: CUPS, gettext;
- системний користувач застосунку: `warehouse`;
- робоча директорія: `/opt/warehouse_config`;
- директорія логів: `/var/log/warehouse_config`;
- директорія backup: `/var/backups/warehouse_config`;
- Apache працює через окремий VirtualHost, бажано на порту `8081`;
- Gunicorn слухає локальний інтерфейс `127.0.0.1:8001`.

## Що ще не реалізовано / TODO

- UI для CRUD складів, локацій, номенклатури та довідників поза Django Admin.
- UI для прийому, видачі, повернення, списання, переміщення та коригування залишків.
- Друк етикеток.
- Інтеграція зі сканером штрихкодів.
- Інвентаризація.
- Імпорт/експорт Excel.
- Ролі користувачів і деталізовані права доступу.
- Повний `AuditLog` у базі даних.
- Звіти по залишках, рухах, складах, номенклатурі та отримувачах.

## Додаткова документація

- [`DEPLOY_APACHE_UBUNTU.md`](DEPLOY_APACHE_UBUNTU.md) — повна інструкція deployment на Ubuntu з Apache і Gunicorn.
- [`docs/BACKUP_AND_RESTORE.md`](docs/BACKUP_AND_RESTORE.md) — backup/restore MySQL, RPO/RTO, перевірки.
- [`docs/AUDIT_LOGGING_TODO.md`](docs/AUDIT_LOGGING_TODO.md) — план майбутнього audit logging.
- [`docs/apache-warehouse.conf.example`](docs/apache-warehouse.conf.example) — приклад Apache VirtualHost.
- [`docs/warehouse-gunicorn.service.example`](docs/warehouse-gunicorn.service.example) — приклад systemd service для Gunicorn.
- [`docs/warehouse-backup.service.example`](docs/warehouse-backup.service.example) — приклад systemd service для backup.
- [`docs/warehouse-backup.timer.example`](docs/warehouse-backup.timer.example) — приклад systemd timer для регулярного backup.
- [`docs/logrotate-warehouse_config.example`](docs/logrotate-warehouse_config.example) — приклад logrotate-конфігурації.

## Повний складський процес: прихід, штрихкоди та етикетки

Система підтримує повний робочий цикл складу:

1. **Штрихкоди генеруються автоматично** для нової номенклатури, складів і локацій. Послідовності ведуться окремо для префіксів `ITM`, `WH`, `LOC`, `RCK`; формат — `ITM0000000001`, `WH0000000001`, `LOC0000000001`, `RCK0000000001`.
2. **Прихід товару** доступний у меню **Прихід товару** або за URL `/stock/receive/`. Форма створює рух типу `in` через сервіс `receive_stock`, збільшує залишок і показує сторінку результату з кнопкою друку етикетки.
3. **Початковий залишок** доступний у меню **Початковий залишок** або за URL `/stock/initial/`. Операція виконується через `create_initial_balance` і створює рух типу `initial_balance`.
4. **Рухи товарів** доступні за URL `/stock/movements/` із фільтрами за типом, номенклатурою, складом, локацією, датами та пошуком за назвою, `internal_code`, `barcode`.
5. **PDF етикетки** можна завантажити зі сторінки друку номенклатури `/labels/item/<id>/print/` або напряму `/labels/item/<id>/download/`. Стандартний шаблон — 58×40 мм.
6. **Друк через CUPS** використовує системну команду `lp -d PRINTER_NAME file.pdf`. Помилки друку записуються у `PrintJob` і показуються користувачу без 500-помилки.

### Перевірка принтерів на Ubuntu

```bash
lpstat -p -d
```

Тестовий друк:

```bash
echo test | lp -d PRINTER_NAME
```

### Ролі доступу

- **Адміністратор складу** — усі складські операції, принтери, шаблони етикеток і керування.
- **Комірник** — прихід, початковий залишок, рухи, залишки та друк етикеток.
- **Перегляд / аудитор** — перегляд залишків і рухів.

## Паролі та валідатори Django

За замовчуванням система дозволяє прості паролі, щоб її було зручно запускати в локальній закритій мережі складу:

```env
DJANGO_ENABLE_PASSWORD_VALIDATORS=false
```

Якщо змінна не задана або має значення `false`, `AUTH_PASSWORD_VALIDATORS` порожній і Django не блокує прості паролі. Для публічного доступу або доступу з інтернету обов'язково увімкніть стандартні валідатори Django:

```env
DJANGO_ENABLE_PASSWORD_VALIDATORS=true
```

