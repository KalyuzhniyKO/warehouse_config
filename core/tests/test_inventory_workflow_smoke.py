"""Business-readable smoke coverage for inventory reconciliation."""

from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from ..models import (
    InventoryCount,
    Item,
    Location,
    Recipient,
    StockBalance,
    StockMovement,
    Unit,
    Warehouse,
)
from ..services.inventory import (
    complete_inventory_count,
    create_inventory_count,
    get_inventory_line_expected_qty,
    get_inventory_line_movement_delta,
    reconcile_inventory_line,
    update_inventory_line_actual_qty,
)
from ..services.stock import (
    cancel_stock_movement,
    issue_stock,
    receive_stock,
    return_stock,
    transfer_stock,
    writeoff_stock,
)


class InventoryWorkflowSmokeTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="inventory-smoke-user",
            password="test-password",
        )
        self.unit = Unit.objects.create(name="Inventory smoke piece", symbol="isp")
        self.warehouse_a = Warehouse.objects.create(name="Inventory smoke warehouse A")
        self.warehouse_b = Warehouse.objects.create(name="Inventory smoke warehouse B")
        self.location_a = Location.objects.create(
            warehouse=self.warehouse_a,
            name="SMOKE-A",
        )
        self.location_b = Location.objects.create(
            warehouse=self.warehouse_b,
            name="SMOKE-B",
        )
        self.item = Item.objects.create(name="Inventory smoke item", unit=self.unit)
        self.recipient = Recipient.objects.create(name="Inventory smoke recipient")
        StockBalance.objects.create(
            item=self.item,
            warehouse=self.warehouse_a,
            location=self.location_a,
            qty=Decimal("100.000"),
        )
        StockBalance.objects.create(
            item=self.item,
            warehouse=self.warehouse_b,
            location=self.location_b,
            qty=Decimal("20.000"),
        )
        self.started_at = timezone.now() - timedelta(hours=2)
        self.counted_at = self.started_at + timedelta(hours=1)

    def start_inventory(self, warehouse=None):
        inventory = create_inventory_count(
            warehouse=warehouse or self.warehouse_a,
            user=self.user,
        )
        inventory.started_at = self.started_at
        inventory.save(update_fields=["started_at", "updated_at"])
        return inventory, inventory.lines.get()

    def count_line(self, line, actual_qty):
        with mock.patch("core.services.inventory.timezone.now", return_value=self.counted_at):
            return update_inventory_line_actual_qty(
                line=line,
                actual_qty=Decimal(actual_qty),
                user=self.user,
            )

    def test_start_inventory_stores_system_quantity_snapshot(self):
        inventory, line = self.start_inventory()

        self.assertEqual(inventory.status, InventoryCount.Status.IN_PROGRESS)
        self.assertEqual(line.expected_qty, Decimal("100.000"))
        self.assertIsNone(line.actual_qty)

    def test_issue_before_counted_at_gives_zero_variance_for_matching_fact(self):
        _, line = self.start_inventory()
        issue_stock(
            item=self.item,
            warehouse=self.warehouse_a,
            qty=Decimal("5.000"),
            recipient=self.recipient,
            occurred_at=self.started_at + timedelta(minutes=30),
        )

        self.count_line(line, "95.000")

        self.assertEqual(line.expected_qty_at_count_time, Decimal("95.000"))
        self.assertEqual(line.variance_qty, Decimal("0.000"))

    def test_receive_before_counted_at_gives_zero_variance_for_matching_fact(self):
        _, line = self.start_inventory()
        receive_stock(
            item=self.item,
            warehouse=self.warehouse_a,
            qty=Decimal("10.000"),
            occurred_at=self.started_at + timedelta(minutes=30),
        )

        self.count_line(line, "110.000")

        self.assertEqual(line.expected_qty_at_count_time, Decimal("110.000"))
        self.assertEqual(line.variance_qty, Decimal("0.000"))

    def test_movement_after_counted_at_does_not_change_frozen_variance(self):
        _, line = self.start_inventory()
        self.count_line(line, "100.000")

        issue_stock(
            item=self.item,
            warehouse=self.warehouse_a,
            qty=Decimal("5.000"),
            recipient=self.recipient,
            occurred_at=self.counted_at + timedelta(minutes=1),
        )
        reconcile_inventory_line(line)

        self.assertEqual(line.expected_qty_at_count_time, Decimal("100.000"))
        self.assertEqual(line.variance_qty, Decimal("0.000"))

    def test_real_shortage_posts_negative_adjustment_for_variance(self):
        inventory, line = self.start_inventory()
        self.count_line(line, "97.000")

        complete_inventory_count(inventory_count=inventory, user=self.user)

        adjustment = inventory.stock_movements.get()
        self.assertEqual(line.expected_qty_at_count_time, Decimal("100.000"))
        self.assertEqual(line.variance_qty, Decimal("-3.000"))
        self.assertEqual(adjustment.movement_type, StockMovement.MovementType.ADJUSTMENT)
        self.assertEqual(adjustment.qty, Decimal("3.000"))
        self.assertEqual(adjustment.source_warehouse, self.warehouse_a)
        self.assertIsNone(adjustment.destination_warehouse)

    def test_real_surplus_posts_positive_adjustment_for_variance(self):
        inventory, line = self.start_inventory()
        self.count_line(line, "104.000")

        complete_inventory_count(inventory_count=inventory, user=self.user)

        adjustment = inventory.stock_movements.get()
        self.assertEqual(line.expected_qty_at_count_time, Decimal("100.000"))
        self.assertEqual(line.variance_qty, Decimal("4.000"))
        self.assertEqual(adjustment.movement_type, StockMovement.MovementType.ADJUSTMENT)
        self.assertEqual(adjustment.qty, Decimal("4.000"))
        self.assertEqual(adjustment.destination_warehouse, self.warehouse_a)
        self.assertIsNone(adjustment.source_warehouse)

    def test_transfer_during_inventory_updates_both_warehouse_expectations(self):
        _, line_a = self.start_inventory(self.warehouse_a)
        _, line_b = self.start_inventory(self.warehouse_b)
        line_a.counted_at = self.counted_at
        line_b.counted_at = self.counted_at
        line_a.save(update_fields=["counted_at", "updated_at"])
        line_b.save(update_fields=["counted_at", "updated_at"])

        transfer_stock(
            item=self.item,
            source_warehouse=self.warehouse_a,
            destination_warehouse=self.warehouse_b,
            qty=Decimal("5.000"),
            occurred_at=self.started_at + timedelta(minutes=30),
        )

        self.assertEqual(get_inventory_line_expected_qty(line_a), Decimal("95.000"))
        self.assertEqual(get_inventory_line_expected_qty(line_b), Decimal("25.000"))

    def test_cancelled_movement_before_counted_at_is_excluded(self):
        _, line = self.start_inventory()
        movement = receive_stock(
            item=self.item,
            warehouse=self.warehouse_a,
            qty=Decimal("10.000"),
            occurred_at=self.started_at + timedelta(minutes=30),
        )
        cancel_stock_movement(
            movement=movement,
            cancelled_by=self.user,
            reason="Inventory smoke cancellation",
        )
        line.counted_at = timezone.now() + timedelta(minutes=1)
        line.save(update_fields=["counted_at", "updated_at"])

        self.assertEqual(get_inventory_line_movement_delta(line), Decimal("0.000"))
        self.assertEqual(get_inventory_line_expected_qty(line), Decimal("100.000"))


class ActiveInventoryDoesNotBlockStockOperationsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="inventory-no-block-user",
            password="test-password",
        )
        self.unit = Unit.objects.create(name="No-block piece", symbol="nbp")
        self.warehouse_a = Warehouse.objects.create(name="No-block warehouse A")
        self.warehouse_b = Warehouse.objects.create(name="No-block warehouse B")
        self.location_a = Location.objects.create(
            warehouse=self.warehouse_a,
            name="NO-BLOCK-A",
        )
        self.location_b = Location.objects.create(
            warehouse=self.warehouse_b,
            name="NO-BLOCK-B",
        )
        self.item = Item.objects.create(name="No-block item", unit=self.unit)
        self.recipient = Recipient.objects.create(name="No-block recipient")
        StockBalance.objects.create(
            item=self.item,
            warehouse=self.warehouse_a,
            location=self.location_a,
            qty=Decimal("100.000"),
        )
        StockBalance.objects.create(
            item=self.item,
            warehouse=self.warehouse_b,
            location=self.location_b,
            qty=Decimal("10.000"),
        )
        self.inventory = create_inventory_count(
            warehouse=self.warehouse_a,
            user=self.user,
        )

    def assert_active_inventory_and_movement(self, movement, movement_type):
        self.inventory.refresh_from_db()
        self.assertEqual(self.inventory.status, InventoryCount.Status.IN_PROGRESS)
        self.assertEqual(movement.movement_type, movement_type)
        self.assertIsNone(movement.inventory_count)

    def test_active_inventory_does_not_block_receive(self):
        movement = receive_stock(
            item=self.item,
            warehouse=self.warehouse_a,
            qty=Decimal("1.000"),
        )

        self.assert_active_inventory_and_movement(movement, StockMovement.MovementType.IN)

    def test_active_inventory_does_not_block_issue(self):
        movement = issue_stock(
            item=self.item,
            warehouse=self.warehouse_a,
            qty=Decimal("1.000"),
            recipient=self.recipient,
        )

        self.assert_active_inventory_and_movement(movement, StockMovement.MovementType.OUT)

    def test_active_inventory_does_not_block_return(self):
        issue_stock(
            item=self.item,
            warehouse=self.warehouse_a,
            qty=Decimal("2.000"),
            recipient=self.recipient,
        )

        movement = return_stock(
            item=self.item,
            warehouse=self.warehouse_a,
            qty=Decimal("1.000"),
            recipient=self.recipient,
        )

        self.assert_active_inventory_and_movement(
            movement,
            StockMovement.MovementType.RETURN,
        )

    def test_active_inventory_does_not_block_writeoff(self):
        movement = writeoff_stock(
            item=self.item,
            warehouse=self.warehouse_a,
            qty=Decimal("1.000"),
        )

        self.assert_active_inventory_and_movement(
            movement,
            StockMovement.MovementType.WRITEOFF,
        )

    def test_active_inventory_does_not_block_transfer(self):
        movement = transfer_stock(
            item=self.item,
            source_warehouse=self.warehouse_a,
            destination_warehouse=self.warehouse_b,
            qty=Decimal("1.000"),
        )

        self.assert_active_inventory_and_movement(
            movement,
            StockMovement.MovementType.TRANSFER,
        )
