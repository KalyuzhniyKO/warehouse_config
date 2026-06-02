from decimal import Decimal

from django.utils import timezone

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
