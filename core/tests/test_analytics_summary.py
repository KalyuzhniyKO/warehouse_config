from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.models import Item, Location, StockBalance, StockMovement, Unit, Warehouse
from core.services.analytics import get_analytics_summary

from .analytics_test_utils import (
    AnalyticsInterfaceTestBase,
    WarehouseAnalyticsAuditTestBase,
)


class AnalyticsSummaryTests(AnalyticsInterfaceTestBase):
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


class WarehouseAnalyticsSummaryTests(WarehouseAnalyticsAuditTestBase):
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


class NoMovementAnalyticsTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.now = timezone.now()
        self.unit = Unit.objects.create(name="Piece", symbol="pc")
        self.warehouse = Warehouse.objects.create(name="Warehouse A")
        self.other_warehouse = Warehouse.objects.create(name="Warehouse B")
        self.location = Location.objects.create(warehouse=self.warehouse, name="A1")
        self.other_location = Location.objects.create(warehouse=self.other_warehouse, name="B1")

    def create_stocked_item(self, code, location=None):
        location = location or self.location
        item = Item.objects.create(name=code, internal_code=code, unit=self.unit)
        StockBalance.objects.create(item=item, location=location, qty=Decimal("1.000"))
        return item

    def period_filters(self, **extra):
        return {
            "date_from": self.today,
            "date_to": self.today,
            **extra,
        }

    def test_receive_movement_inside_period_is_not_counted_as_no_movement(self):
        item = self.create_stocked_item("RECEIVE")
        StockMovement.objects.create(
            movement_type=StockMovement.MovementType.IN,
            item=item,
            qty=Decimal("1.000"),
            destination_location=self.location,
            occurred_at=self.now,
        )

        summary = get_analytics_summary(self.period_filters())

        self.assertEqual(summary["no_movement_count"], 0)

    def test_issue_movement_inside_period_is_not_counted_as_no_movement(self):
        item = self.create_stocked_item("ISSUE")
        StockMovement.objects.create(
            movement_type=StockMovement.MovementType.OUT,
            item=item,
            qty=Decimal("1.000"),
            source_location=self.location,
            occurred_at=self.now,
        )

        summary = get_analytics_summary(self.period_filters())

        self.assertEqual(summary["no_movement_count"], 0)

    def test_item_without_movement_inside_period_is_counted_as_no_movement(self):
        item = self.create_stocked_item("OLD-MOVEMENT")
        StockMovement.objects.create(
            movement_type=StockMovement.MovementType.IN,
            item=item,
            qty=Decimal("1.000"),
            destination_location=self.location,
            occurred_at=self.now - timezone.timedelta(days=1),
        )

        summary = get_analytics_summary(self.period_filters())

        self.assertEqual(summary["no_movement_count"], 1)

    def test_warehouse_filter_only_uses_movements_from_selected_warehouse(self):
        moved_here = self.create_stocked_item("MOVED-HERE")
        moved_elsewhere = self.create_stocked_item("MOVED-ELSEWHERE")
        StockMovement.objects.create(
            movement_type=StockMovement.MovementType.IN,
            item=moved_here,
            qty=Decimal("1.000"),
            destination_location=self.location,
            occurred_at=self.now,
        )
        StockMovement.objects.create(
            movement_type=StockMovement.MovementType.IN,
            item=moved_elsewhere,
            qty=Decimal("1.000"),
            destination_location=self.other_location,
            occurred_at=self.now,
        )

        summary = get_analytics_summary(self.period_filters(warehouse=self.warehouse))

        self.assertEqual(summary["no_movement_count"], 1)

    def test_operation_type_filter_does_not_hide_other_movement_types(self):
        item = self.create_stocked_item("RECEIVE-WITH-ISSUE-FILTER")
        StockMovement.objects.create(
            movement_type=StockMovement.MovementType.IN,
            item=item,
            qty=Decimal("1.000"),
            destination_location=self.location,
            occurred_at=self.now,
        )

        summary = get_analytics_summary(
            self.period_filters(movement_type=StockMovement.MovementType.OUT)
        )

        self.assertEqual(summary["operations_count"], 0)
        self.assertEqual(summary["no_movement_count"], 0)
