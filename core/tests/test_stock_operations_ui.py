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


class StockIssueInterfaceTests(TestCase):

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

    def test_storekeeper_sees_stock_writeoff_on_dashboard(self):
        self.client.force_login(self.storekeeper)
        response = self.client.get("/uk/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Списання товару")

    def test_auditor_does_not_see_stock_writeoff_on_dashboard(self):
        self.client.force_login(self.auditor)
        response = self.client.get("/uk/")

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Списання товару")

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
        movement_count = StockMovement.objects.count()
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
        self.assertContains(response, "alert-danger")
        self.assertEqual(StockMovement.objects.count(), movement_count)
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.qty, Decimal("7.000"))

    def test_stock_writeoff_rejects_quantity_greater_than_balance_with_alert(self):
        self.client.force_login(self.storekeeper)
        movement_count = StockMovement.objects.count()
        response = self.client.post(
            "/uk/stock/writeoff/",
            {
                "item": self.item.pk,
                "warehouse": self.warehouse.pk,
                "location": self.location.pk,
                "qty": "99.000",
                "writeoff_reason": "other",
                "document_number": "",
                "comment": "",
                "occurred_at": "2026-01-15T12:00",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Недостатньо залишку для списання")
        self.assertContains(response, "alert-danger")
        self.assertEqual(StockMovement.objects.count(), movement_count)
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.qty, Decimal("7.000"))

    def test_stock_writeoff_page_available_to_storekeeper(self):
        self.client.force_login(self.storekeeper)
        response = self.client.get("/uk/stock/writeoff/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Списання товару")
        self.assertContains(response, "writeoff-barcode-scanner")

    def test_stock_writeoff_post_decreases_balance_and_creates_writeoff_movement(self):
        self.client.force_login(self.storekeeper)
        response = self.client.post(
            "/uk/stock/writeoff/",
            {
                "item": self.item.pk,
                "warehouse": self.warehouse.pk,
                "location": self.location.pk,
                "qty": "2.000",
                "writeoff_reason": "damaged",
                "document_number": "WO-1",
                "comment": "Damaged cable",
                "occurred_at": "2026-01-15T13:00",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.balance.refresh_from_db()
        movement = StockMovement.objects.latest("id")
        self.assertEqual(self.balance.qty, Decimal("5.000"))
        self.assertEqual(movement.movement_type, StockMovement.MovementType.WRITEOFF)
        self.assertEqual(movement.source_location, self.location)
        self.assertIsNone(movement.destination_location)
        self.assertIn("Причина списання: Зіпсовано", movement.comment)
        self.assertIn("Номер документа: WO-1", movement.comment)
        self.assertIn("Коментар: Damaged cable", movement.comment)

    def test_stock_writeoff_result_page_shows_item_quantity_and_location(self):
        self.client.force_login(self.storekeeper)
        movement = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.WRITEOFF,
            item=self.item,
            qty=Decimal("2.000"),
            source_location=self.location,
            comment="Причина списання: Зіпсовано",
        )

        response = self.client.get(f"/uk/stock/writeoff/{movement.pk}/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Кабель ВВГ")
        self.assertContains(response, "2,000")
        self.assertContains(response, "A1")

    def test_auditor_cannot_access_stock_writeoff_form(self):
        self.client.force_login(self.auditor)
        response = self.client.get("/uk/stock/writeoff/")

        self.assertEqual(response.status_code, 403)

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


class StockOperationWorkflowTests(TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        call_command("compilemessages", locale=["en", "uk"], verbosity=0)

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
        from ..services.stock import receive_stock

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

    def _transfer_data(self, **overrides):
        data = {
            "item": self.item.pk,
            "source_warehouse": self.warehouse.pk,
            "source_location": self.location.pk,
            "destination_warehouse": self.destination_warehouse.pk,
            "destination_location": self.destination_location.pk,
            "qty": "2.000",
            "comment": "Insufficient transfer",
            "occurred_at": timezone.now().strftime("%Y-%m-%dT%H:%M"),
        }
        data.update(overrides)
        return data

    def test_transfer_rejects_insufficient_source_stock_with_ukrainian_alert(self):
        StockBalance.objects.create(
            item=self.item, location=self.location, qty=Decimal("1.000")
        )
        movement_count = StockMovement.objects.filter(
            movement_type=StockMovement.MovementType.TRANSFER
        ).count()

        response = self.client.post("/uk/stock/transfer/", self._transfer_data())

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/stock_transfer_form.html")
        self.assertContains(response, "Недостатньо залишку на локації-відправнику")
        self.assertContains(response, "alert-danger")
        self.assertEqual(
            StockMovement.objects.filter(
                movement_type=StockMovement.MovementType.TRANSFER
            ).count(),
            movement_count,
        )
        self.assertEqual(
            StockBalance.objects.get(item=self.item, location=self.location).qty,
            Decimal("1.000"),
        )
        self.assertFalse(
            StockBalance.objects.filter(
                item=self.item, location=self.destination_location
            ).exists()
        )

    def test_transfer_insufficient_stock_uses_english_message_on_english_page(self):
        StockBalance.objects.create(
            item=self.item, location=self.location, qty=Decimal("1.000")
        )

        response = self.client.post("/en/stock/transfer/", self._transfer_data())
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "Not enough stock at the source location. Check stock before transfer.",
            html,
        )
        self.assertIn("alert-danger", html)
        self.assertNotIn("Недостатньо залишку на локації-відправнику", html)
        self.assertFalse(
            StockMovement.objects.filter(
                movement_type=StockMovement.MovementType.TRANSFER,
                comment="Insufficient transfer",
            ).exists()
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

    def test_unauthorized_user_redirects_to_login(self):
        self.client.logout()
        response = self.client.get(reverse("stock_receive"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])
