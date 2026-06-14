# warehouse_config

`warehouse_config` — веб-система складського обліку на Django для щоденної роботи складу, self-service сценаріїв комірника на планшеті та управлінських задач адміністратора.

## Призначення системи

Система покриває повний базовий цикл складського обліку:
- довідники (товари, категорії, одиниці виміру, склади, локації, місця використання, працівники/отримувачі);
- операції руху товару;
- залишки по складу/локації;
- журнал рухів;
- інвентаризацію;
- друк етикеток і контрольних талонів;
- багатомовний інтерфейс для користувачів складу.

## Основні ролі

- **Self-service / tablet user (комірник):** швидкі сценарії для щоденних операцій через великі touch-friendly форми та сканування штрихкодів.
- **Warehouse/Admin management user (адміністратор складу):** керування довідниками, користувачами ролей, налаштуваннями, аналітикою, переглядом і контролем рухів.
- **Django superuser (`/admin/`):** технічне адміністрування Django Admin, аварійний доступ і службові задачі.

## Основні складські операції

- **Прихід товару (Receive stock)**
- **Видача товару (Issue item)**
- **Повернення товару (Return item)**
- **Журнал операцій (Stock movements)**
- **Залишки (Stock balances)**
- **Довідники (Directories)**

### Різниця між «Приходом» і «Поверненням»

Після розділення flow це дві окремі операції:

- **Прихід товару / Receive stock**
  - це надходження товару на склад;
  - створює рух `MovementType.IN`;
  - **не вимагає вибору працівника**.

- **Повернення товару / Return item**
  - це повернення товару від конкретного працівника;
  - створює рух `MovementType.RETURN`;
  - **вимагає вибору працівника та місця використання**.

## Підтримувані мови інтерфейсу

- Українська (`uk`)
- English (`en`)
- Русский (`ru`)
- Italiano (`it`)

## Локальний запуск

```bash
cd /path/to/warehouse_config
python -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Для локальних інструментів розробки опціонально встановіть dev-залежності:

```bash
pip install -r requirements-dev.txt
```

Підготуйте та запустіть застосунок:

```bash
python manage.py migrate
python manage.py compilemessages
python manage.py init_roles
python manage.py createsuperuser
python manage.py runserver
```

Якщо `compilemessages` завершується помилкою, встановіть GNU gettext / `msgfmt`.
На сервері/Linux gettext має бути доступний або встановлений через системні пакети.

Локальні URL:
- <http://127.0.0.1:8000/uk/>
- <http://127.0.0.1:8000/ru/>
- <http://127.0.0.1:8000/it/>
- <http://127.0.0.1:8000/admin/>

## Перевірки та тести

Тести розташовані в `core/tests` і запускаються стандартним Django test runner:

```bash
python manage.py check
python manage.py test core.tests
python manage.py test
```

Black і Ruff доступні після встановлення `requirements-dev.txt`, але поки не є
обов'язковими CI-перевірками для всієї legacy-кодової бази:

```bash
black --check .
ruff check .
```

## Налаштування CUPS-принтера для етикеток

1. На сервері встановіть CUPS і клієнтські утиліти, наприклад `cups` / `cups-client`.
2. Додайте принтер у Linux/CUPS і перевірте системні queue:

```bash
lpstat -v
lpstat -d
```

3. У веб-інтерфейсі відкрийте **Налаштування складу → Принтери** (`/settings/printers/`).
4. Натисніть **Оновити список принтерів**, щоб синхронізувати реальні CUPS-принтери в довідник `Printer`.
5. Виконайте **Тестовий друк** для потрібного принтера.
6. Після успішного тесту користувачі можуть вибирати цей принтер під час друку етикеток.

Якщо `lpstat`, `lp` або CUPS queue недоступні, веб-інтерфейс показує зрозумілу помилку замість прихованого збою друку.

## Production deployment (коротко)

Рекомендована production-схема:

**Apache -> Gunicorn -> Django -> MySQL**

- `Apache` працює як reverse proxy для застосунку;
- `Gunicorn` запускає Django-процес;
- systemd service: **`warehouse-gunicorn`**;
- детальний runbook з командами та перевірками: **`docs/SERVER01_GUNICORN_SWITCHOVER.md`**.

## Документація

- Інструкція користувача: `docs/USER_GUIDE.md`
- Інструкція адміністратора: `docs/ADMIN_GUIDE.md`
- Архітектурний аудит і roadmap рефакторингу: `docs/ARCHITECTURE_AUDIT.md`
- Production runbook: `docs/SERVER01_GUNICORN_SWITCHOVER.md`
