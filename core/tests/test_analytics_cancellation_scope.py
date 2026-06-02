from decimal import Decimal

from .analytics_test_utils import WarehouseAnalyticsAuditTestBase


class WarehouseAnalyticsCancellationScopeTests(WarehouseAnalyticsAuditTestBase):
    def test_cancelled_and_reversal_movements_are_excluded_from_kpi_totals(self):
        summary = self.summary_for_user(self.superuser, warehouse=self.warehouse)
        self.assertEqual(summary["receive_qty"], Decimal("31.000"))
        self.assertEqual(summary["issue_qty"], Decimal("5.000"))
        self.assertEqual(summary["operations_count"], 6)
