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
pip install -r requirements.txt
python manage.py migrate
python manage.py init_roles
python manage.py compilemessages
python manage.py runserver 0.0.0.0:8000
```

Локальні URL:
- <http://127.0.0.1:8000/uk/>
- <http://127.0.0.1:8000/ru/>
- <http://127.0.0.1:8000/it/>
- <http://127.0.0.1:8000/admin/>

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
- Production runbook: `docs/SERVER01_GUNICORN_SWITCHOVER.md`
