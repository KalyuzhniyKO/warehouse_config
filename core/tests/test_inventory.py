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
        from ..services.inventory import create_inventory_count

        inventory_count = create_inventory_count(
            warehouse=self.warehouse, user=self.user, comment="Cycle count"
        )

        self.assertEqual(inventory_count.number, "INV-0000000001")
        self.assertEqual(inventory_count.status, InventoryCount.Status.IN_PROGRESS)
        self.assertEqual(inventory_count.warehouse, self.warehouse)
        self.assertEqual(inventory_count.created_by, self.user)
        self.assertEqual(inventory_count.comment, "Cycle count")

    def test_create_inventory_count_creates_lines_from_current_stock_balances(self):
        from ..services.inventory import create_inventory_count

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
        from ..services.inventory import create_inventory_count

        inventory_count = create_inventory_count(
            warehouse=self.warehouse, location=self.location
        )

        line = inventory_count.lines.get()
        self.assertEqual(line.location, self.location)
        self.assertEqual(line.item, self.item)
        self.assertEqual(line.expected_qty, self.balance.qty)
        self.assertIsNone(line.actual_qty)

    def test_update_inventory_line_actual_qty_calculates_difference(self):
        from ..services.inventory import (
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
        from ..services.inventory import (
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
        from ..services.inventory import create_inventory_count

        create_inventory_count(warehouse=self.warehouse)

        self.assertEqual(StockMovement.objects.count(), 0)

    def test_complete_inventory_count_creates_adjustment_for_surplus(self):
        from ..services.inventory import complete_inventory_count, create_inventory_count

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
        from ..services.inventory import complete_inventory_count, create_inventory_count

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
        from ..services.inventory import complete_inventory_count, create_inventory_count

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
        from ..services.inventory import complete_inventory_count, create_inventory_count

        inventory_count = create_inventory_count(
            warehouse=self.warehouse, location=self.location
        )

        complete_inventory_count(inventory_count=inventory_count, user=self.user)

        self.balance.refresh_from_db()
        self.assertEqual(self.balance.qty, Decimal("7.500"))
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_complete_inventory_count_ignores_zero_difference(self):
        from ..services.inventory import complete_inventory_count, create_inventory_count

        inventory_count = create_inventory_count(
            warehouse=self.warehouse, location=self.location
        )
        line = inventory_count.lines.get()
        line.actual_qty = line.expected_qty
        line.save(update_fields=["actual_qty", "updated_at"])

        complete_inventory_count(inventory_count=inventory_count, user=self.user)

        self.assertEqual(StockMovement.objects.count(), 0)

    def test_complete_inventory_count_marks_completed(self):
        from ..services.inventory import complete_inventory_count, create_inventory_count

        inventory_count = create_inventory_count(
            warehouse=self.warehouse, location=self.location
        )

        completed = complete_inventory_count(inventory_count=inventory_count, user=self.user)

        self.assertEqual(completed.status, InventoryCount.Status.COMPLETED)
        self.assertIsNotNone(completed.completed_at)
        self.assertEqual(completed.approved_by, self.user)

    def test_complete_inventory_count_rejects_repeated_completion(self):
        from ..services.inventory import (
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
        from ..services.inventory import (
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
        from ..services.inventory import create_inventory_count

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
        from ..services.inventory import complete_inventory_count

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


class InventoryBarcodeScannerTests(TestCase):

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

    def test_inventory_count_page_contains_barcode_scanner_field(self):
        from ..services.inventory import create_inventory_count

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
