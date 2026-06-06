from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils.html import strip_tags


class ManagementReportsTests(TestCase):
    def setUp(self):
        call_command("init_roles", stdout=StringIO())
        User = get_user_model()
        self.admin = User.objects.create_user("admin-reports", password="pw")
        self.admin.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.storekeeper = User.objects.create_user("keeper-reports", password="pw")
        self.storekeeper.groups.add(Group.objects.get(name="Комірник"))
        self.superuser = User.objects.create_superuser("root-reports", password="pw", email="root@example.com")

    def test_access(self):
        url = reverse("management_reports")
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.storekeeper)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.force_login(self.superuser)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_page_content_and_presets(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse("management_reports"))
        self.assertContains(r, "Готові звіти")
        self.assertContains(r, "Швидкий доступ до типових складських звітів")
        self.assertContains(r, "Операційні звіти")
        self.assertContains(r, "Аналітичні звіти")
        self.assertContains(r, "Контроль якості даних")
        self.assertContains(r, "Експорт")
        self.assertContains(r, "report-preset-card")
        self.assertContains(r, "Видача за 7 днів")
        self.assertContains(r, "Топ товарів за місяць")
        self.assertContains(r, "missing_documents")
        self.assertContains(r, "data_quality")
        self.assertContains(r, "Відкрити")
        self.assertContains(r, "Excel")

    def test_preset_links_work_without_debug_url_display(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse("management_reports"))
        self.assertContains(r, "period=7d")
        self.assertContains(r, "movement_type=out")
        self.assertContains(r, "no_document=1")
        self.assertContains(r, reverse("management_analytics_data_quality"))
        self.assertContains(r, reverse("management_analytics_export_xlsx"))
        self.assertNotContains(r, "<code")

        visible_text = strip_tags(r.content.decode())
        self.assertNotIn("period=7d", visible_text)
        self.assertNotIn("movement_type=out", visible_text)
        self.assertNotIn("no_document=1", visible_text)

    def test_navigation_links(self):
        self.client.force_login(self.admin)
        reports_response = self.client.get(reverse("management_reports"))
        self.assertContains(reports_response, reverse("management_analytics"))
        self.assertContains(reports_response, reverse("management_dashboard"))
        self.assertContains(self.client.get(reverse("management_analytics")), reverse("management_reports"))
        self.assertContains(self.client.get(reverse("management_dashboard")), reverse("management_reports"))

        self.client.force_login(self.storekeeper)
        self.assertNotContains(self.client.get(reverse("dashboard")), reverse("management_reports"))
