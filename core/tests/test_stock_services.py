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
from ..forms import (
    CategoryForm,
    ItemForm,
    LocationForm,
    StockBalanceFilterForm,
    StockIssueForm,
    StockTransferForm,
)
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


_MESSAGES_COMPILED = None


def _messages_compiled():
    """True if locale catalogs were built; False if gettext msgfmt is missing."""
    global _MESSAGES_COMPILED
    if _MESSAGES_COMPILED is not None:
        return _MESSAGES_COMPILED
    from django.core.management.base import CommandError

    try:
        call_command("compilemessages", verbosity=0)
        _MESSAGES_COMPILED = True
    except CommandError:
        _MESSAGES_COMPILED = False
    return _MESSAGES_COMPILED


class StockServiceTests(TestCase):
    def setUp(self):
        self.unit = Unit.objects.create(name="Kilogram", symbol="kg")
        self.item = Item.objects.create(name="Service item", unit=self.unit)
        self.recipient = Recipient.objects.create(name="Maintenance team")
        self.warehouse = Warehouse.objects.create(name="Service warehouse")
        self.source_location = Location.objects.create(
            warehouse=self.warehouse,
            name="Source",
        )
        self.target_location = Location.objects.create(
            warehouse=self.warehouse,
            name="Target",
        )

    def get_balance_qty(self, location=None):
        location = location or self.source_location
        return StockBalance.objects.get(item=self.item, location=location).qty


    def test_find_best_stock_balance_for_issue_returns_largest_positive_active_balance(self):
        from ..services.stock import find_best_stock_balance_for_issue

        inactive_balance = StockBalance.objects.create(
            item=self.item,
            location=self.source_location,
            qty=Decimal("20.000"),
            is_active=False,
        )
        larger_balance = StockBalance.objects.create(
            item=self.item, location=self.target_location, qty=Decimal("8.000")
        )

        balance = find_best_stock_balance_for_issue(self.item)

        self.assertEqual(balance, larger_balance)
        self.assertNotEqual(balance, inactive_balance)

    def test_find_best_stock_balance_for_issue_returns_none_without_positive_balance(self):
        from ..services.stock import find_best_stock_balance_for_issue

        StockBalance.objects.create(
            item=self.item, location=self.source_location, qty=Decimal("0.000")
        )

        self.assertIsNone(find_best_stock_balance_for_issue(self.item))

    def test_receive_stock_increases_balance_and_creates_movement(self):
        from ..services.stock import receive_stock

        movement = receive_stock(
            item=self.item,
            location=self.source_location,
            qty=Decimal("10.000"),
        )

        self.assertEqual(self.get_balance_qty(), Decimal("10.000"))
        self.assertEqual(movement.movement_type, StockMovement.MovementType.IN)
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_issue_stock_decreases_balance_and_creates_movement(self):
        from ..services.stock import issue_stock, receive_stock

        receive_stock(
            item=self.item, location=self.source_location, qty=Decimal("10.000")
        )
        movement = issue_stock(
            item=self.item,
            location=self.source_location,
            qty=Decimal("3.250"),
            recipient=self.recipient,
            issue_reason=StockMovement.IssueReason.SALE,
        )

        self.assertEqual(self.get_balance_qty(), Decimal("6.750"))
        self.assertEqual(movement.movement_type, StockMovement.MovementType.OUT)
        self.assertEqual(movement.recipient, self.recipient)
        self.assertEqual(movement.issue_reason, StockMovement.IssueReason.SALE)
        self.assertEqual(StockMovement.objects.count(), 2)

    def test_issue_stock_stores_repair_reason_and_department(self):
        from ..services.stock import issue_stock, receive_stock

        receive_stock(
            item=self.item, location=self.source_location, qty=Decimal("4.000")
        )
        movement = issue_stock(
            item=self.item,
            location=self.source_location,
            qty=Decimal("1.000"),
            recipient=self.recipient,
            issue_reason=StockMovement.IssueReason.REPAIR,
            department="  Repair shop  ",
            document_number="REQ-7",
        )

        self.assertEqual(movement.issue_reason, StockMovement.IssueReason.REPAIR)
        self.assertEqual(movement.department, "Repair shop")
        self.assertEqual(movement.document_number, "REQ-7")

    def test_cannot_issue_more_than_available(self):
        from ..services.stock import InsufficientStockError, issue_stock, receive_stock

        receive_stock(
            item=self.item, location=self.source_location, qty=Decimal("2.000")
        )

        with self.assertRaises(InsufficientStockError):
            issue_stock(
                item=self.item,
                location=self.source_location,
                qty=Decimal("2.001"),
                recipient=self.recipient,
            )

        self.assertEqual(self.get_balance_qty(), Decimal("2.000"))
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_issue_stock_without_recipient_raises_missing_recipient_error(self):
        from django.utils import translation

        from ..services.stock import MissingRecipientError, issue_stock, receive_stock

        receive_stock(
            item=self.item, location=self.source_location, qty=Decimal("2.000")
        )
        with translation.override("uk"):
            with self.assertRaises(MissingRecipientError) as ctx:
                issue_stock(
                    item=self.item,
                    location=self.source_location,
                    qty=Decimal("1.000"),
                )
            self.assertEqual(
                str(ctx.exception),
                "Для видачі товару потрібно вказати отримувача.",
            )
        if not _messages_compiled():
            self.skipTest("GNU gettext msgfmt is not available; skipping EN assertion")
        with translation.override("en"):
            with self.assertRaises(MissingRecipientError) as ctx:
                issue_stock(
                    item=self.item,
                    location=self.source_location,
                    qty=Decimal("1.000"),
                )
            self.assertEqual(
                str(ctx.exception),
                "Recipient is required to issue stock.",
            )

    def test_stock_issue_form_invalid_without_recipient_uk(self):
        from django.utils import translation

        with translation.override("uk"):
            form = StockIssueForm(
                data={
                    "item": self.item.pk,
                    "warehouse": self.warehouse.pk,
                    "location": self.source_location.pk,
                    "qty": "1.000",
                    "issue_reason": StockMovement.IssueReason.OTHER,
                    "department": "",
                    "document_number": "",
                    "comment": "",
                    "occurred_at": "2026-01-15T10:00",
                }
            )
            self.assertFalse(form.is_valid())
            self.assertIn("recipient", form.errors)
            self.assertEqual(
                str(form.errors["recipient"][0]),
                "Оберіть, хто бере товар.",
            )

    def test_stock_issue_form_invalid_without_recipient_en(self):
        from django.utils import translation

        if not _messages_compiled():
            self.skipTest("GNU gettext msgfmt is not available; skipping EN assertion")

        with translation.override("en"):
            form = StockIssueForm(
                data={
                    "item": self.item.pk,
                    "warehouse": self.warehouse.pk,
                    "location": self.source_location.pk,
                    "qty": "1.000",
                    "issue_reason": StockMovement.IssueReason.OTHER,
                    "department": "",
                    "document_number": "",
                    "comment": "",
                    "occurred_at": "2026-01-15T10:00",
                }
            )
            self.assertFalse(form.is_valid())
            self.assertIn("recipient", form.errors)
            self.assertEqual(
                str(form.errors["recipient"][0]),
                "Choose who takes the item.",
            )

    def test_writeoff_stock_decreases_balance_and_creates_movement(self):
        from ..services.stock import receive_stock, writeoff_stock

        receive_stock(
            item=self.item, location=self.source_location, qty=Decimal("5.000")
        )
        occurred_at = timezone.datetime(
            2026, 1, 20, 10, 30, tzinfo=timezone.get_current_timezone()
        )
        movement = writeoff_stock(
            item=self.item,
            location=self.source_location,
            qty=Decimal("1.125"),
            occurred_at=occurred_at,
        )

        self.assertEqual(self.get_balance_qty(), Decimal("3.875"))
        self.assertEqual(movement.movement_type, StockMovement.MovementType.WRITEOFF)
        self.assertEqual(movement.source_location, self.source_location)
        self.assertIsNone(movement.destination_location)
        self.assertEqual(movement.occurred_at, occurred_at)
        self.assertEqual(StockMovement.objects.count(), 2)

    def test_cannot_writeoff_more_than_available(self):
        from ..services.stock import (
            InsufficientStockError,
            receive_stock,
            writeoff_stock,
        )

        receive_stock(
            item=self.item, location=self.source_location, qty=Decimal("1.000")
        )

        with self.assertRaises(InsufficientStockError):
            writeoff_stock(
                item=self.item,
                location=self.source_location,
                qty=Decimal("1.001"),
            )

        self.assertEqual(self.get_balance_qty(), Decimal("1.000"))
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_transfer_decreases_source_and_increases_target(self):
        from ..services.stock import receive_stock, transfer_stock

        receive_stock(
            item=self.item, location=self.source_location, qty=Decimal("8.000")
        )
        movement = transfer_stock(
            item=self.item,
            source_location=self.source_location,
            target_location=self.target_location,
            qty=Decimal("2.500"),
        )

        self.assertEqual(self.get_balance_qty(self.source_location), Decimal("5.500"))
        self.assertEqual(self.get_balance_qty(self.target_location), Decimal("2.500"))
        self.assertEqual(movement.movement_type, StockMovement.MovementType.TRANSFER)
        self.assertEqual(movement.source_location, self.source_location)
        self.assertEqual(movement.destination_location, self.target_location)
        self.assertEqual(StockMovement.objects.count(), 2)

    def test_cannot_transfer_to_same_location(self):
        from ..services.stock import (
            SameLocationTransferError,
            receive_stock,
            transfer_stock,
        )

        receive_stock(
            item=self.item, location=self.source_location, qty=Decimal("3.000")
        )

        with self.assertRaises(SameLocationTransferError):
            transfer_stock(
                item=self.item,
                source_location=self.source_location,
                target_location=self.source_location,
                qty=Decimal("1.000"),
            )

        self.assertEqual(self.get_balance_qty(self.source_location), Decimal("3.000"))
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_cannot_transfer_more_than_available(self):
        from ..services.stock import InsufficientStockError, receive_stock, transfer_stock

        receive_stock(
            item=self.item, location=self.source_location, qty=Decimal("2.000")
        )

        with self.assertRaises(InsufficientStockError):
            transfer_stock(
                item=self.item,
                source_location=self.source_location,
                target_location=self.target_location,
                qty=Decimal("2.001"),
            )

        self.assertEqual(self.get_balance_qty(self.source_location), Decimal("2.000"))
        self.assertFalse(
            StockBalance.objects.filter(
                item=self.item, location=self.target_location, qty__gt=0
            ).exists()
        )
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_transfer_records_passed_occurred_at(self):
        from ..services.stock import receive_stock, transfer_stock

        occurred_at = timezone.make_aware(timezone.datetime(2026, 1, 15, 10, 30))
        receive_stock(
            item=self.item, location=self.source_location, qty=Decimal("4.000")
        )
        movement = transfer_stock(
            item=self.item,
            source_location=self.source_location,
            target_location=self.target_location,
            qty=Decimal("1.000"),
            occurred_at=occurred_at,
        )

        self.assertEqual(movement.occurred_at, occurred_at)

    def test_adjust_stock_sets_target_quantity_and_creates_movement(self):
        from ..services.stock import adjust_stock, receive_stock

        receive_stock(
            item=self.item, location=self.source_location, qty=Decimal("4.000")
        )
        increase = adjust_stock(
            item=self.item,
            location=self.source_location,
            target_qty=Decimal("7.750"),
        )
        decrease = adjust_stock(
            item=self.item,
            location=self.source_location,
            target_qty=Decimal("2.125"),
        )

        self.assertEqual(self.get_balance_qty(), Decimal("2.125"))
        self.assertEqual(increase.movement_type, StockMovement.MovementType.ADJUSTMENT)
        self.assertEqual(increase.qty, Decimal("3.750"))
        self.assertEqual(increase.destination_location, self.source_location)
        self.assertEqual(decrease.qty, Decimal("5.625"))
        self.assertEqual(decrease.source_location, self.source_location)
        self.assertEqual(StockMovement.objects.count(), 3)

    def test_initial_balance_return_and_adjustment_create_movements(self):
        from ..services.stock import create_initial_balance, return_stock

        initial = create_initial_balance(
            item=self.item,
            location=self.source_location,
            qty=Decimal("1.000"),
        )
        returned = return_stock(
            item=self.item,
            location=self.source_location,
            qty=Decimal("2.000"),
            recipient=self.recipient,
        )

        self.assertEqual(self.get_balance_qty(), Decimal("3.000"))
        self.assertEqual(
            initial.movement_type, StockMovement.MovementType.INITIAL_BALANCE
        )
        self.assertEqual(returned.movement_type, StockMovement.MovementType.RETURN)
        self.assertEqual(returned.recipient, self.recipient)
        self.assertEqual(StockMovement.objects.count(), 2)

    def test_quantity_is_stored_with_three_decimal_places(self):
        from ..services.stock import receive_stock

        movement = receive_stock(
            item=self.item,
            location=self.source_location,
            qty=Decimal("1.2345"),
        )

        self.assertEqual(self.get_balance_qty(), Decimal("1.235"))
        self.assertEqual(movement.qty, Decimal("1.235"))
