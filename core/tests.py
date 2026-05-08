from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .models import (
    BarcodeRegistry,
    BarcodeSequence,
    Item,
    Location,
    Recipient,
    StockBalance,
    StockMovement,
    Unit,
    Warehouse,
)


class DashboardTests(SimpleTestCase):
    def test_dashboard_url_resolves(self):
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Warehouse dashboard")


class WarehouseModelTests(TestCase):
    def setUp(self):
        self.unit = Unit.objects.create(name="Piece", symbol="pcs")
        warehouse_barcode = BarcodeRegistry.objects.create(
            barcode="WH00000001", prefix=BarcodeRegistry.Prefix.WAREHOUSE
        )
        self.warehouse = Warehouse.objects.create(
            name="Main warehouse", barcode=warehouse_barcode
        )
        location_barcode = BarcodeRegistry.objects.create(
            barcode="LOC00000001", prefix=BarcodeRegistry.Prefix.LOCATION
        )
        self.location = Location.objects.create(
            warehouse=self.warehouse,
            name="A-01",
            barcode=location_barcode,
        )

    def test_barcode_registry_keeps_barcodes_globally_unique(self):
        BarcodeRegistry.objects.create(
            barcode="ITM00000001", prefix=BarcodeRegistry.Prefix.ITEM
        )

        with self.assertRaises(IntegrityError):
            BarcodeRegistry.objects.create(
                barcode="ITM00000001", prefix=BarcodeRegistry.Prefix.ITEM
            )

    def test_barcode_registry_validates_prefix(self):
        barcode = BarcodeRegistry(barcode="WH00000002", prefix=BarcodeRegistry.Prefix.ITEM)

        with self.assertRaises(ValidationError):
            barcode.full_clean()

    def test_barcode_sequence_supports_required_prefixes(self):
        prefixes = {choice.value for choice in BarcodeRegistry.Prefix}

        self.assertEqual(prefixes, {"ITM", "WH", "RCK", "LOC"})
        sequence = BarcodeSequence.objects.create(prefix=BarcodeRegistry.Prefix.RACK)
        self.assertEqual(sequence.next_number, 1)
        self.assertEqual(sequence.padding, 8)

    def test_item_internal_code_is_unique_when_filled(self):
        Item.objects.create(name="First item", internal_code="SKU-1", unit=self.unit)

        with self.assertRaises(IntegrityError):
            Item.objects.create(name="Second item", internal_code="SKU-1", unit=self.unit)

    def test_item_internal_code_can_be_blank_for_multiple_items(self):
        first = Item.objects.create(name="First item", internal_code="", unit=self.unit)
        second = Item.objects.create(name="Second item", internal_code="", unit=self.unit)

        self.assertIsNone(first.internal_code)
        self.assertIsNone(second.internal_code)
        self.assertEqual(Item.objects.filter(internal_code__isnull=True).count(), 2)

    def test_stock_balance_quantity_precision_and_unique_location_balance(self):
        item = Item.objects.create(name="Precise item", unit=self.unit)
        balance = StockBalance.objects.create(
            item=item,
            location=self.location,
            qty=Decimal("123456789012345.123"),
        )

        qty_field = StockBalance._meta.get_field("qty")
        self.assertEqual(qty_field.max_digits, 18)
        self.assertEqual(qty_field.decimal_places, 3)
        self.assertEqual(balance.qty, Decimal("123456789012345.123"))
        with self.assertRaises(IntegrityError):
            StockBalance.objects.create(item=item, location=self.location, qty=Decimal("1.000"))

    def test_stock_movement_has_required_types(self):
        expected_types = {
            "initial_balance",
            "in",
            "out",
            "return",
            "writeoff",
            "transfer",
            "adjustment",
        }
        actual_types = {choice.value for choice in StockMovement.MovementType}

        self.assertEqual(actual_types, expected_types)

    def test_stock_movement_can_store_transfer_between_locations(self):
        item = Item.objects.create(name="Transfer item", unit=self.unit)
        destination_barcode = BarcodeRegistry.objects.create(
            barcode="RCK00000001", prefix=BarcodeRegistry.Prefix.RACK
        )
        destination = Location.objects.create(
            warehouse=self.warehouse,
            name="Rack 1",
            location_type=Location.LocationType.RACK,
            barcode=destination_barcode,
        )
        movement = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.TRANSFER,
            item=item,
            qty=Decimal("5.500"),
            source_location=self.location,
            destination_location=destination,
        )

        self.assertEqual(movement.qty, Decimal("5.500"))
        self.assertEqual(movement.source_location, self.location)
        self.assertEqual(movement.destination_location, destination)

    def test_models_are_active_by_default_for_soft_delete_archiving(self):
        item = Item.objects.create(name="Active item", unit=self.unit)

        self.assertTrue(item.is_active)
        item.is_active = False
        item.save(update_fields=["is_active"])
        item.refresh_from_db()
        self.assertFalse(item.is_active)


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

    def test_receive_stock_increases_balance_and_creates_movement(self):
        from .services.stock import receive_stock

        movement = receive_stock(
            item=self.item,
            location=self.source_location,
            qty=Decimal("10.000"),
        )

        self.assertEqual(self.get_balance_qty(), Decimal("10.000"))
        self.assertEqual(movement.movement_type, StockMovement.MovementType.IN)
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_issue_stock_decreases_balance_and_creates_movement(self):
        from .services.stock import issue_stock, receive_stock

        receive_stock(
            item=self.item, location=self.source_location, qty=Decimal("10.000")
        )
        movement = issue_stock(
            item=self.item,
            location=self.source_location,
            qty=Decimal("3.250"),
            recipient=self.recipient,
        )

        self.assertEqual(self.get_balance_qty(), Decimal("6.750"))
        self.assertEqual(movement.movement_type, StockMovement.MovementType.OUT)
        self.assertEqual(movement.recipient, self.recipient)
        self.assertEqual(StockMovement.objects.count(), 2)

    def test_cannot_issue_more_than_available(self):
        from .services.stock import InsufficientStockError, issue_stock, receive_stock

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

    def test_writeoff_stock_decreases_balance_and_creates_movement(self):
        from .services.stock import receive_stock, writeoff_stock

        receive_stock(
            item=self.item, location=self.source_location, qty=Decimal("5.000")
        )
        movement = writeoff_stock(
            item=self.item,
            location=self.source_location,
            qty=Decimal("1.125"),
        )

        self.assertEqual(self.get_balance_qty(), Decimal("3.875"))
        self.assertEqual(movement.movement_type, StockMovement.MovementType.WRITEOFF)
        self.assertEqual(StockMovement.objects.count(), 2)

    def test_cannot_writeoff_more_than_available(self):
        from .services.stock import (
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
        from .services.stock import receive_stock, transfer_stock

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
        from .services.stock import (
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

    def test_adjust_stock_sets_target_quantity_and_creates_movement(self):
        from .services.stock import adjust_stock, receive_stock

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
        from .services.stock import create_initial_balance, return_stock

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
        from .services.stock import receive_stock

        movement = receive_stock(
            item=self.item,
            location=self.source_location,
            qty=Decimal("1.2345"),
        )

        self.assertEqual(self.get_balance_qty(), Decimal("1.235"))
        self.assertEqual(movement.qty, Decimal("1.235"))
