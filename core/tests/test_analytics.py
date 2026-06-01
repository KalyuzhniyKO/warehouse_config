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
from .warehouse_access_utils import grant_warehouse_access
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


class AnalyticsInterfaceTests(TestCase):

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
        grant_warehouse_access(
            self.admin,
            [self.warehouse, self.other_warehouse],
            can_delegate=True,
        )
        grant_warehouse_access(
            self.storekeeper,
            [self.warehouse, self.other_warehouse],
        )
        grant_warehouse_access(
            self.auditor,
            [self.warehouse, self.other_warehouse],
        )
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

    def test_analytics_redirects_warehouse_admin_to_management_analytics(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("analytics"))
        self.assertRedirects(response, reverse("management_analytics"))

    def test_analytics_counts_in_and_out(self):
        from ..services.analytics import get_movement_summary

        summary = get_movement_summary({"warehouse": self.warehouse})
        self.assertEqual(summary["total_in"], Decimal("10.000"))
        self.assertEqual(summary["total_out"], Decimal("3.000"))

    def test_analytics_filters_by_date(self):
        from ..services.analytics import get_movement_summary

        summary = get_movement_summary(
            {"date_from": timezone.datetime(2026, 1, 11).date()}
        )
        self.assertEqual(summary["total_in"], Decimal("5.000"))
        self.assertEqual(summary["total_out"], Decimal("3.000"))

    def test_analytics_filters_by_warehouse(self):
        from ..services.analytics import get_movement_summary

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


class WarehouseAnalyticsAuditTests(TestCase):
    def setUp(self):
        call_command("init_roles", stdout=StringIO())
        User = get_user_model()
        self.superuser = User.objects.create_superuser(
            username="analytics-root", password="pw", email="analytics-root@example.com"
        )
        self.admin = User.objects.create_user(username="analytics-admin", password="pw")
        self.admin.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.user = User.objects.create_user(username="analytics-user", password="pw")
        self.user.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.no_access_user = User.objects.create_user(username="analytics-no-access", password="pw")
        self.no_access_user.groups.add(Group.objects.get(name="Адміністратор складу"))

        self.unit = Unit.objects.create(name="Piece", symbol="pc")
        self.item = Item.objects.create(name="Audit Cable", unit=self.unit, internal_code="AUD-CBL")
        self.other_item = Item.objects.create(name="Audit Bolt", unit=self.unit, internal_code="AUD-BLT")
        self.warehouse = Warehouse.objects.create(name="Audit Warehouse A")
        self.other_warehouse = Warehouse.objects.create(name="Audit Warehouse B")
        self.location = Location.objects.create(
            warehouse=self.warehouse, name="Основна локація"
        )
        self.other_location = Location.objects.create(
            warehouse=self.other_warehouse, name="Основна локація"
        )
        self.recipient = Recipient.objects.create(name="Audit Recipient")
        grant_warehouse_access(self.admin, self.warehouse, can_delegate=True)
        grant_warehouse_access(self.user, self.warehouse)
        grant_warehouse_access(self.no_access_user, [])

        self.now = timezone.now()
        self.today = timezone.localdate(self.now)
        StockBalance.objects.create(
            item=self.item, location=self.location, qty=Decimal("12.000")
        )
        StockBalance.objects.create(
            item=self.other_item, location=self.other_location, qty=Decimal("4.000")
        )
        self.receive = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.IN,
            item=self.item,
            qty=Decimal("20.000"),
            destination_location=self.location,
            occurred_at=self.now,
            document_number="AUD-IN",
        )
        self.issue = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.OUT,
            item=self.item,
            qty=Decimal("5.000"),
            source_location=self.location,
            recipient=self.recipient,
            department="Audit Dept",
            occurred_at=self.now,
            document_number="AUD-OUT",
        )
        self.return_movement = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.RETURN,
            item=self.item,
            qty=Decimal("2.000"),
            destination_location=self.location,
            recipient=self.recipient,
            occurred_at=self.now,
            document_number="AUD-RET",
        )
        self.writeoff = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.WRITEOFF,
            item=self.item,
            qty=Decimal("1.000"),
            source_location=self.location,
            occurred_at=self.now,
            document_number="AUD-WOFF",
        )
        self.transfer = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.TRANSFER,
            item=self.item,
            qty=Decimal("3.000"),
            source_location=self.location,
            destination_location=self.other_location,
            occurred_at=self.now,
            document_number="AUD-TRN",
        )
        self.other_receive = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.IN,
            item=self.other_item,
            qty=Decimal("7.000"),
            destination_location=self.other_location,
            occurred_at=self.now,
            document_number="AUD-OTHER-IN",
        )
        self.old_receive = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.IN,
            item=self.item,
            qty=Decimal("11.000"),
            destination_location=self.location,
            occurred_at=self.now - timezone.timedelta(days=45),
            document_number="AUD-OLD-IN",
        )
        self.cancelled = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.IN,
            item=self.item,
            qty=Decimal("99.000"),
            destination_location=self.location,
            occurred_at=self.now,
            document_number="AUD-CANCELLED",
            is_cancelled=True,
        )
        self.reversal = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.OUT,
            item=self.item,
            qty=Decimal("99.000"),
            source_location=self.location,
            occurred_at=self.now,
            document_number="AUD-REVERSAL",
            reversal_of=self.cancelled,
        )
        self.cancelled.cancellation_movement = self.reversal
        self.cancelled.save(update_fields=["cancellation_movement"])

    def summary_for_user(self, user, **filters):
        from core.services.analytics import get_analytics_summary
        from core.services.warehouse_access import get_accessible_warehouses

        filters["accessible_warehouses"] = get_accessible_warehouses(user)
        return get_analytics_summary(filters)

    def test_superuser_analytics_sees_all_warehouse_movements(self):
        summary = self.summary_for_user(self.superuser)
        self.assertEqual(summary["operations_count"], 7)
        self.assertEqual(summary["receive_qty"], Decimal("38.000"))
        self.assertEqual(summary["issue_qty"], Decimal("5.000"))
        self.assertEqual(summary["return_qty"], Decimal("2.000"))
        self.assertEqual(summary["writeoff_qty"], Decimal("1.000"))
        self.assertEqual(summary["positions_with_stock"], 2)

    def test_admin_analytics_sees_only_accessible_warehouse_movements(self):
        summary = self.summary_for_user(self.admin)
        self.assertEqual(summary["operations_count"], 6)
        self.assertEqual(summary["receive_qty"], Decimal("31.000"))
        self.assertEqual(summary["issue_qty"], Decimal("5.000"))
        self.assertEqual(summary["positions_with_stock"], 1)
        self.assertEqual(summary["total_items"], 1)
        self.assertEqual(summary["active_items"], 1)

    def test_user_without_access_cannot_see_restricted_warehouse_data(self):
        summary = self.summary_for_user(self.no_access_user)
        self.assertEqual(summary["operations_count"], 0)
        self.assertEqual(summary["receive_qty"], Decimal("0.000"))
        self.client.force_login(self.no_access_user)
        response = self.client.get(
            reverse("management_analytics"), {"warehouse": self.other_warehouse.pk}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "0", count=None)
        self.assertNotContains(response, "AUD-OTHER-IN")

    def test_cancelled_and_reversal_movements_are_excluded_from_kpi_totals(self):
        summary = self.summary_for_user(self.superuser, warehouse=self.warehouse)
        self.assertEqual(summary["receive_qty"], Decimal("31.000"))
        self.assertEqual(summary["issue_qty"], Decimal("5.000"))
        self.assertEqual(summary["operations_count"], 6)

    def test_period_30d_includes_recent_operations_and_excludes_old(self):
        from core.services.analytics import get_analytics_filters

        filters = get_analytics_filters({"period": "30d"})
        filters["accessible_warehouses"] = None
        summary = self.summary_for_user(self.superuser, **filters)
        self.assertEqual(summary["operations_count"], 6)
        self.assertEqual(summary["receive_qty"], Decimal("27.000"))

    def test_custom_date_range_includes_and_excludes_correctly(self):
        summary = self.summary_for_user(
            self.superuser,
            date_from=self.today - timezone.timedelta(days=1),
            date_to=self.today,
        )
        self.assertEqual(summary["operations_count"], 6)
        self.assertEqual(summary["receive_qty"], Decimal("27.000"))

        old_summary = self.summary_for_user(
            self.superuser,
            date_from=self.today - timezone.timedelta(days=46),
            date_to=self.today - timezone.timedelta(days=44),
        )
        self.assertEqual(old_summary["operations_count"], 1)
        self.assertEqual(old_summary["receive_qty"], Decimal("11.000"))

    def test_warehouse_filter_matches_source_and_destination_warehouses(self):
        first = self.summary_for_user(self.superuser, warehouse=self.warehouse)
        second = self.summary_for_user(self.superuser, warehouse=self.other_warehouse)
        self.assertEqual(first["operations_count"], 6)
        self.assertEqual(second["operations_count"], 2)
        self.assertEqual(second["receive_qty"], Decimal("7.000"))

    def test_analytics_page_renders_non_zero_values_when_data_exists(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("management_analytics"), {"reset_filters": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "AUD-IN")
        self.assertContains(response, "Audit Cable</a> 5", html=False)
        self.assertNotContains(
            response, "За вибраний період немає складських операцій."
        )

    def test_analytics_page_shows_empty_state_only_when_no_operations_match(self):
        self.client.force_login(self.admin)
        with_data = self.client.get(reverse("management_analytics"))
        self.assertNotContains(
            with_data, "За вибраний період немає складських операцій."
        )
        no_data = self.client.get(
            reverse("management_analytics"),
            {
                "period": "custom",
                "date_from": "2099-01-01",
                "date_to": "2099-01-31",
            },
        )
        self.assertContains(no_data, "За вибраний період немає складських операцій.")

    def test_location_filter_is_technical_label(self):
        from core.forms.analytics import AnalyticsFilterForm

        form = AnalyticsFilterForm(request_user=self.admin)
        self.assertEqual(str(form.fields["location"].label), "Локація")
