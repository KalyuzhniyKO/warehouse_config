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
    SystemSettings,
    Unit,
    Warehouse,
)


class ManagementInterfaceTests(TestCase):

    def setUp(self):
        from django.utils import translation

        translation.activate("uk")
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

    def test_management_requires_login(self):
        response = self.client.get(reverse("management_dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_warehouse_admin_menu_shows_management(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Керування")
        self.assertNotContains(response, "Адмін-панель")

    def test_warehouse_admin_opens_management_pages(self):
        self.client.force_login(self.admin)
        for url_name in ["management_dashboard", "management_help", "management_analytics"]:
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 200, url_name)

    def test_warehouse_admin_sees_structured_management_dashboard(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("management_dashboard"))

        self.assertEqual(response.status_code, 200)
        for text in [
            "Адміністрування складу",
            "Довідники",
            "Номенклатура",
            "Склади",
            "Локації",
            "Користувачі та доступ",
            "Користувачі та ролі",
            "Етикетки",
            "Контроль і звіти",
            "Система",
        ]:
            self.assertContains(response, text)

    def test_auditor_cannot_open_management_dashboard(self):
        self.client.force_login(self.auditor)
        response = self.client.get(reverse("management_dashboard"))

        self.assertEqual(response.status_code, 403)
        self.assertNotContains(
            response, "Адміністрування складу", status_code=403
        )

    def test_superuser_sees_system_management_cards(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("management_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Система")
        self.assertContains(response, "Налаштування системи")
        self.assertContains(response, "Довідка адміністратора")

    def test_superuser_sees_technical_django_admin_card(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("management_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Технічна Django Admin")
        self.assertContains(response, "Тільки для технічного обслуговування")

    def test_init_roles_creates_expected_groups(self):
        for name in ["Адміністратор складу", "Комірник", "Перегляд / аудитор"]:
            self.assertTrue(Group.objects.filter(name=name).exists())

    def test_documentation_files_exist(self):
        from pathlib import Path

        docs = Path(__file__).resolve().parents[2] / "docs"
        for filename in [
            "USER_GUIDE.md",
            "ADMIN_GUIDE.md",
            "START_WAREHOUSE_FROM_ZERO.md",
        ]:
            self.assertTrue((docs / filename).exists())

    def test_management_help_page_shows_instruction_sections(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("management_help"))
        self.assertEqual(response.status_code, 200)
        for text in [
            "Як почати склад з нуля",
            "Інструкція користувача",
            "Інструкція адміністратора",
            "Типові помилки",
            "Backup і відновлення",
            "Принтери і друк етикеток",
            "Штрихкоди",
            "Прихід товару",
            "Початковий залишок",
            "Рухи товарів",
        ]:
            self.assertContains(response, text)

    def test_user_help_page_shows_only_user_instruction(self):
        self.client.force_login(self.storekeeper)
        response = self.client.get(reverse("help"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Інструкція користувача")
        self.assertNotContains(response, "Інструкція адміністратора")
        self.assertNotContains(response, "Backup і відновлення")

    @override_settings(AUTH_PASSWORD_VALIDATORS=[])
    def test_simple_passwords_are_not_blocked_when_validators_disabled(self):
        validate_password("1", user=self.storekeeper)

    def test_help_page_opens(self):
        self.client.force_login(self.auditor)
        response = self.client.get(reverse("help"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Центр допомоги")

    def test_system_settings_get_solo_creates_default_record(self):
        SystemSettings.objects.all().delete()

        settings = SystemSettings.get_solo()

        self.assertIsNotNone(settings.pk)
        self.assertTrue(settings.use_locations)
        self.assertEqual(SystemSettings.objects.count(), 1)

    def test_system_settings_get_solo_reuses_existing_record(self):
        SystemSettings.objects.all().delete()
        first = SystemSettings.get_solo()

        second = SystemSettings.get_solo()

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(SystemSettings.objects.count(), 1)

    def test_system_settings_get_solo_returns_first_by_id(self):
        SystemSettings.objects.all().delete()
        first = SystemSettings.objects.create(use_locations=False)
        SystemSettings.objects.create(use_locations=True)

        settings = SystemSettings.get_solo()

        self.assertEqual(settings.pk, first.pk)
        self.assertFalse(settings.use_locations)

    def test_warehouse_admin_can_open_settings_page(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("management_settings"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Налаштування системи")
        self.assertContains(response, "Використовувати локації")
        self.assertContains(response, "Зберегти")

    def test_auditor_cannot_open_settings_page(self):
        self.client.force_login(self.auditor)

        response = self.client.get(reverse("management_settings"))

        self.assertEqual(response.status_code, 403)

    def test_post_can_disable_and_enable_use_locations(self):
        self.client.force_login(self.admin)

        response = self.client.post(reverse("management_settings"), data={}, follow=True)

        self.assertEqual(response.status_code, 200)
        settings = SystemSettings.get_solo()
        self.assertFalse(settings.use_locations)
        self.assertContains(response, "Налаштування збережено.")

        response = self.client.post(
            reverse("management_settings"), data={"use_locations": "on"}, follow=True
        )

        self.assertEqual(response.status_code, 200)
        settings.refresh_from_db()
        self.assertTrue(settings.use_locations)
        self.assertContains(response, "Налаштування збережено.")

    def test_english_settings_page_uses_english_terms_only(self):
        self.client.force_login(self.admin)

        response = self.client.get("/en/management/settings/")
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("System settings", html)
        self.assertIn("Use locations", html)
        for phrase in [
            "Налаштування системи",
            "Використовувати локації",
            "Зберегти",
            "Налаштування збережено.",
            "Якщо вимкнено",
        ]:
            self.assertNotIn(phrase, html)
