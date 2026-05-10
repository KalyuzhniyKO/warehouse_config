from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import ProtectedError

from core.models import (
    Category,
    Item,
    Location,
    Recipient,
    StockBalance,
    StockMovement,
    Unit,
    Warehouse,
)
from core.permissions import AUDITOR_GROUP, STOREKEEPER_GROUP, WAREHOUSE_ADMIN_GROUP
from core.services.stock import create_initial_balance

DEMO_CODE_PREFIX = "DEMO-"
DEMO_COMMENT = "Демо початковий залишок"

WAREHOUSES = ["Основний склад", "Резервний склад"]
LOCATIONS = ["Основна локація", "A-01", "A-02", "B-01", "Z-01"]
UNITS = [
    ("Штука", "шт"),
    ("Кілограм", "кг"),
    ("Метр", "м"),
    ("Літр", "л"),
]
CATEGORIES = [
    "Електрика",
    "Механіка",
    "Пневматика",
    "Кріплення",
    "Витратні матеріали",
]
RECIPIENTS = [
    "Цех сітки",
    "Цех оцинкування",
    "Ремонтна дільниця",
    "Технічна служба",
]
ITEMS = [
    (
        "Автоматичний вимикач 16А",
        "Електрика",
        "шт",
        Decimal("12.000"),
        "Основний склад",
        "Основна локація",
    ),
    (
        "Кінцевий вимикач",
        "Електрика",
        "шт",
        Decimal("8.000"),
        "Основний склад",
        "A-01",
    ),
    (
        "Кабель ПВ-3 2.5 мм²",
        "Електрика",
        "м",
        Decimal("150.000"),
        "Основний склад",
        "A-02",
    ),
    (
        "Датчик індуктивний",
        "Електрика",
        "шт",
        Decimal("6.000"),
        "Основний склад",
        "B-01",
    ),
    (
        "Підшипник 6204",
        "Механіка",
        "шт",
        Decimal("20.000"),
        "Основний склад",
        "Основна локація",
    ),
    (
        "Болт М8×30",
        "Кріплення",
        "шт",
        Decimal("500.000"),
        "Резервний склад",
        "A-01",
    ),
    (
        "Гайка М8",
        "Кріплення",
        "шт",
        Decimal("500.000"),
        "Резервний склад",
        "A-02",
    ),
    (
        "Пневмоциліндр",
        "Пневматика",
        "шт",
        Decimal("4.000"),
        "Резервний склад",
        "B-01",
    ),
    (
        "Масло технічне",
        "Витратні матеріали",
        "л",
        Decimal("40.000"),
        "Основний склад",
        "Основна локація",
    ),
    (
        "Рукавиці робочі",
        "Витратні матеріали",
        "шт",
        Decimal("60.000"),
        "Резервний склад",
        "Основна локація",
    ),
]
TEST_USERS = {
    "warehouse_admin": ("warehouse_admin", WAREHOUSE_ADMIN_GROUP),
    "storekeeper": ("storekeeper", STOREKEEPER_GROUP),
    "auditor": ("auditor", AUDITOR_GROUP),
}


class Command(BaseCommand):
    help = "Seed idempotent demo data for local warehouse testing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--create-users",
            action="store_true",
            help="Create optional demo users and assign warehouse roles.",
        )
        parser.add_argument(
            "--reset-passwords",
            action="store_true",
            help="Reset demo user passwords to their standard values.",
        )
        parser.add_argument(
            "--clear-demo",
            action="store_true",
            help="Remove only DEMO-* items with related demo balances and movements.",
        )
        parser.add_argument(
            "--clear-users",
            action="store_true",
            help="With --clear-demo, remove only the known demo users.",
        )

    def handle(self, *args, **options):
        if options["clear_users"] and not options["clear_demo"]:
            raise CommandError(
                "--clear-users можна використовувати тільки разом з --clear-demo."
            )

        if options["clear_demo"]:
            self.clear_demo_data(clear_users=options["clear_users"])
            return

        call_command("init_roles", stdout=self.stdout)
        self.seed_directories()
        self.seed_items_and_balances()

        if options["create_users"]:
            self.seed_users(reset_passwords=options["reset_passwords"])
        elif options["reset_passwords"]:
            self.stdout.write(
                self.style.WARNING(
                    "--reset-passwords пропущено, бо --create-users не передано."
                )
            )

        self.stdout.write(self.style.SUCCESS("Демо-дані готові."))

    def write_result(self, label, name, created):
        status = "створено" if created else "вже існувало"
        self.stdout.write(f"{label}: {name} — {status}.")

    def seed_directories(self):
        for name in WAREHOUSES:
            warehouse, created = Warehouse.objects.get_or_create(name=name)
            self.write_result("Склад", warehouse.name, created)

        for warehouse in Warehouse.objects.filter(name__in=WAREHOUSES):
            for name in LOCATIONS:
                location, created = Location.objects.get_or_create(
                    warehouse=warehouse,
                    name=name,
                    defaults={"location_type": Location.LocationType.LOCATION},
                )
                self.write_result("Локація", str(location), created)

        for name, symbol in UNITS:
            unit, created = Unit.objects.get_or_create(
                symbol=symbol, defaults={"name": name}
            )
            self.write_result("Одиниця", unit.symbol, created)

        for name in CATEGORIES:
            category, created = Category.objects.get_or_create(name=name)
            self.write_result("Категорія", category.name, created)

        for name in RECIPIENTS:
            recipient, created = Recipient.objects.get_or_create(name=name)
            self.write_result("Отримувач", recipient.name, created)

    def seed_items_and_balances(self):
        categories = {
            category.name: category
            for category in Category.objects.filter(name__in=CATEGORIES)
        }
        units = {
            unit.symbol: unit
            for unit in Unit.objects.filter(
                symbol__in=[symbol for _, symbol in UNITS]
            )
        }
        locations = {
            (location.warehouse.name, location.name): location
            for location in Location.objects.select_related("warehouse").filter(
                warehouse__name__in=WAREHOUSES, name__in=LOCATIONS
            )
        }

        for index, (
            name,
            category_name,
            unit_symbol,
            qty,
            warehouse_name,
            location_name,
        ) in enumerate(ITEMS, start=1):
            internal_code = f"{DEMO_CODE_PREFIX}{index:04d}"
            item, created = Item.objects.get_or_create(
                internal_code=internal_code,
                defaults={
                    "name": name,
                    "category": categories[category_name],
                    "unit": units[unit_symbol],
                    "description": "Демо-номенклатура для локального тестування.",
                },
            )
            self.write_result(
                "Номенклатура", f"{item.internal_code} {item.name}", created
            )

            location = locations[(warehouse_name, location_name)]
            if StockBalance.objects.filter(item=item, location=location).exists():
                self.stdout.write(
                    f"Залишок: {item.internal_code} @ {location} — вже існував."
                )
                continue

            create_initial_balance(
                item=item, location=location, qty=qty, comment=DEMO_COMMENT
            )
            self.stdout.write(
                f"Залишок: {item.internal_code} @ {location} — створено {qty}."
            )

    def seed_users(self, *, reset_passwords):
        User = get_user_model()
        for username, (password, group_name) in TEST_USERS.items():
            user, created = User.objects.get_or_create(username=username)
            if created or reset_passwords:
                user.set_password(password)
                user.save(update_fields=["password"] if not created else None)
            group = Group.objects.get(name=group_name)
            user.groups.add(group)
            self.write_result("Користувач", username, created)
            if reset_passwords and not created:
                self.stdout.write(f"Пароль: {username} — оновлено.")

    def clear_demo_data(self, *, clear_users):
        demo_items = Item.objects.filter(internal_code__startswith=DEMO_CODE_PREFIX)
        demo_item_ids = list(demo_items.values_list("id", flat=True))

        if not demo_item_ids:
            self.stdout.write("DEMO-номенклатуру не знайдено.")
        else:
            movements = StockMovement.objects.filter(item_id__in=demo_item_ids)
            balances = StockBalance.objects.filter(item_id__in=demo_item_ids)
            movement_count = movements.count()
            balance_count = balances.count()
            item_count = len(demo_item_ids)
            try:
                with transaction.atomic():
                    movements.delete()
                    balances.delete()
                    demo_items.delete()
            except ProtectedError as exc:
                raise CommandError(
                    "Не вдалося безпечно видалити DEMO-дані через повʼязані записи. "
                    "Реальні дані не змінено. Деталі: " + str(exc)
                ) from exc
            self.stdout.write(
                self.style.SUCCESS(
                    "Видалено DEMO-дані: "
                    f"номенклатура {item_count}, "
                    f"залишки {balance_count}, рухи {movement_count}."
                )
            )

        if clear_users:
            User = get_user_model()
            deleted_count, _ = User.objects.filter(
                username__in=TEST_USERS.keys()
            ).delete()
            self.stdout.write(
                self.style.SUCCESS(f"Видалено тестових користувачів: {deleted_count}.")
            )
