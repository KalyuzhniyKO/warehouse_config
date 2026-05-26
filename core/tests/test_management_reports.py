from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse


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
        self.assertContains(r, "Звіти складу")
        self.assertContains(r, "report-preset-card")
        self.assertContains(r, "missing_documents")
        self.assertContains(r, "data_quality")

    def test_preset_urls(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse("management_reports"))
        self.assertContains(r, "period=7d")
        self.assertContains(r, "movement_type=out")
        self.assertContains(r, "no_document=1")
        self.assertContains(r, reverse("management_analytics_data_quality"))
        self.assertContains(r, reverse("management_analytics_export_xlsx"))

    def test_navigation_links(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("management_analytics")), reverse("management_reports"))
        self.assertContains(self.client.get(reverse("management_dashboard")), reverse("management_reports"))

        self.client.force_login(self.storekeeper)
        self.assertNotContains(self.client.get(reverse("dashboard")), reverse("management_reports"))
