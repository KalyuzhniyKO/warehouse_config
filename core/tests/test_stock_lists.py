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


class StockBalanceListTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="ui-user", password="test-password"
        )
        call_command("init_roles", stdout=StringIO())
        self.user.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.client.force_login(self.user)
        self.unit = Unit.objects.create(name="Штука", symbol="шт")
        self.category = Category.objects.create(name="Матеріали")
        self.recipient = Recipient.objects.create(name="Цех 1")
        self.item = Item.objects.create(
            name="Болт М8",
            internal_code="BOLT-M8",
            category=self.category,
            unit=self.unit,
        )
        self.warehouse = Warehouse.objects.create(name="Основний склад")
        self.location = Location.objects.create(warehouse=self.warehouse, name="A-01")
        self.balance = StockBalance.objects.create(
            item=self.item, location=self.location, qty=Decimal("5.000")
        )

    def test_stock_balance_list_opens_and_filters_by_search(self):
        response = self.client.get(reverse("stockbalance_list"), {"q": "BOLT"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Болт М8")


class StockMovementListTests(TestCase):

    def setUp(self):
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
        self.destination_warehouse = Warehouse.objects.create(name="Workflow destination")
        self.destination_location = Location.objects.create(
            warehouse=self.destination_warehouse, name="Workflow destination location"
        )

    def test_transfer_movement_is_visible_in_movement_list(self):
        StockMovement.objects.create(
            movement_type=StockMovement.MovementType.TRANSFER,
            item=self.item,
            qty=Decimal("1.000"),
            source_location=self.location,
            destination_location=self.destination_location,
            comment="Visible transfer",
        )

        response = self.client.get(reverse("movement_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Переміщення")
        self.assertContains(response, "Workflow location")
        self.assertContains(response, "Workflow destination location")
        self.assertContains(response, "Visible transfer")

    def test_movement_page_available_and_filter_works(self):
        from ..services.stock import receive_stock

        receive_stock(item=self.item, location=self.location, qty=Decimal("2.000"), comment="Find me")
        response = self.client.get(reverse("movement_list"), {"q": "Workflow item"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Find me")
        response = self.client.get(reverse("movement_list"), {"q": "nothing"})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Find me")
