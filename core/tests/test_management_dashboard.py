from django.urls import reverse

from .management_test_utils import ManagementTestBase


class ManagementDashboardTests(ManagementTestBase):
    def test_management_requires_login(self):
        response = self.client.get(reverse("management_dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_warehouse_admin_menu_shows_management(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Керування")
        self.assertNotContains(response, "Адмін-панель")

    def test_warehouse_admin_opens_management_pages(self):
        self.client.force_login(self.admin)
        for url_name in ["management_dashboard", "management_help", "management_analytics"]:
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 200, url_name)

    def test_warehouse_admin_sees_structured_management_dashboard(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("management_dashboard"))
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Навігація", html)
        self.assertNotIn('class="sidebar-link"', html)
        self.assertIn('<main class="col-12">', html)
        self.assertIn("mgmt-grid", html)
        self.assertIn("mgmt-card", html)
        self.assertIn("mgmt-link", html)
        for text in [
            "Керування складом",
            "Операції складу",
            "Залишки та контроль",
            "Номенклатура",
            "Довідники підприємства",
            "Етикетки та друк",
            "Адміністрування",
            "Видача товару",
            "Повернення товару",
            "Прихід товару",
            "Залишки на складі",
            "Журнал операцій",
        ]:
            self.assertContains(response, text)

    def test_management_dashboard_does_not_duplicate_key_links(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("management_dashboard"))
        html = response.content.decode()
        dashboard_html = html[html.index('<main class="col-12">'):]
        self.assertLessEqual(dashboard_html.count(reverse("printer_list")), 1)
        self.assertLessEqual(dashboard_html.count(reverse("labeltemplate_list")), 1)
        self.assertLessEqual(dashboard_html.count(reverse("recipient_list")), 1)

    def test_auditor_cannot_open_management_dashboard(self):
        self.client.force_login(self.auditor)
        response = self.client.get(reverse("management_dashboard"))

        self.assertEqual(response.status_code, 403)
        self.assertNotContains(
            response, "Керування складом", status_code=403
        )

    def test_superuser_sees_system_management_cards(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("management_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Адміністрування")
        self.assertContains(response, "Налаштування складу")
        self.assertContains(response, "Користувачі та ролі")

    def test_superuser_sees_technical_django_admin_card(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("management_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Django admin")
