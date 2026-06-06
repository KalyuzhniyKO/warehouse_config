from decimal import Decimal
from pathlib import Path
from unittest import mock
from django import forms
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone, translation
from io import BytesIO, StringIO
from django.urls import reverse
from ..forms import (
    CategoryForm,
    ItemForm,
    LocationForm,
    StockBalanceFilterForm,
    StockIssueForm,
    StockReceiveForm,
    StockReturnForm,
    StockTransferForm,
)
from .i18n_test_utils import compile_test_messages
from .warehouse_access_utils import grant_warehouse_access
from ..services.locations import (
    DEFAULT_LOCATION_NAME,
    get_default_location_for_warehouse,
)
from ..models import (
    AuditLog,
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
    UsagePlace,
    Warehouse,
)

class StockTransferFormTestBase(TestCase):
    def setUp(self):
        self.unit = Unit.objects.create(name="Form unit", symbol="fu")
        self.item = Item.objects.create(name="Form item", unit=self.unit)
        self.source_warehouse = Warehouse.objects.create(name="Form source warehouse")
        self.destination_warehouse = Warehouse.objects.create(
            name="Form destination warehouse"
        )
        self.source_location = Location.objects.create(
            warehouse=self.source_warehouse, name="Form source location"
        )
        self.destination_location = Location.objects.create(
            warehouse=self.destination_warehouse, name="Form destination location"
        )
        self.other_location = Location.objects.create(
            warehouse=self.destination_warehouse, name="Form other location"
        )

    def form_data(self, **overrides):
        data = {
            "item": self.item.pk,
            "source_warehouse": self.source_warehouse.pk,
            "source_location": self.source_location.pk,
            "destination_warehouse": self.destination_warehouse.pk,
            "destination_location": self.destination_location.pk,
            "qty": "1.000",
            "comment": "Form transfer",
            "occurred_at": "2026-01-15T10:30",
        }
        data.update(overrides)
        return data

class StockIssueInterfaceTestBase(TestCase):
    def setUp(self):
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
        grant_warehouse_access(
            self.admin,
            [self.warehouse, self.other_warehouse],
            can_delegate=True,
        )
        grant_warehouse_access(
            self.storekeeper,
            [self.warehouse, self.other_warehouse],
        )
        grant_warehouse_access(
            self.auditor,
            [self.warehouse, self.other_warehouse],
        )
        self.location = Location.objects.create(warehouse=self.warehouse, name="A1")
        self.other_location = Location.objects.create(
            warehouse=self.other_warehouse, name="B1"
        )
        self.recipient = Recipient.objects.create(name="Цех 1")
        self.usage_place = UsagePlace.objects.create(name="Sales")
        self.inactive_usage_place = UsagePlace.objects.create(
            name="Archived place", is_active=False
        )
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

    def assert_self_service_shell(self, response):
        html = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn('<main class="col-12">', html)
        self.assertNotIn('<aside class="col-lg-2 d-none d-lg-block">', html)
        self.assertNotIn('class="sidebar-link', html)
        self.assertNotIn('<button class="navbar-toggler"', html)
        self.assertNotIn('<div class="collapse navbar-collapse" id="mainNavbar">', html)
        for href in [
            reverse("stock_transfer"),
            reverse("stock_writeoff"),
            reverse("stock_initial"),
            reverse("inventory_list"),
            reverse("stockbalance_list"),
            reverse("movement_list"),
            reverse("item_list"),
            reverse("category_list"),
            reverse("unit_list"),
            reverse("warehouse_list"),
            reverse("location_list"),
            reverse("recipient_list"),
            reverse("printer_list"),
            reverse("labeltemplate_list"),
            reverse("management_dashboard"),
        ]:
            self.assertNotIn(f'href="{href}"', html)

class StockOperationWorkflowTestBase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        compile_test_messages(locales=["en", "uk"])

    def setUp(self):
        translation.activate("uk")
        call_command("init_roles", stdout=StringIO())
        self.user = get_user_model().objects.create_user("workflow", password="pass")
        self.user.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.client.force_login(self.user)
        self.unit = Unit.objects.create(name="Штука workflow", symbol="wf")
        self.item = Item.objects.create(name="Workflow item", unit=self.unit)
        self.warehouse = Warehouse.objects.create(name="Workflow warehouse")
        self.location = Location.objects.create(
            warehouse=self.warehouse, name="Workflow location"
        )
        self.destination_warehouse = Warehouse.objects.create(
            name="Workflow destination"
        )
        self.destination_location = Location.objects.create(
            warehouse=self.destination_warehouse, name="Workflow destination location"
        )
        grant_warehouse_access(
            self.user,
            [self.warehouse, self.destination_warehouse],
            can_delegate=True,
        )
        self.recipient = Recipient.objects.create(name="Workflow recipient")
        self.usage_place = UsagePlace.objects.create(name="Sales")
        self.inactive_usage_place = UsagePlace.objects.create(
            name="Archived place", is_active=False
        )
        StockMovement.objects.create(
            movement_type=StockMovement.MovementType.OUT,
            item=self.item,
            qty=Decimal("100.000"),
            source_warehouse=self.warehouse,
            source_location=self.location,
            recipient=self.recipient,
        )

    def _transfer_data(self, **overrides):
        data = {
            "item": self.item.pk,
            "source_warehouse": self.warehouse.pk,
            "source_location": self.location.pk,
            "destination_warehouse": self.destination_warehouse.pk,
            "destination_location": self.destination_location.pk,
            "qty": "2.000",
            "comment": "Insufficient transfer",
            "occurred_at": timezone.now().strftime("%Y-%m-%dT%H:%M"),
        }
        data.update(overrides)
        return data

    def disable_locations(self):
        settings = SystemSettings.get_solo()
        settings.use_locations = False
        settings.save(update_fields=["use_locations", "updated_at"])

class StockOperationFormsSmokeTestBase(TestCase):
    def setUp(self):
        call_command("init_roles", stdout=StringIO())
        self.user = get_user_model().objects.create_user(username="ops", password="pw")
        self.user.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.client.force_login(self.user)

class ListLayoutSmokeTestBase(TestCase):
    def setUp(self):
        call_command("init_roles", stdout=StringIO())
        user = get_user_model().objects.create_user("layout", password="pw")
        user.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.client.force_login(user)
