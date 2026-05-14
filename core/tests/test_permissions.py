from decimal import Decimal
from pathlib import Path
from unittest import mock
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone
from io import BytesIO, StringIO
from django.urls import reverse
from ..forms import CategoryForm, ItemForm, LocationForm, StockBalanceFilterForm, StockTransferForm
from ..models import (
    BarcodeRegistry,
    BarcodeSequence,
    Category,
    InventoryCount,
    InventoryCountLine,
    Item,
    LabelTemplate,
    Location,
    PrintJob,
    Printer,
    Recipient,
    StockBalance,
    StockMovement,
    Unit,
    Warehouse,
)


class ManagementPermissionTests(TestCase):

    def setUp(self):
        call_command("init_roles", stdout=StringIO())
        self.admin = get_user_model().objects.create_user(
            username="admin", password="pw"
        )
        self.admin.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.storekeeper = get_user_model().objects.create_user(
            username="keeper", password="pw"
        )
        self.storekeeper.groups.add(Group.objects.get(name="Комірник"))
        self.auditor = get_user_model().objects.create_user(
            username="auditor", password="pw"
        )
        self.superuser = get_user_model().objects.create_superuser(
            username="root", password="pw", email="root@example.com"
        )
        self.auditor.groups.add(Group.objects.get(name="Перегляд / аудитор"))
        self.unit = Unit.objects.create(name="Штука", symbol="шт")
        self.category = Category.objects.create(name="Кабель")
        self.item = Item.objects.create(
            name="Кабель ВВГ",
            internal_code="CBL-1",
            category=self.category,
            unit=self.unit,
        )
        self.other_item = Item.objects.create(
            name="Автомат",
            internal_code="AUTO-1",
            category=self.category,
            unit=self.unit,
        )
        self.warehouse = Warehouse.objects.create(name="Основний склад")
        self.other_warehouse = Warehouse.objects.create(name="Резервний склад")
        self.location = Location.objects.create(warehouse=self.warehouse, name="A1")
        self.other_location = Location.objects.create(
            warehouse=self.other_warehouse, name="B1"
        )
        self.recipient = Recipient.objects.create(name="Цех 1")
        self.balance = StockBalance.objects.create(
            item=self.item, location=self.location, qty=Decimal("7.000")
        )
        StockBalance.objects.create(
            item=self.other_item, location=self.other_location, qty=Decimal("0.000")
        )
        StockMovement.objects.create(
            movement_type=StockMovement.MovementType.IN,
            item=self.item,
            qty=Decimal("10.000"),
            destination_location=self.location,
            occurred_at=timezone.datetime(
                2026, 1, 10, 12, tzinfo=timezone.get_current_timezone()
            ),
        )
        StockMovement.objects.create(
            movement_type=StockMovement.MovementType.OUT,
            item=self.item,
            qty=Decimal("3.000"),
            source_location=self.location,
            recipient=self.recipient,
            occurred_at=timezone.datetime(
                2026, 1, 12, 12, tzinfo=timezone.get_current_timezone()
            ),
        )
        StockMovement.objects.create(
            movement_type=StockMovement.MovementType.IN,
            item=self.other_item,
            qty=Decimal("5.000"),
            destination_location=self.other_location,
            occurred_at=timezone.datetime(
                2026, 2, 1, 12, tzinfo=timezone.get_current_timezone()
            ),
        )

    def test_storekeeper_menu_hides_management_analytics_and_admin(self):
        self.client.force_login(self.storekeeper)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Склад самообслуговування")
        for label in [
            "Керування",
            "Аналітика",
            "Адмін-панель",
            "Категорії",
            "Одиниці виміру",
            "Принтери",
            "Шаблони етикеток",
        ]:
            self.assertNotContains(response, label)

    def test_storekeeper_cannot_open_analytics_urls(self):
        self.client.force_login(self.storekeeper)
        response = self.client.get(reverse("management_analytics"))
        self.assertEqual(response.status_code, 403)
        response = self.client.get(reverse("analytics"))
        self.assertEqual(response.status_code, 403)

    def test_storekeeper_cannot_manage_users(self):
        self.client.force_login(self.storekeeper)
        response = self.client.get(reverse("management_users"))
        self.assertEqual(response.status_code, 403)

    def test_auditor_cannot_edit_directories(self):
        self.client.force_login(self.auditor)
        response = self.client.post(
            reverse("unit_create"), {"name": "Кг", "symbol": "кг", "is_active": "on"}
        )
        self.assertEqual(response.status_code, 403)

    def test_auditor_cannot_create_stock_issue_or_transfer(self):
        self.client.force_login(self.auditor)
        response = self.client.get(reverse("stock_issue"))
        self.assertEqual(response.status_code, 403)

        response = self.client.post(reverse("stock_issue"), {})
        self.assertEqual(response.status_code, 403)

        response = self.client.get(reverse("stock_transfer"))
        self.assertEqual(response.status_code, 403)

        response = self.client.post(reverse("stock_transfer"), {})
        self.assertEqual(response.status_code, 403)

        response = self.client.get(reverse("stock_receive"))
        self.assertEqual(response.status_code, 403)

        response = self.client.post(reverse("stock_receive"), {})
        self.assertEqual(response.status_code, 403)

        response = self.client.get(reverse("stock_writeoff"))
        self.assertEqual(response.status_code, 403)

        response = self.client.post(reverse("stock_writeoff"), {})
        self.assertEqual(response.status_code, 403)


class DashboardPermissionTests(TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        call_command("compilemessages", verbosity=0)

    def setUp(self):
        call_command("init_roles", stdout=StringIO())
        User = get_user_model()
        self.admin = User.objects.create_user(username="dash-admin", password="pw")
        self.admin.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.storekeeper = User.objects.create_user(
            username="dash-storekeeper", password="pw"
        )
        self.storekeeper.groups.add(Group.objects.get(name="Комірник"))
        self.auditor = User.objects.create_user(username="dash-auditor", password="pw")
        self.auditor.groups.add(Group.objects.get(name="Перегляд / аудитор"))

    def dashboard_for(self, user, path=None):
        from django.utils import translation

        translation.activate("en" if path and path.startswith("/en/") else "uk")
        self.client.force_login(user)
        return self.client.get(path or reverse("dashboard"))

    def tearDown(self):
        from django.utils import translation

        translation.activate("uk")

    def test_admin_dashboard_shows_stock_transfer_card(self):
        response = self.dashboard_for(self.admin, "/uk/")

        self.assertContains(response, "Переміщення товару")

    def test_user_self_service_dashboard_hides_stock_transfer_card(self):
        response = self.dashboard_for(self.storekeeper, "/uk/")

        self.assertNotContains(response, "Перемістити товар")

    def test_auditor_dashboard_hides_stock_transfer_card(self):
        response = self.dashboard_for(self.auditor, "/uk/")

        self.assertNotContains(response, "Переміщення товару")

    def test_storekeeper_can_open_ukrainian_stock_transfer_page(self):
        response = self.dashboard_for(self.storekeeper, "/uk/stock/transfer/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Переміщення товару")

    def test_admin_dashboard_contains_required_groups_and_operations(self):
        response = self.dashboard_for(self.admin)

        self.assertContains(response, "Складські операції")
        self.assertContains(response, "Контроль")
        self.assertContains(response, "Довідники")
        for label in [
            "Прихід товару",
            "Видача товару",
            "Переміщення товару",
            "Початкові залишки",
            "Інвентаризація",
        ]:
            self.assertContains(response, label)

    def test_storekeeper_dashboard_contains_workplace_actions_without_admin_items(self):
        response = self.dashboard_for(self.storekeeper, "/uk/")

        self.assertTemplateUsed(response, "core/storekeeper_workplace.html")
        self.assertTrue(response.context["is_storekeeper_workplace"])
        html = response.content.decode()
        for label in [
            "Склад самообслуговування",
            "Оберіть дію",
            "Взяти товар",
            "Повернути товар",
            "Зіскануйте товар і зафіксуйте видачу зі складу.",
            "Зіскануйте товар і зафіксуйте повернення на склад.",
        ]:
            self.assertContains(response, label)
        main_html = html[html.index('<main class="col-12">'):]
        for label in [
            "Категорії",
            "Одиниці виміру",
            "Принтери",
            "Шаблони етикеток",
            "Аналітика",
            "Керування",
            "Отримувачі",
            "Довідники",
            "Рухи товарів",
            "Залишки",
            "Інвентаризація",
            "Складські налаштування",
            "Початкові залишки",
            "Знайти товар",
            "Відкрити",
            "Перемістити товар",
            "Списати товар",
            "Провести інвентаризацію",
            "Перевірити залишки",
            "Надрукувати етикетку",
            "Пошук товару",
            "Назва, внутрішній код або штрихкод",
            "Робоче місце комірника",
            "Комірник",
            "Допомога",
        ]:
            self.assertNotIn(label, main_html)

    def test_storekeeper_workplace_primary_cards_are_links(self):
        response = self.dashboard_for(self.storekeeper, "/uk/")
        html = response.content.decode()

        for label, url_name in [
            ("Взяти товар", "stock_issue"),
            ("Повернути товар", "stock_receive"),
        ]:
            self.assertIn(
                f'<a class="card self-service-action-card text-decoration-none text-reset" href="{reverse(url_name)}"',
                html,
            )
            self.assertIn(
                f'<a class="card self-service-action-card text-decoration-none text-reset" href="{reverse(url_name)}" aria-label="{label}"',
                html,
            )
            self.assertIn(label, html)
        main_html = html[html.index('<main class="col-12">'):]
        for label in ["Перемістити товар", "Списати товар", "Прийняти товар", "Видача товару", "Повернення товару"]:
            self.assertNotIn(label, main_html)

    def test_storekeeper_workplace_hides_sidebar_and_uses_full_width(self):
        response = self.dashboard_for(self.storekeeper, "/uk/")
        html = response.content.decode()

        self.assertContains(response, "Склад самообслуговування")
        self.assertNotContains(response, "Навігація")
        self.assertIn('<main class="col-12">', html)
        self.assertNotIn('<main class="col-lg-10">', html)
        for label in ["Взяти товар", "Повернути товар"]:
            self.assertContains(response, label)
        main_html = html[html.index('<main class="col-12">'):]
        for label in ["Перемістити товар", "Списати товар", "Прийняти товар", "Видача товару", "Повернення товару"]:
            self.assertNotIn(label, main_html)

    def test_storekeeper_internal_page_keeps_sidebar(self):
        response = self.dashboard_for(self.storekeeper, "/uk/stock/receive/")
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Навігація")
        self.assertIn('<main class="col-lg-10">', html)

    def test_warehouse_admin_keeps_full_dashboard(self):
        response = self.dashboard_for(self.admin, "/uk/")

        self.assertTemplateUsed(response, "core/dashboard.html")
        self.assertTemplateNotUsed(response, "core/storekeeper_workplace.html")
        self.assertFalse(response.context["is_storekeeper_workplace"])
        self.assertContains(response, "Навігація")
        self.assertContains(response, "Головна")
        self.assertContains(response, "Довідники")
        self.assertNotContains(response, "Склад самообслуговування")
        self.assertNotContains(response, "Пошук товару")
        self.assertNotContains(response, "autofocus")

    def test_auditor_dashboard_is_view_only(self):
        response = self.dashboard_for(self.auditor)

        for label in ["Прихід товару", "Видача товару", "Переміщення товару", "Початкові залишки"]:
            self.assertNotContains(response, label)
        for label in ["Залишки", "Рухи товарів", "Інвентаризація"]:
            self.assertContains(response, label)

    def test_storekeeper_sidebar_hides_recipients(self):
        response = self.dashboard_for(self.storekeeper)

        self.assertNotContains(response, "Отримувачі")
        self.assertNotContains(response, "Довідники")

    def test_auditor_sidebar_hides_create_operations(self):
        response = self.dashboard_for(self.auditor)

        for label in ["Прихід товару", "Видача товару", "Переміщення товару", "Початкові залишки"]:
            self.assertNotContains(response, label)
        self.assertContains(response, "Інвентаризація")

    def test_mobile_menu_hides_management_for_storekeeper(self):
        response = self.dashboard_for(self.storekeeper)
        html = response.content.decode()

        self.assertNotIn('navbar-nav me-auto mb-2 mb-lg-0 d-lg-none', html)
        self.assertNotIn('navbar-toggler', html)
        self.assertNotIn("Керування", html)
        self.assertNotIn("management/", html)
