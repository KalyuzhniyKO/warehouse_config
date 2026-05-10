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

from .forms import CategoryForm, ItemForm, LocationForm, StockBalanceFilterForm, StockTransferForm
from .models import (
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


class ActiveChoiceFormTests(TestCase):
    def setUp(self):
        self.active_category = Category.objects.create(name="Активна категорія")
        self.archived_category = Category.objects.create(
            name="Архівна категорія", is_active=False
        )
        self.active_unit = Unit.objects.create(name="Штука", symbol="шт")
        self.archived_unit = Unit.objects.create(
            name="Архівна штука", symbol="арх", is_active=False
        )
        self.active_warehouse = Warehouse.objects.create(name="Активний склад")
        self.archived_warehouse = Warehouse.objects.create(
            name="Архівний склад", is_active=False
        )

    def test_archived_category_is_hidden_from_item_form_category_queryset(self):
        form = ItemForm()

        self.assertIn(self.active_category, form.fields["category"].queryset)
        self.assertNotIn(self.archived_category, form.fields["category"].queryset)

    def test_archived_unit_is_hidden_from_item_form_unit_queryset(self):
        form = ItemForm()

        self.assertIn(self.active_unit, form.fields["unit"].queryset)
        self.assertNotIn(self.archived_unit, form.fields["unit"].queryset)

    def test_archived_warehouse_is_hidden_from_location_form_warehouse_queryset(self):
        form = LocationForm()

        self.assertIn(self.active_warehouse, form.fields["warehouse"].queryset)
        self.assertNotIn(self.archived_warehouse, form.fields["warehouse"].queryset)

    def test_archived_category_is_hidden_from_category_form_parent_queryset(self):
        form = CategoryForm()

        self.assertIn(self.active_category, form.fields["parent"].queryset)
        self.assertNotIn(self.archived_category, form.fields["parent"].queryset)

    def test_category_form_excludes_itself_from_parent_queryset(self):
        form = CategoryForm(instance=self.active_category)

        self.assertNotIn(self.active_category, form.fields["parent"].queryset)

    def test_item_form_rejects_posted_archived_category(self):
        form = ItemForm(
            data={
                "name": "Болт",
                "internal_code": "BOLT-1",
                "category": self.archived_category.pk,
                "unit": self.active_unit.pk,
                "description": "",
                "is_active": "on",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("Не можна вибрати архівний запис.", form.errors["category"])

    def test_active_category_and_unit_are_available_for_item_form(self):
        form = ItemForm(
            data={
                "name": "Гайка",
                "internal_code": "NUT-1",
                "category": self.active_category.pk,
                "unit": self.active_unit.pk,
                "description": "",
                "is_active": "on",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_stock_balance_filter_uses_only_active_references(self):
        active_location = Location.objects.create(
            warehouse=self.active_warehouse, name="Активна локація"
        )
        archived_location = Location.objects.create(
            warehouse=self.active_warehouse, name="Архівна локація", is_active=False
        )
        location_in_archived_warehouse = Location.objects.create(
            warehouse=self.archived_warehouse, name="Локація архівного складу"
        )
        active_item = Item.objects.create(
            name="Активна номенклатура", unit=self.active_unit
        )
        archived_item = Item.objects.create(
            name="Архівна номенклатура", unit=self.active_unit, is_active=False
        )

        form = StockBalanceFilterForm()

        self.assertIn(self.active_warehouse, form.fields["warehouse"].queryset)
        self.assertNotIn(self.archived_warehouse, form.fields["warehouse"].queryset)
        self.assertIn(active_location, form.fields["location"].queryset)
        self.assertNotIn(archived_location, form.fields["location"].queryset)
        self.assertNotIn(
            location_in_archived_warehouse, form.fields["location"].queryset
        )
        self.assertIn(active_item, form.fields["item"].queryset)
        self.assertNotIn(archived_item, form.fields["item"].queryset)


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
        barcode = BarcodeRegistry(
            barcode="WH00000002", prefix=BarcodeRegistry.Prefix.ITEM
        )

        with self.assertRaises(ValidationError):
            barcode.full_clean()

    def test_barcode_sequence_supports_required_prefixes(self):
        prefixes = {choice.value for choice in BarcodeRegistry.Prefix}

        self.assertEqual(prefixes, {"ITM", "WH", "RCK", "LOC"})
        sequence = BarcodeSequence.objects.create(prefix=BarcodeRegistry.Prefix.RACK)
        self.assertEqual(sequence.next_number, 1)
        self.assertEqual(sequence.padding, 10)

    def test_item_internal_code_is_normalized_when_filled(self):
        item = Item.objects.create(
            name="First item", internal_code=" SKU-1 ", unit=self.unit
        )

        self.assertEqual(item.internal_code, "SKU-1")

    def test_item_internal_code_can_be_blank_for_multiple_items(self):
        first = Item.objects.create(name="First item", internal_code="", unit=self.unit)
        second = Item.objects.create(
            name="Second item", internal_code="", unit=self.unit
        )

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
            StockBalance.objects.create(
                item=item, location=self.location, qty=Decimal("1.000")
            )

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
            issue_reason=StockMovement.IssueReason.SALE,
        )

        self.assertEqual(self.get_balance_qty(), Decimal("6.750"))
        self.assertEqual(movement.movement_type, StockMovement.MovementType.OUT)
        self.assertEqual(movement.recipient, self.recipient)
        self.assertEqual(movement.issue_reason, StockMovement.IssueReason.SALE)
        self.assertEqual(StockMovement.objects.count(), 2)

    def test_issue_stock_stores_repair_reason_and_department(self):
        from .services.stock import issue_stock, receive_stock

        receive_stock(
            item=self.item, location=self.source_location, qty=Decimal("4.000")
        )
        movement = issue_stock(
            item=self.item,
            location=self.source_location,
            qty=Decimal("1.000"),
            issue_reason=StockMovement.IssueReason.REPAIR,
            department="  Repair shop  ",
            document_number="REQ-7",
        )

        self.assertEqual(movement.issue_reason, StockMovement.IssueReason.REPAIR)
        self.assertEqual(movement.department, "Repair shop")
        self.assertEqual(movement.document_number, "REQ-7")

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

    def test_cannot_transfer_more_than_available(self):
        from .services.stock import InsufficientStockError, receive_stock, transfer_stock

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
        from .services.stock import receive_stock, transfer_stock

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


class InventoryServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="inventory-user", password="test-password"
        )
        self.unit = Unit.objects.create(name="Piece", symbol="pcs")
        self.warehouse = Warehouse.objects.create(name="Inventory warehouse")
        self.other_warehouse = Warehouse.objects.create(name="Other warehouse")
        self.location = Location.objects.create(warehouse=self.warehouse, name="A-01")
        self.other_location = Location.objects.create(
            warehouse=self.warehouse, name="B-01"
        )
        self.foreign_location = Location.objects.create(
            warehouse=self.other_warehouse, name="C-01"
        )
        self.item = Item.objects.create(name="Counted item", unit=self.unit)
        self.second_item = Item.objects.create(name="Second counted item", unit=self.unit)
        self.foreign_item = Item.objects.create(name="Foreign item", unit=self.unit)
        self.balance = StockBalance.objects.create(
            item=self.item, location=self.location, qty=Decimal("7.500")
        )
        self.second_balance = StockBalance.objects.create(
            item=self.second_item, location=self.other_location, qty=Decimal("2.250")
        )
        StockBalance.objects.create(
            item=self.foreign_item,
            location=self.foreign_location,
            qty=Decimal("9.000"),
        )

    def test_inventory_count_can_be_created_with_sequential_number(self):
        from .services.inventory import create_inventory_count

        inventory_count = create_inventory_count(
            warehouse=self.warehouse, user=self.user, comment="Cycle count"
        )

        self.assertEqual(inventory_count.number, "INV-0000000001")
        self.assertEqual(inventory_count.status, InventoryCount.Status.IN_PROGRESS)
        self.assertEqual(inventory_count.warehouse, self.warehouse)
        self.assertEqual(inventory_count.created_by, self.user)
        self.assertEqual(inventory_count.comment, "Cycle count")

    def test_create_inventory_count_creates_lines_from_current_stock_balances(self):
        from .services.inventory import create_inventory_count

        inventory_count = create_inventory_count(warehouse=self.warehouse)

        lines = inventory_count.lines.order_by("item__name")
        self.assertEqual(lines.count(), 2)
        self.assertEqual(
            [line.expected_qty for line in lines],
            [Decimal("7.500"), Decimal("2.250")],
        )
        self.assertTrue(all(line.actual_qty is None for line in lines))
        self.assertEqual(
            set(lines.values_list("location", flat=True)),
            {self.location.pk, self.other_location.pk},
        )

    def test_create_inventory_count_for_location_uses_only_that_location(self):
        from .services.inventory import create_inventory_count

        inventory_count = create_inventory_count(
            warehouse=self.warehouse, location=self.location
        )

        line = inventory_count.lines.get()
        self.assertEqual(line.location, self.location)
        self.assertEqual(line.item, self.item)
        self.assertEqual(line.expected_qty, self.balance.qty)
        self.assertIsNone(line.actual_qty)

    def test_update_inventory_line_actual_qty_calculates_difference(self):
        from .services.inventory import (
            create_inventory_count,
            update_inventory_line_actual_qty,
        )

        inventory_count = create_inventory_count(
            warehouse=self.warehouse, location=self.location
        )
        line = inventory_count.lines.get()

        update_inventory_line_actual_qty(
            line=line,
            actual_qty=Decimal("6.000"),
            user=self.user,
            comment="Found shortage",
        )

        line.refresh_from_db()
        self.assertEqual(line.actual_qty, Decimal("6.000"))
        self.assertEqual(line.difference_qty, Decimal("-1.500"))
        self.assertEqual(line.counted_by, self.user)
        self.assertIsNotNone(line.counted_at)
        self.assertEqual(line.comment, "Found shortage")

    def test_update_inventory_line_actual_qty_does_not_change_stock_balance(self):
        from .services.inventory import (
            create_inventory_count,
            update_inventory_line_actual_qty,
        )

        inventory_count = create_inventory_count(
            warehouse=self.warehouse, location=self.location
        )
        line = inventory_count.lines.get()

        update_inventory_line_actual_qty(line=line, actual_qty=Decimal("1.000"))

        self.balance.refresh_from_db()
        self.assertEqual(self.balance.qty, Decimal("7.500"))

    def test_create_inventory_count_does_not_create_stock_movements(self):
        from .services.inventory import create_inventory_count

        create_inventory_count(warehouse=self.warehouse)

        self.assertEqual(StockMovement.objects.count(), 0)

    def test_complete_inventory_count_creates_adjustment_for_surplus(self):
        from .services.inventory import complete_inventory_count, create_inventory_count

        inventory_count = create_inventory_count(
            warehouse=self.warehouse, location=self.location
        )
        line = inventory_count.lines.get()
        line.actual_qty = Decimal("8.250")
        line.save(update_fields=["actual_qty", "updated_at"])

        complete_inventory_count(inventory_count=inventory_count, user=self.user)

        movement = StockMovement.objects.get()
        self.assertEqual(movement.movement_type, StockMovement.MovementType.ADJUSTMENT)
        self.assertEqual(movement.qty, Decimal("0.750"))
        self.assertEqual(movement.destination_location, self.location)
        self.assertEqual(movement.inventory_count, inventory_count)

    def test_complete_inventory_count_creates_adjustment_for_shortage(self):
        from .services.inventory import complete_inventory_count, create_inventory_count

        inventory_count = create_inventory_count(
            warehouse=self.warehouse, location=self.location
        )
        line = inventory_count.lines.get()
        line.actual_qty = Decimal("5.000")
        line.save(update_fields=["actual_qty", "updated_at"])

        complete_inventory_count(inventory_count=inventory_count, user=self.user)

        movement = StockMovement.objects.get()
        self.assertEqual(movement.movement_type, StockMovement.MovementType.ADJUSTMENT)
        self.assertEqual(movement.qty, Decimal("2.500"))
        self.assertEqual(movement.source_location, self.location)
        self.assertEqual(movement.inventory_count, inventory_count)

    def test_complete_inventory_count_updates_stock_balance(self):
        from .services.inventory import complete_inventory_count, create_inventory_count

        inventory_count = create_inventory_count(
            warehouse=self.warehouse, location=self.location
        )
        line = inventory_count.lines.get()
        line.actual_qty = Decimal("9.000")
        line.save(update_fields=["actual_qty", "updated_at"])

        complete_inventory_count(inventory_count=inventory_count, user=self.user)

        self.balance.refresh_from_db()
        self.assertEqual(self.balance.qty, Decimal("9.000"))

    def test_complete_inventory_count_ignores_empty_actual_qty(self):
        from .services.inventory import complete_inventory_count, create_inventory_count

        inventory_count = create_inventory_count(
            warehouse=self.warehouse, location=self.location
        )

        complete_inventory_count(inventory_count=inventory_count, user=self.user)

        self.balance.refresh_from_db()
        self.assertEqual(self.balance.qty, Decimal("7.500"))
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_complete_inventory_count_ignores_zero_difference(self):
        from .services.inventory import complete_inventory_count, create_inventory_count

        inventory_count = create_inventory_count(
            warehouse=self.warehouse, location=self.location
        )
        line = inventory_count.lines.get()
        line.actual_qty = line.expected_qty
        line.save(update_fields=["actual_qty", "updated_at"])

        complete_inventory_count(inventory_count=inventory_count, user=self.user)

        self.assertEqual(StockMovement.objects.count(), 0)

    def test_complete_inventory_count_marks_completed(self):
        from .services.inventory import complete_inventory_count, create_inventory_count

        inventory_count = create_inventory_count(
            warehouse=self.warehouse, location=self.location
        )

        completed = complete_inventory_count(inventory_count=inventory_count, user=self.user)

        self.assertEqual(completed.status, InventoryCount.Status.COMPLETED)
        self.assertIsNotNone(completed.completed_at)
        self.assertEqual(completed.approved_by, self.user)

    def test_complete_inventory_count_rejects_repeated_completion(self):
        from .services.inventory import (
            InventoryAlreadyCompletedError,
            complete_inventory_count,
            create_inventory_count,
        )

        inventory_count = create_inventory_count(
            warehouse=self.warehouse, location=self.location
        )
        line = inventory_count.lines.get()
        line.actual_qty = Decimal("8.000")
        line.save(update_fields=["actual_qty", "updated_at"])
        complete_inventory_count(inventory_count=inventory_count, user=self.user)

        with self.assertRaises(InventoryAlreadyCompletedError):
            complete_inventory_count(inventory_count=inventory_count, user=self.user)

        self.assertEqual(StockMovement.objects.count(), 1)

    def test_complete_inventory_count_rejects_cancelled_count(self):
        from .services.inventory import (
            InventoryCancelledError,
            complete_inventory_count,
            create_inventory_count,
        )

        inventory_count = create_inventory_count(
            warehouse=self.warehouse, location=self.location
        )
        inventory_count.status = InventoryCount.Status.CANCELLED
        inventory_count.save(update_fields=["status", "updated_at"])

        with self.assertRaises(InventoryCancelledError):
            complete_inventory_count(inventory_count=inventory_count, user=self.user)

        self.assertEqual(StockMovement.objects.count(), 0)

    def test_line_save_sets_zero_difference_when_actual_qty_is_empty(self):
        inventory_count = InventoryCount.objects.create(
            number="INV-0000000001",
            warehouse=self.warehouse,
            status=InventoryCount.Status.IN_PROGRESS,
        )
        line = InventoryCountLine.objects.create(
            inventory_count=inventory_count,
            item=self.item,
            location=self.location,
            expected_qty=Decimal("7.500"),
            actual_qty=None,
        )

        self.assertEqual(line.difference_qty, Decimal("0"))


class WebInterfaceTests(TestCase):
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

    def test_pages_redirect_anonymous_user_to_login(self):
        self.client.logout()

        response = self.client.get(reverse("item_list"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_localized_home_pages_show_yantos_brand(self):
        for path in ["/uk/", "/en/"]:
            with self.subTest(path=path):
                response = self.client.get(path)

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "YANTOS")

    def test_base_navbar_uses_yantos_theme_instead_of_bootstrap_primary(self):
        template = Path("templates/base.html").read_text()

        self.assertNotIn("navbar-dark bg-primary", template)
        self.assertNotIn("bg-primary", template)
        self.assertIn("yantos-navbar", template)
        self.assertIn('brand-name">YANTOS</span>', template)
        self.assertNotIn('brand-name">Yantos</span>', template)

    def test_directory_list_pages_are_available_for_logged_in_user(self):
        url_names = [
            "unit_list",
            "category_list",
            "recipient_list",
            "item_list",
            "warehouse_list",
            "location_list",
        ]

        for url_name in url_names:
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name))
                self.assertEqual(response.status_code, 200)

    def test_unit_create_update_and_archive(self):
        create_response = self.client.post(
            reverse("unit_create"),
            {"name": "Кілограм", "symbol": "кг", "is_active": "on"},
        )
        self.assertEqual(create_response.status_code, 302)
        unit = Unit.objects.get(symbol="кг")

        update_response = self.client.post(
            reverse("unit_update", args=[unit.pk]),
            {"name": "Кілограм", "symbol": "kg", "is_active": "on"},
        )
        self.assertEqual(update_response.status_code, 302)
        unit.refresh_from_db()
        self.assertEqual(unit.symbol, "kg")

        archive_response = self.client.post(reverse("unit_archive", args=[unit.pk]))
        self.assertEqual(archive_response.status_code, 302)
        unit.refresh_from_db()
        self.assertFalse(unit.is_active)

    def test_item_can_be_created_through_web(self):
        response = self.client.post(
            reverse("item_create"),
            {
                "name": "Гайка М8",
                "internal_code": "NUT-M8",
                "category": self.category.pk,
                "unit": self.unit.pk,
                "description": "",
                "is_active": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Item.objects.filter(internal_code="NUT-M8").exists())

    def test_item_create_page_hides_archived_categories(self):
        archived_category = Category.objects.create(
            name="Архівна категорія UI", is_active=False
        )

        response = self.client.get(reverse("item_create"), HTTP_ACCEPT_LANGUAGE="uk")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.category.name)
        self.assertNotContains(response, archived_category.name)

    def test_item_create_page_rejects_archived_category_post(self):
        archived_category = Category.objects.create(
            name="Архівна категорія POST", is_active=False
        )

        response = self.client.post(
            reverse("item_create"),
            {
                "name": "Шайба М8",
                "internal_code": "WASHER-M8",
                "category": archived_category.pk,
                "unit": self.unit.pk,
                "description": "",
                "is_active": "on",
            },
            HTTP_ACCEPT_LANGUAGE="uk",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Не можна вибрати архівний запис.")
        self.assertFalse(Item.objects.filter(internal_code="WASHER-M8").exists())

    def test_warehouse_and_location_can_be_created_through_web(self):
        warehouse_response = self.client.post(
            reverse("warehouse_create"),
            {"name": "Резервний склад", "address": "", "is_active": "on"},
        )
        self.assertEqual(warehouse_response.status_code, 302)
        warehouse = Warehouse.objects.get(name="Резервний склад")

        location_response = self.client.post(
            reverse("location_create"),
            {
                "warehouse": warehouse.pk,
                "name": "B-02",
                "location_type": Location.LocationType.LOCATION,
                "is_active": "on",
            },
        )
        self.assertEqual(location_response.status_code, 302)
        self.assertTrue(
            Location.objects.filter(warehouse=warehouse, name="B-02").exists()
        )

    def test_cannot_create_duplicate_root_category_with_trimmed_name(self):
        response = self.client.post(
            reverse("category_create"),
            {"name": " Матеріали ", "parent": "", "is_active": "on"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Категорія з такою назвою вже існує.")
        self.assertEqual(
            Category.objects.filter(
                name__iexact="Матеріали", parent__isnull=True
            ).count(),
            1,
        )

    def test_cannot_create_duplicate_category_with_same_parent(self):
        parent = Category.objects.create(name="Запчастини")
        Category.objects.create(name="Електрика", parent=parent)

        response = self.client.post(
            reverse("category_create"),
            {"name": " електрика ", "parent": parent.pk, "is_active": "on"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Категорія з такою назвою вже існує.")
        self.assertEqual(Category.objects.filter(parent=parent).count(), 1)

    def test_can_create_same_category_name_in_different_parents(self):
        first_parent = Category.objects.create(name="Склад 1")
        second_parent = Category.objects.create(name="Склад 2")
        Category.objects.create(name="Кабелі", parent=first_parent)

        response = self.client.post(
            reverse("category_create"),
            {"name": "Кабелі", "parent": second_parent.pk, "is_active": "on"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Category.objects.filter(name="Кабелі").count(), 2)

    def test_archive_and_restore_actions_toggle_active_status(self):
        unit = Unit.objects.create(name="Метр", symbol="м")

        archive_response = self.client.post(reverse("unit_archive", args=[unit.pk]))
        self.assertEqual(archive_response.status_code, 302)
        unit.refresh_from_db()
        self.assertFalse(unit.is_active)

        restore_response = self.client.post(reverse("unit_restore", args=[unit.pk]))
        self.assertEqual(restore_response.status_code, 302)
        unit.refresh_from_db()
        self.assertTrue(unit.is_active)

    def test_directory_list_shows_active_by_default_and_archived_by_filter(self):
        archived = Unit.objects.create(name="Літр", symbol="л", is_active=False)

        active_response = self.client.get(reverse("unit_list"))
        self.assertContains(active_response, self.unit.name)
        self.assertNotContains(active_response, archived.name)

        archived_response = self.client.get(
            reverse("unit_list"), {"status": "archived"}
        )
        self.assertNotContains(archived_response, self.unit.name)
        self.assertContains(archived_response, archived.name)

    def test_item_form_labels_are_ukrainian(self):
        response = self.client.get(reverse("item_create"))

        for label in ["Назва", "Внутрішній код", "Категорія", "Одиниця виміру", "Опис"]:
            self.assertContains(response, label)
        self.assertNotContains(response, ">Name<")
        self.assertNotContains(response, ">Internal code<")

    def test_archive_category_blocked_when_active_items_exist(self):
        response = self.client.post(
            reverse("category_archive", args=[self.category.pk])
        )

        self.category.refresh_from_db()
        self.assertTrue(self.category.is_active)
        self.assertEqual(response.status_code, 302)

    def test_find_duplicates_command_reports_duplicates_without_changes(self):
        first = Category.objects.create(name="Електрозапчастини")
        second = Category.objects.create(name=" електрозапчастини ")
        before_count = Category.objects.count()
        out = StringIO()

        call_command("find_duplicates", stdout=out)

        self.assertIn("Category", out.getvalue())
        self.assertEqual(Category.objects.count(), before_count)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertTrue(first.is_active)
        self.assertTrue(second.is_active)

    def test_stock_balance_list_opens_and_filters_by_search(self):
        response = self.client.get(reverse("stockbalance_list"), {"q": "BOLT"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Болт М8")


class InventoryInterfaceTests(TestCase):
    def setUp(self):
        call_command("init_roles", stdout=StringIO())
        User = get_user_model()
        self.admin = User.objects.create_user(username="inventory-admin", password="pw")
        self.admin.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.storekeeper = User.objects.create_user(username="inventory-storekeeper", password="pw")
        self.storekeeper.groups.add(Group.objects.get(name="Комірник"))
        self.auditor = User.objects.create_user(username="inventory-auditor", password="pw")
        self.auditor.groups.add(Group.objects.get(name="Перегляд / аудитор"))
        self.no_access = User.objects.create_user(username="inventory-no-access", password="pw")
        self.unit = Unit.objects.create(name="Piece", symbol="pcs")
        self.warehouse = Warehouse.objects.create(name="Inventory UI warehouse")
        self.location = Location.objects.create(warehouse=self.warehouse, name="INV-A-01")
        self.item_barcode = BarcodeRegistry.objects.create(
            barcode="ITM9990000001", prefix=BarcodeRegistry.Prefix.ITEM
        )
        self.item = Item.objects.create(
            name="Inventory UI item",
            internal_code="INV-ITEM-1",
            unit=self.unit,
            barcode=self.item_barcode,
        )
        self.balance = StockBalance.objects.create(
            item=self.item, location=self.location, qty=Decimal("5.000")
        )

    def login(self, user):
        self.client.force_login(user)

    def create_inventory(self):
        from .services.inventory import create_inventory_count

        return create_inventory_count(warehouse=self.warehouse, user=self.admin)

    def test_admin_sees_inventory_menu_item(self):
        self.login(self.admin)

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "Інвентаризація")

    def test_storekeeper_sees_inventory_menu_item(self):
        self.login(self.storekeeper)

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "Інвентаризація")

    def test_auditor_does_not_see_new_inventory_button(self):
        self.login(self.auditor)

        response = self.client.get(reverse("inventory_list"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Нова інвентаризація")

    def test_inventory_list_opens_for_authorized_stock_user(self):
        self.login(self.admin)

        response = self.client.get(reverse("inventory_list"))

        self.assertEqual(response.status_code, 200)

    def test_create_inventory_form_creates_count_lines_and_redirects_to_count(self):
        self.login(self.admin)

        response = self.client.post(
            reverse("inventory_create"),
            {"warehouse": self.warehouse.pk, "location": "", "comment": "UI count"},
        )

        inventory_count = InventoryCount.objects.get()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("inventory_count", args=[inventory_count.pk]))
        self.assertEqual(inventory_count.comment, "UI count")
        self.assertEqual(inventory_count.lines.count(), 1)

    def test_count_page_saves_actual_qty_and_difference(self):
        self.login(self.admin)
        inventory_count = self.create_inventory()
        line = inventory_count.lines.get()

        response = self.client.post(
            reverse("inventory_count", args=[inventory_count.pk]),
            {f"line-{line.pk}-actual_qty": "7.000", f"line-{line.pk}-comment": "Found surplus"},
        )

        self.assertEqual(response.status_code, 302)
        line.refresh_from_db()
        self.assertEqual(line.actual_qty, Decimal("7.000"))
        self.assertEqual(line.difference_qty, Decimal("2.000"))
        self.assertEqual(line.comment, "Found surplus")

    def test_search_by_barcode_filters_count_lines(self):
        self.login(self.admin)
        inventory_count = self.create_inventory()
        other_item = Item.objects.create(name="Other inventory item", unit=self.unit)
        InventoryCountLine.objects.create(
            inventory_count=inventory_count,
            item=other_item,
            location=self.location,
            barcode="ITM-NOT-MATCHED",
            expected_qty=Decimal("1.000"),
        )

        response = self.client.get(
            reverse("inventory_count", args=[inventory_count.pk]), {"q": "ITM9990000001"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Inventory UI item")
        self.assertNotContains(response, "Other inventory item")

    def test_count_page_does_not_change_stock_balance_or_create_movement(self):
        self.login(self.admin)
        inventory_count = self.create_inventory()
        line = inventory_count.lines.get()
        before_balance = self.balance.qty
        before_movements = StockMovement.objects.count()

        self.client.post(
            reverse("inventory_count", args=[inventory_count.pk]),
            {f"line-{line.pk}-actual_qty": "2.000", f"line-{line.pk}-comment": "Short"},
        )

        self.balance.refresh_from_db()
        self.assertEqual(self.balance.qty, before_balance)
        self.assertEqual(StockMovement.objects.count(), before_movements)

    def test_completed_count_page_does_not_allow_editing(self):
        from .services.inventory import complete_inventory_count

        self.login(self.admin)
        inventory_count = self.create_inventory()
        complete_inventory_count(inventory_count=inventory_count, user=self.admin)

        response = self.client.get(reverse("inventory_count", args=[inventory_count.pk]))

        self.assertEqual(response.status_code, 404)

    def test_admin_and_storekeeper_see_complete_button(self):
        inventory_count = self.create_inventory()

        self.login(self.admin)
        admin_response = self.client.get(reverse("inventory_detail", args=[inventory_count.pk]))
        self.assertContains(admin_response, "Завершити інвентаризацію")

        self.login(self.storekeeper)
        storekeeper_response = self.client.get(reverse("inventory_detail", args=[inventory_count.pk]))
        self.assertContains(storekeeper_response, "Завершити інвентаризацію")

    def test_auditor_cannot_complete_inventory(self):
        self.login(self.auditor)
        inventory_count = self.create_inventory()

        detail_response = self.client.get(reverse("inventory_detail", args=[inventory_count.pk]))
        self.assertNotContains(detail_response, "Завершити інвентаризацію")
        complete_response = self.client.post(
            reverse("inventory_complete", args=[inventory_count.pk])
        )

        inventory_count.refresh_from_db()
        self.assertEqual(complete_response.status_code, 403)
        self.assertEqual(inventory_count.status, InventoryCount.Status.IN_PROGRESS)


    def test_csv_export_is_available_for_admin_and_contains_inventory_data_and_bom(self):
        self.login(self.admin)
        inventory_count = self.create_inventory()
        line = inventory_count.lines.get()
        line.actual_qty = Decimal("7.000")
        line.comment = "Found surplus"
        line.save(update_fields=["actual_qty", "comment", "updated_at"])

        response = self.client.get(reverse("inventory_export_csv", args=[inventory_count.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content[:3], b"\xef\xbb\xbf")
        content = response.content.decode("utf-8-sig")
        self.assertIn(inventory_count.number, content)
        self.assertIn("Inventory UI item", content)
        self.assertIn("Found surplus", content)
        self.assertIn('filename="inventory_%s.csv"' % inventory_count.number, response["Content-Disposition"])

    def test_xlsx_export_returns_file_when_openpyxl_is_available(self):
        from openpyxl import load_workbook

        self.login(self.admin)
        inventory_count = self.create_inventory()

        response = self.client.get(reverse("inventory_export_xlsx", args=[inventory_count.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertIn('filename="inventory_%s.xlsx"' % inventory_count.number, response["Content-Disposition"])
        workbook = load_workbook(BytesIO(response.content), data_only=True)
        sheet = workbook.active
        self.assertIn(sheet.title, {"Inventory", "Інвентаризація"})
        self.assertEqual(sheet["A2"].value, inventory_count.number)
        self.assertEqual(sheet["E2"].value, "Inventory UI item")
        self.assertIsInstance(sheet["I2"].value, (int, float))

    def test_xlsx_export_returns_service_unavailable_when_openpyxl_is_missing(self):
        self.login(self.admin)
        inventory_count = self.create_inventory()
        original_import = __import__

        def import_without_openpyxl(name, *args, **kwargs):
            if name.startswith("openpyxl"):
                raise ImportError("openpyxl unavailable")
            return original_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=import_without_openpyxl):
            response = self.client.get(reverse("inventory_export_xlsx", args=[inventory_count.pk]))

        self.assertEqual(response.status_code, 503)
        self.assertContains(response, "openpyxl", status_code=503)

    def test_auditor_can_export_inventory_but_cannot_create_or_edit_it(self):
        inventory_count = self.create_inventory()
        self.login(self.auditor)

        csv_response = self.client.get(reverse("inventory_export_csv", args=[inventory_count.pk]))
        create_response = self.client.post(
            reverse("inventory_create"),
            {"warehouse": self.warehouse.pk, "location": "", "comment": "Forbidden"},
        )
        count_response = self.client.get(reverse("inventory_count", args=[inventory_count.pk]))
        complete_response = self.client.post(reverse("inventory_complete", args=[inventory_count.pk]))

        inventory_count.refresh_from_db()
        self.assertEqual(csv_response.status_code, 200)
        self.assertEqual(create_response.status_code, 403)
        self.assertEqual(count_response.status_code, 403)
        self.assertEqual(complete_response.status_code, 403)
        self.assertEqual(inventory_count.status, InventoryCount.Status.IN_PROGRESS)

    def test_detail_page_shows_inventory_summary(self):
        self.login(self.admin)
        inventory_count = self.create_inventory()
        line = inventory_count.lines.get()
        line.actual_qty = Decimal("7.000")
        line.save(update_fields=["actual_qty", "updated_at"])
        other_item = Item.objects.create(name="Shortage item", unit=self.unit)
        InventoryCountLine.objects.create(
            inventory_count=inventory_count,
            item=other_item,
            location=self.location,
            expected_qty=Decimal("4.000"),
            actual_qty=Decimal("1.000"),
        )

        response = self.client.get(reverse("inventory_detail", args=[inventory_count.pk]))

        self.assertContains(response, "Всього рядків")
        self.assertContains(response, "Кількість розбіжностей")
        self.assertContains(response, "Сума надлишків")
        self.assertContains(response, "Сума нестач")
        self.assertEqual(response.context["inventory_summary"]["total_lines"], 2)
        self.assertEqual(response.context["inventory_summary"]["difference_lines"], 2)
        self.assertEqual(response.context["inventory_summary"]["total_surplus"], Decimal("2.000"))
        self.assertEqual(response.context["inventory_summary"]["total_shortage"], Decimal("3.000"))

    def test_inventory_list_shows_status_badges(self):
        self.login(self.admin)
        self.create_inventory()

        response = self.client.get(reverse("inventory_list"))

        self.assertContains(response, "badge text-bg-primary")
        self.assertContains(response, InventoryCount.Status.IN_PROGRESS.label)

    def test_complete_inventory_post_adjusts_stock_and_redirects(self):
        self.login(self.storekeeper)
        inventory_count = self.create_inventory()
        line = inventory_count.lines.get()
        line.actual_qty = Decimal("6.500")
        line.save(update_fields=["actual_qty", "updated_at"])

        response = self.client.post(reverse("inventory_complete", args=[inventory_count.pk]))

        inventory_count.refresh_from_db()
        self.balance.refresh_from_db()
        movement = StockMovement.objects.get()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("inventory_detail", args=[inventory_count.pk]))
        self.assertEqual(inventory_count.status, InventoryCount.Status.COMPLETED)
        self.assertIsNotNone(inventory_count.completed_at)
        self.assertEqual(inventory_count.approved_by, self.storekeeper)
        self.assertEqual(self.balance.qty, Decimal("6.500"))
        self.assertEqual(movement.inventory_count, inventory_count)

    def test_movements_list_shows_inventory_number_for_adjustment(self):
        self.login(self.admin)
        inventory_count = self.create_inventory()
        line = inventory_count.lines.get()
        line.actual_qty = Decimal("6.000")
        line.save(update_fields=["actual_qty", "updated_at"])
        self.client.post(reverse("inventory_complete", args=[inventory_count.pk]))

        response = self.client.get(reverse("movement_list"))

        self.assertContains(response, inventory_count.number)

    def test_user_without_rights_cannot_create_inventory(self):
        self.login(self.no_access)

        response = self.client.post(
            reverse("inventory_create"),
            {"warehouse": self.warehouse.pk, "location": "", "comment": "Forbidden"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(InventoryCount.objects.count(), 0)


class SwitchLanguageUrlTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def assert_switch_url(self, source_url, language_code, expected_url):
        from .templatetags.i18n_extras import switch_language_url

        request = self.factory.get(source_url)
        self.assertEqual(switch_language_url(request, language_code), expected_url)

    def test_replaces_existing_language_prefix(self):
        self.assert_switch_url("/uk/", "en", "/en/")
        self.assert_switch_url("/en/items/", "uk", "/uk/items/")

    def test_preserves_query_string(self):
        self.assert_switch_url("/uk/items/?q=test", "en", "/en/items/?q=test")

    def test_adds_language_prefix_when_missing(self):
        self.assert_switch_url("/admin/", "en", "/en/admin/")
        self.assert_switch_url("/", "uk", "/uk/")


class ManagementAnalyticsTests(TestCase):
    def setUp(self):
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
        self.location = Location.objects.create(warehouse=self.warehouse, name="A1")
        self.other_location = Location.objects.create(
            warehouse=self.other_warehouse, name="B1"
        )
        self.recipient = Recipient.objects.create(name="Цех 1")
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

    def test_management_requires_login(self):
        response = self.client.get(reverse("management_dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_management_analytics_requires_role(self):
        self.client.force_login(self.storekeeper)
        response = self.client.get(reverse("management_analytics"))
        self.assertEqual(response.status_code, 403)
        self.client.force_login(self.auditor)
        response = self.client.get(reverse("management_analytics"))
        self.assertEqual(response.status_code, 403)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("management_analytics"))
        self.assertEqual(response.status_code, 200)

    def test_storekeeper_menu_hides_management_analytics_and_admin(self):
        self.client.force_login(self.storekeeper)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Керування")
        self.assertNotContains(response, "Аналітика")
        self.assertNotContains(response, "Адмін-панель")

    def test_warehouse_admin_menu_shows_management(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Керування")
        self.assertNotContains(response, "Адмін-панель")

    def test_warehouse_admin_opens_management_pages(self):
        self.client.force_login(self.admin)
        for url_name in ["management_dashboard", "management_help", "management_analytics"]:
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 200, url_name)

    def test_superuser_sees_technical_django_admin_card(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("management_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Технічна Django Admin")
        self.assertContains(response, "Тільки для технічного обслуговування")

    def test_storekeeper_cannot_open_analytics_urls(self):
        self.client.force_login(self.storekeeper)
        response = self.client.get(reverse("management_analytics"))
        self.assertEqual(response.status_code, 403)
        response = self.client.get(reverse("analytics"))
        self.assertEqual(response.status_code, 403)

    def test_analytics_redirects_warehouse_admin_to_management_analytics(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("analytics"))
        self.assertRedirects(response, reverse("management_analytics"))

    def test_storekeeper_cannot_manage_users(self):
        self.client.force_login(self.storekeeper)
        response = self.client.get(reverse("management_users"))
        self.assertEqual(response.status_code, 403)

    def test_auditor_cannot_edit_directories(self):
        self.client.force_login(self.auditor)
        response = self.client.post(
            reverse("unit_create"), {"name": "Кг", "symbol": "кг", "is_active": "on"}
        )
        self.assertEqual(response.status_code, 403)

    def test_init_roles_creates_expected_groups(self):
        for name in ["Адміністратор складу", "Комірник", "Перегляд / аудитор"]:
            self.assertTrue(Group.objects.filter(name=name).exists())

    def test_analytics_counts_in_and_out(self):
        from .services.analytics import get_movement_summary

        summary = get_movement_summary({"warehouse": self.warehouse})
        self.assertEqual(summary["total_in"], Decimal("10.000"))
        self.assertEqual(summary["total_out"], Decimal("3.000"))

    def test_analytics_filters_by_date(self):
        from .services.analytics import get_movement_summary

        summary = get_movement_summary(
            {"date_from": timezone.datetime(2026, 1, 11).date()}
        )
        self.assertEqual(summary["total_in"], Decimal("5.000"))
        self.assertEqual(summary["total_out"], Decimal("3.000"))

    def test_analytics_filters_by_warehouse(self):
        from .services.analytics import get_movement_summary

        summary = get_movement_summary({"warehouse": self.other_warehouse})
        self.assertEqual(summary["total_in"], Decimal("5.000"))
        self.assertEqual(summary["total_out"], Decimal("0.000"))

    def test_export_csv_works(self):
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("management_analytics_export_csv"), {"warehouse": self.warehouse.pk}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertContains(response, "Кабель ВВГ")

    def test_documentation_files_exist(self):
        from pathlib import Path

        docs = Path(__file__).resolve().parent.parent / "docs"
        for filename in [
            "USER_GUIDE.md",
            "ADMIN_GUIDE.md",
            "START_WAREHOUSE_FROM_ZERO.md",
        ]:
            self.assertTrue((docs / filename).exists())

    def test_management_help_page_shows_instruction_sections(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("management_help"))
        self.assertEqual(response.status_code, 200)
        for text in [
            "Як почати склад з нуля",
            "Інструкція користувача",
            "Інструкція адміністратора",
            "Типові помилки",
            "Backup і відновлення",
            "Принтери і друк етикеток",
            "Штрихкоди",
            "Прихід товару",
            "Початковий залишок",
            "Рухи товарів",
        ]:
            self.assertContains(response, text)

    def test_user_help_page_shows_only_user_instruction(self):
        self.client.force_login(self.storekeeper)
        response = self.client.get(reverse("help"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Інструкція користувача")
        self.assertNotContains(response, "Інструкція адміністратора")
        self.assertNotContains(response, "Backup і відновлення")

    @override_settings(AUTH_PASSWORD_VALIDATORS=[])
    def test_simple_passwords_are_not_blocked_when_validators_disabled(self):
        validate_password("1", user=self.storekeeper)

    def test_pr17_stock_pages_available_to_storekeeper(self):
        self.client.force_login(self.storekeeper)
        for url_name in ["stock_receive", "stock_issue", "stock_initial", "movement_list", "stockbalance_list", "item_list", "help"]:
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 200, url_name)


    def test_storekeeper_sees_stock_issue_but_not_recipients_in_main_menu(self):
        self.client.force_login(self.storekeeper)
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Видача товару")
        self.assertNotContains(response, "Отримувачі")

    def test_stock_issue_page_available_to_storekeeper(self):
        self.client.force_login(self.storekeeper)
        response = self.client.get(reverse("stock_issue"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Видача товару")

    def test_stock_issue_post_decreases_balance_and_creates_out_movement(self):
        self.client.force_login(self.storekeeper)
        response = self.client.post(
            reverse("stock_issue"),
            {
                "item": self.item.pk,
                "warehouse": self.warehouse.pk,
                "location": self.location.pk,
                "qty": "2.000",
                "issue_reason": StockMovement.IssueReason.SALE,
                "department": "Sales",
                "recipient": self.recipient.pk,
                "document_number": "SO-1",
                "comment": "",
                "occurred_at": "2026-01-15T10:00",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.balance.refresh_from_db()
        movement = StockMovement.objects.latest("id")
        self.assertEqual(self.balance.qty, Decimal("5.000"))
        self.assertEqual(movement.movement_type, StockMovement.MovementType.OUT)
        self.assertEqual(movement.issue_reason, StockMovement.IssueReason.SALE)

    def test_stock_issue_post_stores_repair_reason_and_department(self):
        self.client.force_login(self.storekeeper)
        response = self.client.post(
            reverse("stock_issue"),
            {
                "item": self.item.pk,
                "warehouse": self.warehouse.pk,
                "location": self.location.pk,
                "qty": "1.000",
                "issue_reason": StockMovement.IssueReason.REPAIR,
                "department": "Ремонтний цех",
                "recipient": "",
                "document_number": "",
                "comment": "",
                "occurred_at": "2026-01-15T11:00",
            },
        )

        self.assertEqual(response.status_code, 302)
        movement = StockMovement.objects.latest("id")
        self.assertEqual(movement.issue_reason, StockMovement.IssueReason.REPAIR)
        self.assertEqual(movement.department, "Ремонтний цех")

    def test_stock_issue_rejects_quantity_greater_than_balance(self):
        self.client.force_login(self.storekeeper)
        response = self.client.post(
            reverse("stock_issue"),
            {
                "item": self.item.pk,
                "warehouse": self.warehouse.pk,
                "location": self.location.pk,
                "qty": "99.000",
                "issue_reason": StockMovement.IssueReason.OTHER,
                "department": "",
                "recipient": "",
                "document_number": "",
                "comment": "",
                "occurred_at": "2026-01-15T12:00",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Недостатньо залишку для видачі")
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.qty, Decimal("7.000"))

    def test_movements_show_translated_issue_reason(self):
        StockMovement.objects.create(
            movement_type=StockMovement.MovementType.OUT,
            item=self.item,
            qty=Decimal("1.000"),
            source_location=self.location,
            issue_reason=StockMovement.IssueReason.SALE,
            department="Цех 1",
            document_number="DOC-1",
        )
        self.client.force_login(self.storekeeper)
        response = self.client.get(reverse("movement_list"), HTTP_ACCEPT_LANGUAGE="uk")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Продаж")
        self.assertContains(response, "Цех 1")
        self.assertContains(response, "DOC-1")

    def test_auditor_cannot_create_stock_issue_or_transfer(self):
        self.client.force_login(self.auditor)
        response = self.client.get(reverse("stock_issue"))
        self.assertEqual(response.status_code, 403)

        response = self.client.post(reverse("stock_issue"), {})
        self.assertEqual(response.status_code, 403)

        response = self.client.get(reverse("stock_transfer"))
        self.assertEqual(response.status_code, 403)

        response = self.client.post(reverse("stock_transfer"), {})
        self.assertEqual(response.status_code, 403)

    def test_help_page_opens(self):
        self.client.force_login(self.auditor)
        response = self.client.get(reverse("help"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Центр допомоги")

class StockTransferFormTests(TestCase):
    def setUp(self):
        self.unit = Unit.objects.create(name="Form unit", symbol="fu")
        self.item = Item.objects.create(name="Form item", unit=self.unit)
        self.source_warehouse = Warehouse.objects.create(name="Form source warehouse")
        self.destination_warehouse = Warehouse.objects.create(name="Form destination warehouse")
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

    def test_source_location_must_belong_to_source_warehouse(self):
        form = StockTransferForm(
            data=self.form_data(source_location=self.other_location.pk)
        )

        self.assertFalse(form.is_valid())
        self.assertIn("source_location", form.errors)

    def test_destination_location_must_belong_to_destination_warehouse(self):
        form = StockTransferForm(
            data=self.form_data(destination_location=self.source_location.pk)
        )

        self.assertFalse(form.is_valid())
        self.assertIn("destination_location", form.errors)

    def test_same_source_and_destination_location_is_invalid(self):
        form = StockTransferForm(
            data=self.form_data(
                destination_warehouse=self.source_warehouse.pk,
                destination_location=self.source_location.pk,
            )
        )

        self.assertFalse(form.is_valid())
        self.assertIn("destination_location", form.errors)

    def test_qty_must_be_positive(self):
        form = StockTransferForm(data=self.form_data(qty="0.000"))

        self.assertFalse(form.is_valid())
        self.assertIn("qty", form.errors)


class WarehouseWorkflowTests(TestCase):
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

    def test_item_without_barcode_gets_itm_barcode(self):
        self.assertTrue(self.item.barcode.barcode.startswith("ITM"))
        self.assertEqual(len(self.item.barcode.barcode), 13)

    def test_warehouse_without_barcode_gets_wh_barcode(self):
        self.assertTrue(self.warehouse.barcode.barcode.startswith("WH"))
        self.assertEqual(len(self.warehouse.barcode.barcode), 12)

    def test_location_types_get_loc_and_rck_barcodes(self):
        rack = Location.objects.create(
            warehouse=self.warehouse,
            name="Workflow rack",
            location_type=Location.LocationType.RACK,
        )
        self.assertTrue(self.location.barcode.barcode.startswith("LOC"))
        self.assertTrue(rack.barcode.barcode.startswith("RCK"))

    def test_receive_stock_ui_increases_balance_creates_movement_and_barcode(self):
        self.item.barcode = None
        self.item.save(update_fields=["barcode"])
        response = self.client.post(
            reverse("stock_receive"),
            {
                "item": self.item.pk,
                "warehouse": self.warehouse.pk,
                "location": self.location.pk,
                "qty": "7.000",
                "comment": "UI receive",
                "occurred_at": timezone.now().strftime("%Y-%m-%dT%H:%M"),
            },
        )
        self.assertEqual(response.status_code, 302)
        balance = StockBalance.objects.get(item=self.item, location=self.location)
        movement = StockMovement.objects.get(comment="UI receive")
        self.item.refresh_from_db()
        self.assertEqual(balance.qty, Decimal("7.000"))
        self.assertEqual(movement.movement_type, StockMovement.MovementType.IN)
        self.assertIsNotNone(self.item.barcode)


    def test_transfer_stock_ui_creates_transfer_movement(self):
        from .services.stock import receive_stock

        receive_stock(item=self.item, location=self.location, qty=Decimal("5.000"))
        response = self.client.post(
            reverse("stock_transfer"),
            {
                "item": self.item.pk,
                "source_warehouse": self.warehouse.pk,
                "source_location": self.location.pk,
                "destination_warehouse": self.destination_warehouse.pk,
                "destination_location": self.destination_location.pk,
                "qty": "2.000",
                "comment": "UI transfer",
                "occurred_at": timezone.now().strftime("%Y-%m-%dT%H:%M"),
            },
        )

        self.assertEqual(response.status_code, 302)
        movement = StockMovement.objects.get(comment="UI transfer")
        self.assertEqual(movement.movement_type, StockMovement.MovementType.TRANSFER)
        self.assertEqual(movement.source_location, self.location)
        self.assertEqual(movement.destination_location, self.destination_location)
        self.assertEqual(
            StockBalance.objects.get(item=self.item, location=self.location).qty,
            Decimal("3.000"),
        )
        self.assertEqual(
            StockBalance.objects.get(
                item=self.item, location=self.destination_location
            ).qty,
            Decimal("2.000"),
        )

    def test_transfer_result_page_shows_item_quantity_source_and_destination(self):
        movement = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.TRANSFER,
            item=self.item,
            qty=Decimal("2.000"),
            source_location=self.location,
            destination_location=self.destination_location,
            comment="Result transfer",
        )

        response = self.client.get(reverse("stock_transfer_result", args=[movement.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Workflow item")
        self.assertContains(response, "2,000")
        self.assertContains(response, "Workflow location")
        self.assertContains(response, "Workflow destination location")

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

    def test_initial_balance_creates_stock_movement(self):
        response = self.client.post(
            reverse("stock_initial"),
            {
                "item": self.item.pk,
                "warehouse": self.warehouse.pk,
                "location": self.location.pk,
                "qty": "3.000",
                "comment": "Initial UI",
                "occurred_at": timezone.now().strftime("%Y-%m-%dT%H:%M"),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            StockMovement.objects.filter(
                comment="Initial UI",
                movement_type=StockMovement.MovementType.INITIAL_BALANCE,
            ).exists()
        )

    def test_movement_page_available_and_filter_works(self):
        from .services.stock import receive_stock

        receive_stock(item=self.item, location=self.location, qty=Decimal("2.000"), comment="Find me")
        response = self.client.get(reverse("movement_list"), {"q": "Workflow item"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Find me")
        response = self.client.get(reverse("movement_list"), {"q": "nothing"})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Find me")

    def test_pdf_label_generates(self):
        from .services.labels import generate_item_label_pdf

        pdf = generate_item_label_pdf(self.item)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 1000)
        self.assertEqual(self.item.barcode.barcode, "ITM0000000001")

    def test_pdf_label_generates_with_cyrillic_name(self):
        from unittest.mock import patch

        from .services import labels

        regular_path, _bold_path = labels._discover_label_ttf_fonts()
        if not regular_path:
            self.skipTest("Unicode TTF font is not available in this environment")

        self.item.name = "Кінцевий вимикач"
        self.item.save(update_fields=["name"])

        with patch(
            "core.services.labels._fallback_pdf",
            side_effect=AssertionError("fallback must not be used"),
        ):
            pdf = labels.generate_item_label_pdf(self.item)

        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 1000)
        self.assertEqual(
            labels._get_label_font_names(needs_unicode=True),
            ("WarehouseSans", "WarehouseSansBold"),
        )

    def test_printer_labeltemplate_and_printjob_can_be_created(self):
        printer = Printer.objects.create(name="Test printer", system_name="TEST_PRINTER")
        template = LabelTemplate.objects.create(name="58x40", is_default=True)
        job = PrintJob.objects.create(
            printer=printer,
            item=self.item,
            barcode=self.item.barcode.barcode,
            label_template=template,
            copies=1,
            user=self.user,
        )
        self.assertEqual(job.status, PrintJob.Status.PENDING)

    def test_lp_error_does_not_break_print_page(self):
        from unittest.mock import patch

        printer = Printer.objects.create(name="Broken printer", system_name="BROKEN", is_default=True)
        LabelTemplate.objects.create(name="Default label", is_default=True)

        class Result:
            returncode = 1
            stdout = ""
            stderr = "lp failed"

        with patch("core.services.labels.subprocess.run", return_value=Result()):
            response = self.client.post(
                reverse("item_label_print", args=[self.item.pk]),
                {"printer": printer.pk, "label_template": LabelTemplate.objects.get().pk, "copies": 1},
            )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(PrintJob.objects.filter(status=PrintJob.Status.FAILED).exists())

    def test_barcode_lookup_finds_item(self):
        response = self.client.get(
            reverse("barcode_lookup"), {"barcode": self.item.barcode.barcode}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "found": True,
                "type": "item",
                "id": self.item.pk,
                "name": self.item.name,
                "internal_code": self.item.internal_code or "",
                "barcode": self.item.barcode.barcode,
            },
        )

    def test_barcode_lookup_finds_warehouse(self):
        response = self.client.get(
            reverse("barcode_lookup"), {"barcode": self.warehouse.barcode.barcode}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "found": True,
                "type": "warehouse",
                "id": self.warehouse.pk,
                "name": self.warehouse.name,
                "barcode": self.warehouse.barcode.barcode,
            },
        )

    def test_barcode_lookup_finds_location(self):
        response = self.client.get(
            reverse("barcode_lookup"), {"barcode": self.location.barcode.barcode}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "found": True,
                "type": "location",
                "id": self.location.pk,
                "name": self.location.name,
                "warehouse_id": self.warehouse.pk,
                "warehouse_name": self.warehouse.name,
                "barcode": self.location.barcode.barcode,
            },
        )

    def test_barcode_lookup_returns_not_found_for_unknown_barcode(self):
        response = self.client.get(reverse("barcode_lookup"), {"barcode": "UNKNOWN"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"found": False, "message": "Штрихкод не знайдено."},
        )

    def test_anonymous_user_cannot_access_barcode_lookup(self):
        self.client.logout()

        response = self.client.get(
            reverse("barcode_lookup"), {"barcode": self.item.barcode.barcode}
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_receive_page_contains_barcode_scanner_field(self):
        response = self.client.get(reverse("stock_receive"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "receive-barcode-scanner")
        self.assertContains(response, "Сканувати штрихкод")

    def test_issue_page_contains_barcode_scanner_field(self):
        response = self.client.get(reverse("stock_issue"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "issue-barcode-scanner")
        self.assertContains(response, "Сканувати штрихкод")

    def test_inventory_count_page_contains_barcode_scanner_field(self):
        from .services.inventory import create_inventory_count

        StockBalance.objects.create(
            item=self.item, location=self.location, qty=Decimal("1.000")
        )
        inventory_count = create_inventory_count(
            warehouse=self.warehouse, user=self.user
        )

        response = self.client.get(reverse("inventory_count", args=[inventory_count.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "inventory-barcode-scanner")
        self.assertContains(response, "Сканувати штрихкод")

    def test_unauthorized_user_redirects_to_login(self):
        self.client.logout()
        response = self.client.get(reverse("stock_receive"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])


class DashboardNavigationPolishTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        call_command("compilemessages", verbosity=0)

    def setUp(self):
        call_command("init_roles", stdout=StringIO())
        User = get_user_model()
        self.admin = User.objects.create_user(username="dash-admin", password="pw")
        self.admin.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.storekeeper = User.objects.create_user(
            username="dash-storekeeper", password="pw"
        )
        self.storekeeper.groups.add(Group.objects.get(name="Комірник"))
        self.auditor = User.objects.create_user(username="dash-auditor", password="pw")
        self.auditor.groups.add(Group.objects.get(name="Перегляд / аудитор"))

    def dashboard_for(self, user, path=None):
        from django.utils import translation

        translation.activate("en" if path and path.startswith("/en/") else "uk")
        self.client.force_login(user)
        return self.client.get(path or reverse("dashboard"))

    def tearDown(self):
        from django.utils import translation

        translation.activate("uk")

    def test_admin_dashboard_shows_stock_transfer_card(self):
        response = self.dashboard_for(self.admin, "/uk/")

        self.assertContains(response, "Переміщення товару")

    def test_storekeeper_dashboard_shows_stock_transfer_card(self):
        response = self.dashboard_for(self.storekeeper, "/uk/")

        self.assertContains(response, "Переміщення товару")

    def test_auditor_dashboard_hides_stock_transfer_card(self):
        response = self.dashboard_for(self.auditor, "/uk/")

        self.assertNotContains(response, "Переміщення товару")

    def test_storekeeper_can_open_ukrainian_stock_transfer_page(self):
        response = self.dashboard_for(self.storekeeper, "/uk/stock/transfer/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Переміщення товару")

    def test_english_dashboard_contains_stock_transfer(self):
        response = self.dashboard_for(self.admin, "/en/")

        self.assertContains(response, "Stock transfer")

    def test_english_transfer_page_has_no_ukrainian_transfer_phrases(self):
        response = self.dashboard_for(self.admin, "/en/stock/transfer/")
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("Stock transfer", html)
        for phrase in [
            "Переміщення товару",
            "Перемістіть товар",
            "Склад-відправник",
            "Локація-відправник",
            "Перемістити",
        ]:
            self.assertNotIn(phrase, html)

    def test_ukrainian_transfer_page_has_no_english_transfer_phrases(self):
        response = self.dashboard_for(self.admin, "/uk/stock/transfer/")
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("Переміщення товару", html)
        for phrase in [
            "Stock transfer",
            "Move items between warehouses or locations",
            "Source warehouse",
            "Destination location",
        ]:
            self.assertNotIn(phrase, html)

    def test_language_switcher_only_exposes_ukrainian_and_english(self):
        response = self.dashboard_for(self.admin, "/uk/")
        html = response.content.decode()

        self.assertIn("Українська", html)
        self.assertIn("English", html)
        for language_name in [
            "Русский",
            "Deutsch",
            "Polski",
            "Français",
            "Español",
            "Italiano",
            "Português",
            "Türkçe",
        ]:
            self.assertNotIn(language_name, html)

    def test_ukrainian_dashboard_uses_only_ukrainian_navigation_terms(self):
        response = self.dashboard_for(self.admin, "/uk/")
        html = response.content.decode()

        for phrase in [
            "Головна",
            "Складські операції",
            "Прихід товару",
            "Видача товару",
            "Переміщення товару",
            "Початкові залишки",
            "Інвентаризація",
            "Залишки",
            "Рухи товарів",
        ]:
            self.assertIn(phrase, html)
        for phrase in [
            "Warehouse operations",
            "Stock receipt",
            "Stock issue",
            "Initial balances",
            "Stock transfer",
            "Stock movements",
            "Open",
        ]:
            self.assertNotIn(phrase, html)

    def test_english_dashboard_uses_only_english_navigation_terms(self):
        response = self.dashboard_for(self.admin, "/en/")
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("YANTOS", html)
        for phrase in [
            "Home",
            "Warehouse operations",
            "Stock receipt",
            "Stock issue",
            "Stock transfer",
            "Initial balances",
            "Inventory count",
            "Stock balances",
            "Stock movements",
            "Open",
        ]:
            self.assertIn(phrase, html)
        for phrase in [
            "Головна",
            "Складські операції",
            "Прихід товару",
            "Видача товару",
            "Початкові залишки",
            "Переміщення товару",
            "Рухи товарів",
            "Відкрити",
        ]:
            self.assertNotIn(phrase, html)

    def test_english_core_pages_do_not_show_ukrainian_menu_words(self):
        forbidden_phrases = [
            "Головна",
            "Навігація",
            "Складські операції",
            "Прихід товару",
            "Видача товару",
            "Початкові залишки",
            "Переміщення товару",
            "Залишки",
            "Рухи товарів",
            "Довідники",
            "Етикетки",
            "Адміністрування",
            "Допомога",
            "Відкрити",
            "Зберегти",
            "Скасувати",
        ]
        for path in [
            "/en/stock/balances/",
            "/en/stock/movements/",
            "/en/stock/receive/",
            "/en/stock/issue/",
            "/en/stock/transfer/",
            "/en/stock/initial/",
            "/en/stock/inventory/",
        ]:
            with self.subTest(path=path):
                response = self.dashboard_for(self.admin, path)
                html = response.content.decode()

                self.assertEqual(response.status_code, 200)
                self.assertIn("YANTOS", html)
                for phrase in forbidden_phrases:
                    self.assertNotIn(phrase, html)

    def test_ukrainian_core_pages_do_not_show_english_menu_words(self):
        forbidden_phrases = [
            "Warehouse operations",
            "Stock receipt",
            "Stock issue",
            "Stock transfer",
            "Initial balances",
            "Stock movements",
            "Stock balances",
            "Stock transfer",
            "Directories",
            "Labels",
            "Administration",
            "Management",
            "Help",
            "Open",
            "Save",
            "Cancel",
        ]
        for path in [
            "/uk/stock/balances/",
            "/uk/stock/movements/",
            "/uk/stock/receive/",
            "/uk/stock/issue/",
            "/uk/stock/transfer/",
            "/uk/stock/initial/",
            "/uk/stock/inventory/",
        ]:
            with self.subTest(path=path):
                response = self.dashboard_for(self.admin, path)
                html = response.content.decode()

                self.assertEqual(response.status_code, 200)
                self.assertIn("YANTOS", html)
                for phrase in forbidden_phrases:
                    self.assertNotIn(phrase, html)

    def test_admin_dashboard_contains_required_groups_and_operations(self):
        response = self.dashboard_for(self.admin)

        self.assertContains(response, "Складські операції")
        self.assertContains(response, "Контроль")
        self.assertContains(response, "Довідники")
        for label in [
            "Прихід товару",
            "Видача товару",
            "Переміщення товару",
            "Початкові залишки",
            "Інвентаризація",
        ]:
            self.assertContains(response, label)

    def test_storekeeper_dashboard_contains_operations_without_management_or_recipients(self):
        response = self.dashboard_for(self.storekeeper)

        self.assertContains(response, "Складські операції")
        for label in [
            "Прихід товару",
            "Видача товару",
            "Переміщення товару",
            "Початкові залишки",
            "Інвентаризація",
        ]:
            self.assertContains(response, label)
        self.assertNotContains(response, "Керування")
        self.assertNotContains(response, "Отримувачі")

    def test_auditor_dashboard_is_view_only(self):
        response = self.dashboard_for(self.auditor)

        for label in ["Прихід товару", "Видача товару", "Переміщення товару", "Початкові залишки"]:
            self.assertNotContains(response, label)
        for label in ["Залишки", "Рухи товарів", "Інвентаризація"]:
            self.assertContains(response, label)

    def test_storekeeper_sidebar_hides_recipients(self):
        response = self.dashboard_for(self.storekeeper)

        self.assertNotContains(response, "Отримувачі")

    def test_auditor_sidebar_hides_create_operations(self):
        response = self.dashboard_for(self.auditor)

        for label in ["Прихід товару", "Видача товару", "Переміщення товару", "Початкові залишки"]:
            self.assertNotContains(response, label)
        self.assertContains(response, "Інвентаризація")

    def test_mobile_menu_hides_management_for_storekeeper(self):
        response = self.dashboard_for(self.storekeeper)
        html = response.content.decode()

        mobile_start = html.index('navbar-nav me-auto mb-2 mb-lg-0 d-lg-none')
        mobile_end = html.index('ms-auto d-flex', mobile_start)
        mobile_menu = html[mobile_start:mobile_end]
        self.assertNotIn("Керування", mobile_menu)
        self.assertNotIn("management/", mobile_menu)

    def test_english_dashboard_has_no_new_ukrainian_phrases_and_keeps_yantos_brand(self):
        response = self.dashboard_for(self.admin, "/en/")
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("YANTOS", html)
        self.assertIn("Warehouse operations", html)
        for phrase in [
            "Складські операції",
            "Прихід товару",
            "Видача товару",
            "Початкові залишки",
            "Переміщення товару",
            "Керування",
        ]:
            self.assertNotIn(phrase, html)

