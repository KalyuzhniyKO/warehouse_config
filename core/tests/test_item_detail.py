from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Category, Item, Location, StockBalance, StockMovement, Unit, Warehouse

from .warehouse_access_utils import grant_warehouse_access


class ItemDetailTests(TestCase):
    def setUp(self):
        call_command("init_roles", stdout=StringIO())
        self.user = get_user_model().objects.create_user("item-detail", password="pw")
        self.user.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.client.force_login(self.user)
        self.unit = Unit.objects.create(name="Piece", symbol="pc")
        self.category = Category.objects.create(name="Materials")
        self.item = Item.objects.create(
            name="Detail item",
            internal_code="DETAIL-1",
            category=self.category,
            unit=self.unit,
        )
        self.warehouse = Warehouse.objects.create(name="Allowed warehouse")
        self.other_warehouse = Warehouse.objects.create(name="Hidden warehouse")
        self.location = Location.objects.create(warehouse=self.warehouse, name="A1")
        self.other_location = Location.objects.create(
            warehouse=self.other_warehouse,
            name="B1",
        )
        grant_warehouse_access(self.user, self.warehouse, can_delegate=True)
        StockBalance.objects.create(
            item=self.item,
            location=self.location,
            qty=Decimal("5.000"),
        )
        StockBalance.objects.create(
            item=self.item,
            location=self.other_location,
            qty=Decimal("9.000"),
        )
        self.receive = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.IN,
            item=self.item,
            qty=Decimal("7.000"),
            destination_location=self.location,
            occurred_at=timezone.now() - timezone.timedelta(hours=2),
            document_number="RECEIVE-VISIBLE",
        )
        self.issue = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.OUT,
            item=self.item,
            qty=Decimal("2.000"),
            source_location=self.location,
            occurred_at=timezone.now() - timezone.timedelta(hours=1),
            document_number="ISSUE-VISIBLE",
        )
        StockMovement.objects.create(
            movement_type=StockMovement.MovementType.IN,
            item=self.item,
            qty=Decimal("9.000"),
            destination_location=self.other_location,
            document_number="HIDDEN",
        )

    def test_item_list_links_to_item_detail(self):
        response = self.client.get(reverse("item_list"))

        self.assertContains(response, reverse("item_detail", args=[self.item.pk]))

    def test_item_detail_shows_card_stock_and_movements(self):
        response = self.client.get(reverse("item_detail", args=[self.item.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_stock"], Decimal("5.000"))
        self.assertEqual(response.context["last_receive"], self.receive)
        self.assertEqual(response.context["last_issue"], self.issue)
        self.assertEqual(list(response.context["recent_movements"]), [self.issue, self.receive])
        for value in [
            self.item.name,
            self.item.barcode.barcode,
            self.category.name,
            self.unit.symbol,
            self.warehouse.name,
            "RECEIVE-VISIBLE",
            "ISSUE-VISIBLE",
        ]:
            self.assertContains(response, value)
        self.assertNotContains(response, self.other_warehouse.name)
        self.assertNotContains(response, "HIDDEN")

    def test_item_detail_limits_recent_movements_to_twenty(self):
        for index in range(25):
            StockMovement.objects.create(
                movement_type=StockMovement.MovementType.OUT,
                item=self.item,
                qty=Decimal("1.000"),
                source_location=self.location,
                document_number=f"RECENT-{index:02d}",
                occurred_at=timezone.now() + timezone.timedelta(minutes=index),
            )

        response = self.client.get(reverse("item_detail", args=[self.item.pk]))

        self.assertEqual(len(response.context["recent_movements"]), 20)

    def test_item_detail_uses_existing_login_permission(self):
        self.client.logout()

        response = self.client.get(reverse("item_detail", args=[self.item.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])
