from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import translation

from core.models import Item, PurchaseRequest, StockBalance, StockMovement, Unit, Warehouse
from core.services.purchase_requests import archive_purchase_request
from core.templatetags.core_extras import qty
from core.tests.warehouse_access_utils import grant_warehouse_access


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class TableHeaderFilterUITests(TestCase):
    def setUp(self):
        call_command("init_roles", stdout=StringIO())
        User = get_user_model()
        self.user = User.objects.create_user("filter-ui", password="pw")
        self.user.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.client.force_login(self.user)
        self.unit = Unit.objects.create(name="Piece", symbol="pc")
        self.item = Item.objects.create(
            name="Filter test item",
            internal_code="FILTER-1",
            unit=self.unit,
        )
        self.warehouse = Warehouse.objects.create(name="Filter warehouse")
        self.location = self.warehouse.locations.create(name="A-01")
        grant_warehouse_access(self.user, self.warehouse, can_delegate=True)
        StockBalance.objects.create(
            item=self.item, warehouse=self.warehouse, location=self.location, qty=Decimal("5.000")
        )

    def test_qty_filter_hides_redundant_decimal_zeroes(self):
        with translation.override("uk"):
            self.assertEqual(qty(Decimal("1.000")), "1")
            self.assertEqual(qty(Decimal("1.500")), "1,5")
            self.assertEqual(qty(Decimal("1.250")), "1,25")
            self.assertEqual(qty(Decimal("0.125")), "0,125")

    def test_purchase_archive_uses_header_dropdown_filters(self):
        purchase_request = PurchaseRequest.objects.create(
            requested_by=self.user,
            title="Archived filter request",
            requested_qty=Decimal("2.000"),
            unit="pc",
            status=PurchaseRequest.Status.RECEIVED,
            approval_status=PurchaseRequest.ApprovalStatus.APPROVED,
        )
        archive_purchase_request(purchase_request, archived_by=self.user, reason="Done")

        response = self.client.get(
            reverse("purchase_request_archive"),
            {"q": "Archived", "quantity_from": "1", "quantity_to": "3"},
        )

        self.assertContains(response, "purchase-request-table--archive")
        self.assertNotContains(response, "purchase-filter-panel")
        self.assertNotContains(response, "purchase-filter-grid")
        self.assertContains(response, "purchase-list-tabs")
        self.assertContains(response, "table-filter-heading")
        self.assertContains(response, "table-filter-toggle purchase-filter-toggle active")
        self.assertContains(response, "dropdown-menu-end")
        self.assertContains(response, 'name="quantity_from"')
        self.assertContains(response, 'name="quantity_to"')
        self.assertContains(response, "purchase-archive-stock-cell")
        self.assertContains(response, "purchase-archive-meta-cell")
        self.assertContains(response, "purchase-archive-label")
        self.assertNotContains(response, "purchase-archive-qty-cell")
        self.assertNotContains(response, "purchase-archive-date-cell")
        self.assertContains(response, "Archived filter request")

    def test_operation_audit_uses_header_dropdown_filters_without_top_panel(self):
        StockMovement.objects.create(
            movement_type=StockMovement.MovementType.IN,
            item=self.item,
            qty=Decimal("1.000"),
            destination_location=self.location,
            document_number="DOC-1",
        )

        response = self.client.get(
            reverse("stock_operation_audit"),
            {
                "q": "Filter",
                "quantity_from": "1",
                "quantity_to": "2",
                "warehouse": self.warehouse.pk,
                "location": self.location.pk,
                "document": "DOC",
                "cancelled": "no",
            },
        )

        self.assertNotContains(response, "filter-panel")
        self.assertContains(response, "operation-audit-filter-form")
        self.assertContains(response, "table-filter-heading")
        self.assertContains(response, "table-filter-toggle active")
        self.assertContains(response, "dropdown-menu-end")
        self.assertContains(response, 'name="quantity_from"')
        self.assertContains(response, 'name="quantity_to"')
        self.assertContains(response, 'name="location"')
        self.assertContains(response, 'name="document"')

    def test_item_list_uses_header_dropdown_filters_without_top_filter_panel(self):
        response = self.client.get(reverse("item_list"), {"q": "FILTER", "status": "all"})

        self.assertNotContains(response, "filter-panel")
        self.assertContains(response, "directory-filter-form")
        self.assertContains(response, "table-filter-heading")
        self.assertContains(response, "table-filter-toggle active")
        self.assertContains(response, "table-filter-menu table-filter-menu--wide")
        self.assertContains(response, "dropdown-menu-end")
        self.assertContains(response, 'name="q"')
        self.assertContains(response, 'value="FILTER"')
        self.assertContains(response, 'name="status"')

    def test_stock_balance_list_uses_header_dropdown_filters(self):
        response = self.client.get(
            reverse("stockbalance_list"),
            {
                "q": "FILTER",
                "warehouse": self.warehouse.pk,
                "location": self.location.pk,
            },
        )

        self.assertNotContains(response, "filter-panel")
        self.assertContains(response, "stockbalance-filter-form")
        self.assertContains(response, "stockbalance-card")
        self.assertContains(response, "stockbalance-table")
        self.assertContains(response, "table-filter-heading")
        self.assertContains(response, "table-filter-toggle active")
        self.assertContains(response, "dropdown-menu-end")
        self.assertContains(response, 'name="q"')
        self.assertContains(response, 'value="FILTER"')
        self.assertContains(response, 'name="warehouse"')
        self.assertContains(response, 'name="location"')

    def test_stock_balance_quantities_do_not_show_redundant_zeroes(self):
        fractional_item = Item.objects.create(
            name="Fractional balance item",
            internal_code="FILTER-2",
            unit=self.unit,
        )
        StockBalance.objects.create(
            item=fractional_item,
            warehouse=self.warehouse,
            location=self.location,
            qty=Decimal("1.500"),
        )

        response = self.client.get(reverse("stockbalance_list"))
        html = response.content.decode()

        self.assertIn(">5<", html)
        self.assertIn(">1,5<", html)
        self.assertNotIn("5,000", html)
        self.assertNotIn("1,500", html)

    def test_movement_list_uses_header_dropdown_filters(self):
        StockMovement.objects.create(
            movement_type=StockMovement.MovementType.IN,
            item=self.item,
            qty=Decimal("1.000"),
            destination_location=self.location,
            document_number="DOC-1",
        )

        response = self.client.get(
            reverse("movement_list"),
            {
                "q": "Filter",
                "movement_type": StockMovement.MovementType.IN,
                "warehouse": self.warehouse.pk,
                "date_from": "2026-06-01",
                "document_number": "DOC",
            },
        )

        self.assertNotContains(response, "filter-panel")
        self.assertContains(response, "movement-filter-form")
        self.assertContains(response, "table-filter-toolbar")
        self.assertContains(response, "table-filter-heading")
        self.assertContains(response, "table-filter-toggle active")
        self.assertContains(response, "dropdown-menu-end")
        self.assertContains(response, 'name="date_from"')
        self.assertContains(response, 'name="movement_type"')
        self.assertContains(response, 'name="q"')
        self.assertContains(response, 'value="Filter"')
        self.assertContains(response, 'name="document_number"')

    def test_stock_documents_registry_uses_movement_document_table(self):
        movement = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.IN,
            item=self.item,
            qty=Decimal("1.000"),
            destination_location=self.location,
            document_number="IN-2026-000001",
        )

        response = self.client.get(reverse("stock_documents"), {"document_number": "IN-2026"})

        self.assertContains(response, "Реєстр документів")
        self.assertContains(response, "Документи складських операцій")
        self.assertContains(response, "Номер документа")
        self.assertContains(response, "IN-2026-000001")
        self.assertContains(response, "Друкувати документ")
        self.assertContains(response, reverse("stock_movement_print", args=[movement.pk]))
        self.assertContains(response, 'name="document_number"')

    def test_stock_documents_print_all_document_types_by_document_number(self):
        movement_types = [
            StockMovement.MovementType.IN,
            StockMovement.MovementType.OUT,
            StockMovement.MovementType.RETURN,
            StockMovement.MovementType.TRANSFER,
            StockMovement.MovementType.WRITEOFF,
            StockMovement.MovementType.INITIAL_BALANCE,
        ]

        for index, movement_type in enumerate(movement_types, start=1):
            location_fields = {}
            if movement_type in {
                StockMovement.MovementType.OUT,
                StockMovement.MovementType.WRITEOFF,
            }:
                location_fields["source_location"] = self.location
            elif movement_type == StockMovement.MovementType.TRANSFER:
                location_fields["source_location"] = self.location
                location_fields["destination_location"] = self.location
            else:
                location_fields["destination_location"] = self.location
            movement = StockMovement.objects.create(
                movement_type=movement_type,
                item=self.item,
                qty=Decimal("1.000"),
                document_number=f"TEST-2026-{index:06d}",
                **location_fields,
            )

            with self.subTest(movement_type=movement_type):
                response = self.client.get(reverse("stock_movement_print", args=[movement.pk]))
                self.assertContains(response, f"Складський документ {movement.document_number}")
                self.assertContains(response, "Номер документа")
                self.assertContains(response, movement.document_number)
                self.assertContains(response, "Службовий ID операції")

    def test_old_document_without_number_still_opens_for_printing(self):
        movement = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.IN,
            item=self.item,
            qty=Decimal("1.000"),
            destination_location=self.location,
            document_number="",
        )

        response = self.client.get(reverse("stock_movement_print", args=[movement.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Складський документ —")

    def test_table_filter_and_archive_print_css_rules_exist(self):
        css = (PROJECT_ROOT / "static/core/css/app.css").read_text()

        self.assertIn(".table-filter-heading", css)
        self.assertIn(".table-filter-toggle", css)
        self.assertIn(".table-filter-menu", css)
        self.assertIn(".table-filter-menu--wide", css)
        self.assertIn(".stockbalance-table", css)
        self.assertIn(".stockbalance-table thead th{position:sticky", css)
        self.assertIn(".stockbalance-actions{display:flex", css)
        self.assertNotIn(".purchase-filter-panel", css)
        self.assertNotIn(".purchase-filter-grid", css)
        self.assertIn(".purchase-status-menu", css)
        self.assertIn(".purchase-list-tabs", css)
        self.assertIn("@media (max-width:767.98px)", css)
        self.assertIn(".purchase-status-inline-form{right:auto;left:0;max-width:calc(100vw - 2rem)", css)
        self.assertIn(".purchase-request-table{min-width:880px}", css)
        self.assertIn(".purchase-request-table--archive{min-width:980px}", css)
        self.assertIn(".purchase-request-table--archive", css)
        self.assertIn(".purchase-request-table--archive td", css)
        self.assertIn(".purchase-archive-stock-cell", css)
        self.assertIn(".purchase-archive-meta-cell", css)
        self.assertIn("@media print", css)
        self.assertIn(".yantos-navbar", css)
        self.assertIn(".sticky-top{position:static!important}", css)
