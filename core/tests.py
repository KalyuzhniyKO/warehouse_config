from django.test import SimpleTestCase
from django.urls import reverse


class DashboardTests(SimpleTestCase):
    def test_dashboard_url_resolves(self):
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Warehouse dashboard")
