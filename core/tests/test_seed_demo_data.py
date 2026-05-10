from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase

from core.management.commands.seed_demo_data import TEST_USERS
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


class SeedDemoDataCommandTests(TestCase):
    def call_seed(self, *args):
        out = StringIO()
        call_command("seed_demo_data", *args, stdout=out)
        return out.getvalue()

    def test_seed_demo_data_creates_directories_items_barcodes_and_stock(self):
        self.call_seed()

        self.assertTrue(Warehouse.objects.filter(name="Основний склад").exists())
        self.assertTrue(Warehouse.objects.filter(name="Резервний склад").exists())

        for warehouse_name in ["Основний склад", "Резервний склад"]:
            warehouse = Warehouse.objects.get(name=warehouse_name)
            for location_name in ["Основна локація", "A-01", "A-02", "B-01", "Z-01"]:
                self.assertTrue(
                    Location.objects.filter(
                        warehouse=warehouse,
                        name=location_name,
                    ).exists()
                )

        self.assertTrue(Location.objects.filter(name="Основна локація").exists())

        for symbol in ["шт", "кг", "м", "л"]:
            self.assertTrue(Unit.objects.filter(symbol=symbol).exists())

        for name in [
            "Електрика",
            "Механіка",
            "Пневматика",
            "Кріплення",
            "Витратні матеріали",
        ]:
            self.assertTrue(Category.objects.filter(name=name).exists())

        for name in [
            "Цех сітки",
            "Цех оцинкування",
            "Ремонтна дільниця",
            "Технічна служба",
        ]:
            self.assertTrue(Recipient.objects.filter(name=name).exists())

        demo_items = Item.objects.filter(internal_code__startswith="DEMO-")
        self.assertEqual(demo_items.count(), 10)
        self.assertEqual(demo_items.filter(barcode__isnull=False).count(), 10)
        self.assertGreaterEqual(
            StockBalance.objects.filter(item__in=demo_items).count(), 10
        )
        self.assertGreaterEqual(
            StockMovement.objects.filter(
                item__in=demo_items,
                movement_type=StockMovement.MovementType.INITIAL_BALANCE,
            ).count(),
            10,
        )

    def test_seed_demo_data_is_idempotent_for_items_and_balances(self):
        self.call_seed()
        item_count = Item.objects.filter(internal_code__startswith="DEMO-").count()
        balance_count = StockBalance.objects.filter(
            item__internal_code__startswith="DEMO-"
        ).count()
        movement_count = StockMovement.objects.filter(
            item__internal_code__startswith="DEMO-",
            movement_type=StockMovement.MovementType.INITIAL_BALANCE,
        ).count()

        self.call_seed()

        self.assertEqual(
            Item.objects.filter(internal_code__startswith="DEMO-").count(), item_count
        )
        self.assertEqual(
            StockBalance.objects.filter(item__internal_code__startswith="DEMO-").count(),
            balance_count,
        )
        self.assertEqual(
            StockMovement.objects.filter(
                item__internal_code__startswith="DEMO-",
                movement_type=StockMovement.MovementType.INITIAL_BALANCE,
            ).count(),
            movement_count,
        )

    def test_create_users_creates_users_with_correct_groups(self):
        self.call_seed("--create-users")
        User = get_user_model()

        expected_groups = {
            "warehouse_admin": WAREHOUSE_ADMIN_GROUP,
            "storekeeper": STOREKEEPER_GROUP,
            "auditor": AUDITOR_GROUP,
        }
        for username, group_name in expected_groups.items():
            user = User.objects.get(username=username)
            self.assertTrue(user.check_password(username))
            self.assertTrue(user.groups.filter(name=group_name).exists())

    def test_reset_passwords_updates_existing_demo_user_passwords(self):
        call_command("init_roles", stdout=StringIO())
        User = get_user_model()
        for username, (_, group_name) in TEST_USERS.items():
            user = User.objects.create_user(username=username, password="custom-password")
            user.groups.add(Group.objects.get(name=group_name))

        self.call_seed("--create-users")
        self.assertTrue(
            User.objects.get(username="warehouse_admin").check_password("custom-password")
        )

        self.call_seed("--create-users", "--reset-passwords")
        for username in TEST_USERS:
            self.assertTrue(User.objects.get(username=username).check_password(username))

    def test_clear_demo_does_not_delete_non_demo_item(self):
        unit = Unit.objects.create(name="Test unit", symbol="test")
        item = Item.objects.create(name="Real item", internal_code="REAL-0001", unit=unit)
        self.call_seed()

        self.call_seed("--clear-demo")

        self.assertTrue(Item.objects.filter(pk=item.pk).exists())
        self.assertFalse(
            Item.objects.filter(internal_code__startswith="DEMO-").exists()
        )

    def test_clear_demo_with_clear_users_deletes_only_test_users(self):
        self.call_seed("--create-users")
        User = get_user_model()
        real_user = User.objects.create_user(username="real_user", password="pw")

        self.call_seed("--clear-demo", "--clear-users")

        self.assertTrue(User.objects.filter(pk=real_user.pk).exists())
        for username in TEST_USERS:
            self.assertFalse(User.objects.filter(username=username).exists())
