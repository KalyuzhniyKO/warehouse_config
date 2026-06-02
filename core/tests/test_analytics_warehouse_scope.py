from decimal import Decimal

from django.urls import reverse

from .analytics_test_utils import WarehouseAnalyticsAuditTestBase


class WarehouseAnalyticsAuditTests(WarehouseAnalyticsAuditTestBase):
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
