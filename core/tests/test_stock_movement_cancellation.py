from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from core.models import AuditLog, Item, Location, Recipient, StockBalance, StockMovement, Unit, Warehouse
from core.services import analytics as analytics_service
from core.tests.warehouse_access_utils import grant_warehouse_access
from core.services.stock import (
    InsufficientStockError,
    StockServiceError,
    adjust_stock,
    cancel_stock_movement,
    issue_stock,
    receive_stock,
    return_stock,
    transfer_stock,
    writeoff_stock,
)


class StockMovementCancellationTests(TestCase):
    def setUp(self):
        call_command("init_roles", stdout=StringIO())
        User = get_user_model()
        self.superuser = User.objects.create_superuser(
            username="super", password="pw", email="super@example.com"
        )
        self.admin = User.objects.create_user(username="admin", password="pw")
        self.admin.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.user = User.objects.create_user(username="user", password="pw")
        self.unit = Unit.objects.create(name="Piece", symbol="pc")
        self.item = Item.objects.create(name="Cable", unit=self.unit)
        self.warehouse = Warehouse.objects.create(name="Main")
        grant_warehouse_access(self.admin, self.warehouse, can_delegate=True)
        grant_warehouse_access(self.user, self.warehouse)
        self.source = Location.objects.create(warehouse=self.warehouse, name="Source")
        self.destination = Location.objects.create(warehouse=self.warehouse, name="Destination")
        self.recipient = Recipient.objects.create(name="Worker")

    def balance(self, location):
        return StockBalance.objects.get(item=self.item, location=location).qty

    def cancel(self, movement, reason="Created by mistake"):
        return cancel_stock_movement(
            movement=movement, cancelled_by=self.superuser, reason=reason
        )

    def test_superuser_can_open_cancel_page(self):
        movement = receive_stock(item=self.item, location=self.destination, qty=5)
        self.client.force_login(self.superuser)

        response = self.client.get(reverse("stock_movement_cancel", args=[movement.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Підтвердити анулювання")
        self.assertContains(response, "Причина анулювання")

    def test_warehouse_admin_cannot_open_cancel_page(self):
        movement = receive_stock(item=self.item, location=self.destination, qty=5)
        self.client.force_login(self.admin)

        response = self.client.get(reverse("stock_movement_cancel", args=[movement.pk]))

        self.assertEqual(response.status_code, 403)

    def test_regular_user_cannot_open_cancel_page(self):
        movement = receive_stock(item=self.item, location=self.destination, qty=5)
        self.client.force_login(self.user)

        response = self.client.get(reverse("stock_movement_cancel", args=[movement.pk]))

        self.assertEqual(response.status_code, 403)

    def test_cancelling_in_decreases_destination_balance(self):
        movement = receive_stock(item=self.item, location=self.destination, qty=5)

        reversal = self.cancel(movement)

        self.assertEqual(self.balance(self.destination), Decimal("0.000"))
        movement.refresh_from_db()
        self.assertTrue(movement.is_cancelled)
        self.assertEqual(movement.cancellation_movement, reversal)
        self.assertEqual(reversal.reversal_of, movement)

    def test_cancelling_out_increases_source_balance(self):
        receive_stock(item=self.item, location=self.source, qty=10)
        movement = issue_stock(
            item=self.item,
            location=self.source,
            qty=4,
            recipient=self.recipient,
        )

        self.cancel(movement)

        self.assertEqual(self.balance(self.source), Decimal("10.000"))

    def test_cancelling_return_decreases_destination_balance(self):
        StockMovement.objects.create(
            movement_type=StockMovement.MovementType.OUT,
            item=self.item,
            qty=3,
            source_location=self.source,
            recipient=self.recipient,
        )
        movement = return_stock(
            item=self.item,
            location=self.destination,
            qty=3,
            recipient=self.recipient,
        )

        self.cancel(movement)

        self.assertEqual(self.balance(self.destination), Decimal("0.000"))

    def test_cancelling_writeoff_increases_source_balance(self):
        receive_stock(item=self.item, location=self.source, qty=8)
        movement = writeoff_stock(item=self.item, location=self.source, qty=2)

        self.cancel(movement)

        self.assertEqual(self.balance(self.source), Decimal("8.000"))

    def test_cancelling_transfer_increases_source_and_decreases_destination(self):
        receive_stock(item=self.item, location=self.source, qty=9)
        movement = transfer_stock(
            item=self.item,
            source_location=self.source,
            target_location=self.destination,
            qty=4,
        )

        self.cancel(movement)

        self.assertEqual(self.balance(self.source), Decimal("9.000"))
        self.assertEqual(self.balance(self.destination), Decimal("0.000"))

    def test_cancelling_adjustment_reverses_destination_side(self):
        movement = adjust_stock(item=self.item, location=self.destination, quantity_delta=6)

        self.cancel(movement)

        self.assertEqual(self.balance(self.destination), Decimal("0.000"))

    def test_cancelling_adjustment_reverses_source_side(self):
        receive_stock(item=self.item, location=self.source, qty=6)
        movement = adjust_stock(item=self.item, location=self.source, quantity_delta=-2)

        self.cancel(movement)

        self.assertEqual(self.balance(self.source), Decimal("6.000"))

    def test_cancellation_requires_reason(self):
        movement = receive_stock(item=self.item, location=self.destination, qty=5)

        with self.assertRaises(StockServiceError):
            cancel_stock_movement(
                movement=movement, cancelled_by=self.superuser, reason="   "
            )

    def test_cannot_cancel_already_cancelled_movement(self):
        movement = receive_stock(item=self.item, location=self.destination, qty=5)
        self.cancel(movement)

        with self.assertRaises(StockServiceError):
            self.cancel(movement, reason="Again")

    def test_cannot_cancel_if_reversal_would_make_balance_negative(self):
        movement = receive_stock(item=self.item, location=self.destination, qty=5)
        issue_stock(
            item=self.item,
            location=self.destination,
            qty=5,
            recipient=self.recipient,
        )

        with self.assertRaisesMessage(
            InsufficientStockError,
            "Неможливо анулювати рух, бо на складі вже недостатньо залишку для зворотної операції.",
        ):
            self.cancel(movement)

    def test_cancellation_creates_audit_log(self):
        movement = receive_stock(item=self.item, location=self.destination, qty=5)

        reversal = self.cancel(movement, reason="Duplicate")

        log = AuditLog.objects.get(action="stock_movement.cancelled")
        self.assertEqual(log.actor, self.superuser)
        self.assertEqual(log.changes["original_movement_id"], movement.pk)
        self.assertEqual(log.changes["cancellation_movement_id"], reversal.pk)
        self.assertEqual(log.changes["reason"], "Duplicate")

    def test_movement_journal_marks_cancelled_movement(self):
        movement = receive_stock(item=self.item, location=self.destination, qty=5)
        self.cancel(movement, reason="Wrong item")
        self.client.force_login(self.admin)

        response = self.client.get(reverse("movement_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Анулювано")
        self.assertContains(response, "Wrong item")

    def test_cancel_button_visible_only_for_superuser(self):
        movement = receive_stock(item=self.item, location=self.destination, qty=5)
        url = reverse("stock_movement_cancel", args=[movement.pk])

        self.client.force_login(self.superuser)
        response = self.client.get(reverse("movement_list"))
        self.assertContains(response, url)

        self.client.force_login(self.admin)
        response = self.client.get(reverse("movement_list"))
        self.assertNotContains(response, url)

    def test_print_slip_shows_cancelled_status(self):
        movement = receive_stock(item=self.item, location=self.destination, qty=5)
        self.cancel(movement, reason="Duplicate")
        self.client.force_login(self.admin)

        response = self.client.get(reverse("stock_movement_print", args=[movement.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Анулювано")
        self.assertContains(response, "Duplicate")

    def test_analytics_exclude_cancelled_original_and_reversal_movement(self):
        movement = receive_stock(item=self.item, location=self.destination, qty=5)
        self.cancel(movement)

        summary = analytics_service.get_analytics_summary({})

        self.assertEqual(summary["operations_count"], 0)
        self.assertEqual(summary["receive_qty"], Decimal("0"))
