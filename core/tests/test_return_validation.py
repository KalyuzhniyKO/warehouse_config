from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from core.forms import StockReturnForm
from core.models import Item, Location, Recipient, StockBalance, StockMovement, Unit, UsagePlace, Warehouse
from core.services.stock import (
    MissingReturnRecipientError,
    ReturnQuantityExceededError,
    cancel_stock_movement,
    get_available_return_qty,
    issue_stock,
    receive_stock,
    return_stock,
)
from core.tests.warehouse_access_utils import grant_warehouse_access


class ReturnValidationTests(TestCase):
    def setUp(self):
        call_command("init_roles", stdout=StringIO())
        self.superuser = get_user_model().objects.create_superuser(
            "return-root", "return-root@example.com", "pw"
        )
        self.user = get_user_model().objects.create_user("return-user", password="pw")
        self.user.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.client.force_login(self.user)
        self.unit = Unit.objects.create(name="Return unit", symbol="ru")
        self.item = Item.objects.create(name="Return item", unit=self.unit)
        self.other_item = Item.objects.create(name="Other return item", unit=self.unit)
        self.recipient = Recipient.objects.create(name="Return recipient")
        self.other_recipient = Recipient.objects.create(name="Other recipient")
        self.usage_place = UsagePlace.objects.create(name="Return usage place")
        self.warehouse = Warehouse.objects.create(name="Return warehouse")
        self.location = Location.objects.create(
            warehouse=self.warehouse, name="Return location"
        )
        grant_warehouse_access(self.user, self.warehouse, can_delegate=True)
        receive_stock(item=self.item, location=self.location, qty=Decimal("20.000"))

    def issue(self, qty="5.000", recipient=None):
        return issue_stock(
            item=self.item,
            location=self.location,
            qty=Decimal(qty),
            recipient=recipient or self.recipient,
        )

    def return_item(self, qty, **kwargs):
        return return_stock(
            item=self.item,
            warehouse=self.warehouse,
            location=kwargs.pop("location", self.location),
            qty=Decimal(qty),
            recipient=kwargs.pop("recipient", self.recipient),
            **kwargs,
        )

    def form_data(self, **overrides):
        data = {
            "item": self.item.pk,
            "warehouse": self.warehouse.pk,
            "location": self.location.pk,
            "qty": "1.000",
            "recipient": self.recipient.pk,
            "comment": "",
            "occurred_at": "2026-01-15T10:00",
        }
        data.update(overrides)
        return data

    def test_service_requires_recipient_for_normal_return(self):
        with self.assertRaises(MissingReturnRecipientError):
            return_stock(
                item=self.item,
                location=self.location,
                qty=Decimal("1.000"),
            )

    def test_form_requires_recipient_for_normal_return(self):
        form = StockReturnForm(data=self.form_data(recipient=""))
        self.assertFalse(form.is_valid())
        self.assertIn("recipient", form.errors)

    def test_cannot_return_item_never_issued_to_recipient(self):
        with self.assertRaises(ReturnQuantityExceededError):
            self.return_item("1.000")
        self.assertEqual(
            StockMovement.objects.filter(
                movement_type=StockMovement.MovementType.RETURN
            ).count(),
            0,
        )

    def test_form_rejects_item_never_issued_to_recipient(self):
        form = StockReturnForm(data=self.form_data())
        self.assertFalse(form.is_valid())
        self.assertIn("qty", form.errors)
        self.assertIn("Неможливо повернути більше", str(form.errors["qty"]))

    def test_cannot_return_more_than_issued(self):
        self.issue("5.000")
        with self.assertRaises(ReturnQuantityExceededError):
            self.return_item("5.001")
        self.assertEqual(get_available_return_qty(self.item, self.recipient), Decimal("5.000"))

    def test_can_return_exactly_issued_quantity(self):
        self.issue("5.000")
        movement = self.return_item("5.000")
        self.assertEqual(movement.qty, Decimal("5.000"))
        self.assertEqual(get_available_return_qty(self.item, self.recipient), Decimal("0.000"))

    def test_partial_return_reduces_remaining_available_quantity(self):
        self.issue("5.000")
        self.return_item("2.000")
        self.assertEqual(get_available_return_qty(self.item, self.recipient), Decimal("3.000"))
        self.return_item("3.000")
        self.assertEqual(get_available_return_qty(self.item, self.recipient), Decimal("0.000"))

    def test_cancelled_issue_is_not_available_for_return(self):
        issue = self.issue("5.000")
        cancel_stock_movement(
            movement=issue, cancelled_by=self.superuser, reason="Cancel issue"
        )
        self.assertEqual(get_available_return_qty(self.item, self.recipient), Decimal("0.000"))
        with self.assertRaises(ReturnQuantityExceededError):
            self.return_item("1.000")

    def test_cancelled_return_restores_availability(self):
        self.issue("5.000")
        returned = self.return_item("3.000")
        self.assertEqual(get_available_return_qty(self.item, self.recipient), Decimal("2.000"))
        cancel_stock_movement(
            movement=returned, cancelled_by=self.superuser, reason="Cancel return"
        )
        self.assertEqual(get_available_return_qty(self.item, self.recipient), Decimal("5.000"))

    def test_return_validation_does_not_require_location(self):
        self.issue("2.000")
        movement = return_stock(
            item=self.item,
            warehouse=self.warehouse,
            location=None,
            qty=Decimal("2.000"),
            recipient=self.recipient,
        )
        self.assertIsNone(movement.destination_location)

    def test_return_form_shows_available_quantity_after_validation(self):
        self.issue("5.000")
        form = StockReturnForm(data=self.form_data(qty="6.000"))
        self.assertFalse(form.is_valid())
        self.assertEqual(form.fields["qty"].help_text, "Доступно до повернення: 5.000")

    def test_return_double_submit_still_creates_one_return(self):
        self.issue("5.000")
        get_response = self.client.get(
            f'{reverse("stock_return")}?barcode={self.item.barcode.barcode}'
        )
        data = self.form_data(
            operation_token=get_response.context["operation_token"],
            qty="2.000",
            occurred_at=get_response.context["form"].initial["occurred_at"],
        )
        first_response = self.client.post(reverse("stock_return"), data)
        second_response = self.client.post(reverse("stock_return"), data)
        self.assertEqual(first_response.status_code, 302)
        self.assertEqual(second_response["Location"], first_response["Location"])
        self.assertEqual(
            StockMovement.objects.filter(
                movement_type=StockMovement.MovementType.RETURN,
                recipient=self.recipient,
            ).count(),
            1,
        )

    def test_stock_balance_non_negative_constraint_remains_active(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                StockBalance.objects.create(
                    item=self.other_item,
                    warehouse=self.warehouse,
                    location=self.location,
                    qty=Decimal("-0.001"),
                )

    def test_legacy_unmatched_return_requires_explicit_opt_out(self):
        movement = return_stock(
            item=self.other_item,
            warehouse=self.warehouse,
            qty=Decimal("1.000"),
            allow_unmatched_return=True,
        )
        self.assertIsNone(movement.recipient)
