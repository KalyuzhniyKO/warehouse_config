from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from core.models import Item, Location, StockBalance, Unit, Warehouse

from .warehouse_access_utils import grant_warehouse_access


class BarcodeLookupWorkflowTests(TestCase):
    def setUp(self):
        call_command("init_roles", stdout=StringIO())
        self.user = get_user_model().objects.create_user("barcode-user", password="pw")
        self.user.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.client.force_login(self.user)
        self.unit = Unit.objects.create(name="Piece", symbol="pc")
        self.item = Item.objects.create(name="Visible stock item", unit=self.unit)
        self.warehouse = Warehouse.objects.create(name="Visible warehouse")
        self.location = Location.objects.create(warehouse=self.warehouse, name="A1")
        grant_warehouse_access(self.user, self.warehouse, can_delegate=True)
        StockBalance.objects.create(
            item=self.item,
            location=self.location,
            qty=Decimal("5.000"),
        )
        self.scanned_barcode = f"  {self.item.barcode.barcode.lower()}  "

    def test_issue_finds_barcode_visible_in_stock_balances(self):
        response = self.client.get(
            reverse("stock_issue"),
            {"barcode": self.scanned_barcode},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["scanned_item"], self.item)
        self.assertEqual(response.context["form"].initial["item"], self.item)
        self.assertNotContains(response, "Товар за цим штрихкодом не знайдено.")

    def test_return_finds_barcode_visible_in_stock_balances(self):
        response = self.client.get(
            reverse("stock_return"),
            {"barcode": self.scanned_barcode},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["scanned_item"], self.item)
        self.assertEqual(response.context["form"].initial["item"], self.item)
        self.assertNotContains(response, "Товар за цим штрихкодом не знайдено.")

    def test_transfer_scanner_finds_barcode_visible_in_stock_balances(self):
        response = self.client.get(
            reverse("barcode_lookup"),
            {"barcode": self.scanned_barcode},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["found"])
        self.assertEqual(response.json()["id"], self.item.pk)

    def test_inventory_scanner_finds_barcode_visible_in_stock_balances(self):
        response = self.client.get(
            reverse("barcode_lookup"),
            {"barcode": self.scanned_barcode},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["type"], "item")
        self.assertEqual(response.json()["barcode"], self.item.barcode.barcode)
