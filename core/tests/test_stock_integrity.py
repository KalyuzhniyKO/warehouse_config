from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from core.models import (
    Item,
    Location,
    Recipient,
    StockBalance,
    StockMovement,
    Unit,
    UsagePlace,
    Warehouse,
)
from core.services.stock import (
    InsufficientStockError,
    issue_stock,
    receive_stock,
    transfer_stock,
    writeoff_stock,
)
from core.tests.warehouse_access_utils import grant_warehouse_access


class StockBalanceConstraintTests(TransactionTestCase):
    def setUp(self):
        self.unit = Unit.objects.create(name="Constraint unit", symbol="cu")
        self.warehouse = Warehouse.objects.create(name="Constraint warehouse")
        self.location = Location.objects.create(
            warehouse=self.warehouse, name="Constraint location"
        )

    def create_balance(self, *, name, qty):
        item = Item.objects.create(name=name, unit=self.unit)
        return StockBalance.objects.create(
            item=item,
            warehouse=self.warehouse,
            location=self.location,
            qty=qty,
        )

    def test_database_rejects_negative_balance(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_balance(name="Negative balance", qty=Decimal("-0.001"))

    def test_database_allows_zero_balance(self):
        balance = self.create_balance(name="Zero balance", qty=Decimal("0.000"))
        self.assertEqual(balance.qty, Decimal("0.000"))

    def test_database_allows_positive_balance(self):
        balance = self.create_balance(name="Positive balance", qty=Decimal("1.000"))
        self.assertEqual(balance.qty, Decimal("1.000"))


class StockServiceNonNegativeTests(TestCase):
    def setUp(self):
        self.unit = Unit.objects.create(name="Service constraint unit", symbol="scu")
        self.item = Item.objects.create(name="Service constraint item", unit=self.unit)
        self.recipient = Recipient.objects.create(name="Constraint recipient")
        self.source_warehouse = Warehouse.objects.create(name="Constraint source")
        self.destination_warehouse = Warehouse.objects.create(name="Constraint destination")
        self.source_location = Location.objects.create(
            warehouse=self.source_warehouse, name="Constraint source location"
        )
        self.destination_location = Location.objects.create(
            warehouse=self.destination_warehouse, name="Constraint destination location"
        )

    def seed_stock(self):
        receive_stock(item=self.item, location=self.source_location, qty=Decimal("1.000"))

    def assert_source_balance_unchanged(self):
        self.assertEqual(
            StockBalance.objects.get(
                item=self.item, warehouse=self.source_warehouse
            ).qty,
            Decimal("1.000"),
        )

    def test_issue_cannot_make_balance_negative(self):
        self.seed_stock()
        with self.assertRaises(InsufficientStockError):
            issue_stock(
                item=self.item,
                location=self.source_location,
                qty=Decimal("1.001"),
                recipient=self.recipient,
            )
        self.assert_source_balance_unchanged()

    def test_writeoff_cannot_make_balance_negative(self):
        self.seed_stock()
        with self.assertRaises(InsufficientStockError):
            writeoff_stock(
                item=self.item,
                location=self.source_location,
                qty=Decimal("1.001"),
            )
        self.assert_source_balance_unchanged()

    def test_transfer_cannot_make_balance_negative(self):
        self.seed_stock()
        with self.assertRaises(InsufficientStockError):
            transfer_stock(
                item=self.item,
                source_location=self.source_location,
                destination_location=self.destination_location,
                qty=Decimal("1.001"),
            )
        self.assert_source_balance_unchanged()
        self.assertFalse(
            StockBalance.objects.filter(
                item=self.item, warehouse=self.destination_warehouse, qty__gt=0
            ).exists()
        )


class StockOperationDuplicateSubmitTests(TestCase):
    def setUp(self):
        call_command("init_roles", verbosity=0)
        self.user = get_user_model().objects.create_user("integrity-user", password="pw")
        self.user.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.client.force_login(self.user)
        self.unit = Unit.objects.create(name="Integrity unit", symbol="iu")
        self.item = Item.objects.create(name="Integrity item", unit=self.unit)
        self.recipient = Recipient.objects.create(name="Integrity recipient")
        self.usage_place = UsagePlace.objects.create(name="Integrity usage place")
        self.source_warehouse = Warehouse.objects.create(name="Integrity source")
        self.destination_warehouse = Warehouse.objects.create(name="Integrity destination")
        self.source_location = Location.objects.create(
            warehouse=self.source_warehouse, name="Integrity source location"
        )
        self.destination_location = Location.objects.create(
            warehouse=self.destination_warehouse, name="Integrity destination location"
        )
        grant_warehouse_access(
            self.user,
            [self.source_warehouse, self.destination_warehouse],
            can_delegate=True,
        )

    def operation_time(self):
        return timezone.now().strftime("%Y-%m-%dT%H:%M")

    def test_issue_duplicate_submit_creates_one_movement_and_decreases_once(self):
        receive_stock(item=self.item, location=self.source_location, qty=Decimal("5.000"))
        response = self.client.get(
            f'{reverse("stock_issue")}?barcode={self.item.barcode.barcode}'
        )
        data = {
            "operation_token": response.context["operation_token"],
            "item": self.item.pk,
            "warehouse": self.source_warehouse.pk,
            "location": self.source_location.pk,
            "qty": "2.000",
            "issue_reason": StockMovement.IssueReason.OTHER,
            "department": self.usage_place.pk,
            "recipient": self.recipient.pk,
            "document_number": "",
            "comment": "",
            "occurred_at": self.operation_time(),
        }

        first_response = self.client.post(reverse("stock_issue"), data)
        second_response = self.client.post(reverse("stock_issue"), data)

        self.assertEqual(first_response.status_code, 302)
        self.assertEqual(second_response["Location"], first_response["Location"])
        self.assertEqual(
            StockMovement.objects.filter(
                movement_type=StockMovement.MovementType.OUT
            ).count(),
            1,
        )
        self.assertEqual(
            StockBalance.objects.get(item=self.item, warehouse=self.source_warehouse).qty,
            Decimal("3.000"),
        )

    def test_receive_duplicate_submit_creates_one_movement_and_increases_once(self):
        response = self.client.get(
            f'{reverse("stock_receive")}?barcode={self.item.barcode.barcode}'
        )
        data = {
            "operation_token": response.context["operation_token"],
            "item": self.item.pk,
            "warehouse": self.source_warehouse.pk,
            "location": self.source_location.pk,
            "qty": "2.000",
            "comment": "",
            "occurred_at": self.operation_time(),
        }

        first_response = self.client.post(reverse("stock_receive"), data)
        second_response = self.client.post(reverse("stock_receive"), data)

        self.assertEqual(first_response.status_code, 302)
        self.assertEqual(second_response["Location"], first_response["Location"])
        self.assertEqual(
            StockMovement.objects.filter(
                movement_type=StockMovement.MovementType.IN
            ).count(),
            1,
        )
        self.assertEqual(
            StockBalance.objects.get(item=self.item, warehouse=self.source_warehouse).qty,
            Decimal("2.000"),
        )

    def test_invalid_submission_does_not_consume_token(self):
        receive_stock(item=self.item, location=self.source_location, qty=Decimal("5.000"))
        response = self.client.get(reverse("stock_writeoff"))
        token = response.context["operation_token"]
        data = {
            "operation_token": token,
            "item": self.item.pk,
            "warehouse": self.source_warehouse.pk,
            "location": self.source_location.pk,
            "qty": "",
            "writeoff_reason": "other",
            "document_number": "",
            "comment": "",
            "occurred_at": self.operation_time(),
        }

        invalid_response = self.client.post(reverse("stock_writeoff"), data)
        data["qty"] = "1.000"
        valid_response = self.client.post(reverse("stock_writeoff"), data)

        self.assertEqual(invalid_response.status_code, 200)
        self.assertEqual(invalid_response.context["operation_token"], token)
        self.assertEqual(valid_response.status_code, 302)
        self.assertEqual(
            StockMovement.objects.filter(
                movement_type=StockMovement.MovementType.WRITEOFF
            ).count(),
            1,
        )

    def test_new_get_creates_fresh_token(self):
        first_token = self.client.get(reverse("stock_transfer")).context["operation_token"]
        second_token = self.client.get(reverse("stock_transfer")).context["operation_token"]
        self.assertNotEqual(first_token, second_token)

    def test_transfer_writeoff_and_initial_forms_render_submission_token(self):
        for url_name in ["stock_transfer", "stock_writeoff", "stock_initial"]:
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name))
                self.assertContains(response, 'name="operation_token"')
                self.assertTrue(response.context["operation_token"])

    def test_normal_single_transfer_submission_still_works(self):
        receive_stock(item=self.item, location=self.source_location, qty=Decimal("5.000"))
        response = self.client.get(reverse("stock_transfer"))
        data = {
            "operation_token": response.context["operation_token"],
            "item": self.item.pk,
            "source_warehouse": self.source_warehouse.pk,
            "source_location": self.source_location.pk,
            "destination_warehouse": self.destination_warehouse.pk,
            "destination_location": self.destination_location.pk,
            "qty": "1.000",
            "comment": "",
            "occurred_at": self.operation_time(),
        }
        post_response = self.client.post(reverse("stock_transfer"), data)

        self.assertEqual(post_response.status_code, 302)
        self.assertEqual(
            StockMovement.objects.filter(
                movement_type=StockMovement.MovementType.TRANSFER
            ).count(),
            1,
        )

    def test_transfer_duplicate_submit_creates_one_movement(self):
        receive_stock(item=self.item, location=self.source_location, qty=Decimal("5.000"))
        response = self.client.get(reverse("stock_transfer"))
        data = {
            "operation_token": response.context["operation_token"],
            "item": self.item.pk,
            "source_warehouse": self.source_warehouse.pk,
            "source_location": self.source_location.pk,
            "destination_warehouse": self.destination_warehouse.pk,
            "destination_location": self.destination_location.pk,
            "qty": "1.000",
            "comment": "Duplicate transfer",
            "occurred_at": self.operation_time(),
        }

        self.client.post(reverse("stock_transfer"), data)
        self.client.post(reverse("stock_transfer"), data)

        self.assertEqual(
            StockMovement.objects.filter(
                movement_type=StockMovement.MovementType.TRANSFER,
                comment="Duplicate transfer",
            ).count(),
            1,
        )

    def test_writeoff_duplicate_submit_creates_one_movement(self):
        receive_stock(item=self.item, location=self.source_location, qty=Decimal("5.000"))
        response = self.client.get(reverse("stock_writeoff"))
        data = {
            "operation_token": response.context["operation_token"],
            "item": self.item.pk,
            "warehouse": self.source_warehouse.pk,
            "location": self.source_location.pk,
            "qty": "1.000",
            "writeoff_reason": "other",
            "document_number": "DUP-WO",
            "comment": "",
            "occurred_at": self.operation_time(),
        }

        self.client.post(reverse("stock_writeoff"), data)
        self.client.post(reverse("stock_writeoff"), data)

        self.assertEqual(
            StockMovement.objects.filter(
                movement_type=StockMovement.MovementType.WRITEOFF,
                comment__contains="DUP-WO",
            ).count(),
            1,
        )

    def test_initial_balance_duplicate_submit_creates_one_movement(self):
        response = self.client.get(reverse("stock_initial"))
        data = {
            "operation_token": response.context["operation_token"],
            "item": self.item.pk,
            "warehouse": self.source_warehouse.pk,
            "location": self.source_location.pk,
            "qty": "2.000",
            "comment": "Duplicate initial",
            "occurred_at": self.operation_time(),
        }

        self.client.post(reverse("stock_initial"), data)
        self.client.post(reverse("stock_initial"), data)

        self.assertEqual(
            StockMovement.objects.filter(
                movement_type=StockMovement.MovementType.INITIAL_BALANCE,
                comment="Duplicate initial",
            ).count(),
            1,
        )
