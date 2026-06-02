from django.urls import reverse

from .analytics_test_utils import (
    AnalyticsInterfaceTestBase,
    WarehouseAnalyticsAuditTestBase,
)


class AnalyticsInterfaceTests(AnalyticsInterfaceTestBase):
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

    def test_export_csv_works(self):
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("management_analytics_export_csv"), {"warehouse": self.warehouse.pk}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertContains(response, "Кабель ВВГ")


class WarehouseAnalyticsInterfaceTests(WarehouseAnalyticsAuditTestBase):
    def test_analytics_page_renders_non_zero_values_when_data_exists(self):
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("management_analytics"), {"reset_filters": "1"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "AUD-IN")
        self.assertContains(response, "Audit Cable")
        self.assertContains(response, 'analytics-visual-value">5', html=False)
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
