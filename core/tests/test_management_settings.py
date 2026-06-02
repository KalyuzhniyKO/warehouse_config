from django.urls import reverse

from ..models import SystemSettings
from .management_test_utils import ManagementTestBase


class ManagementSettingsTests(ManagementTestBase):
    def test_system_settings_get_solo_creates_default_record(self):
        SystemSettings.objects.all().delete()

        settings = SystemSettings.get_solo()

        self.assertIsNotNone(settings.pk)
        self.assertTrue(settings.use_locations)
        self.assertEqual(SystemSettings.objects.count(), 1)

    def test_system_settings_get_solo_reuses_existing_record(self):
        SystemSettings.objects.all().delete()
        first = SystemSettings.get_solo()

        second = SystemSettings.get_solo()

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(SystemSettings.objects.count(), 1)

    def test_system_settings_get_solo_returns_first_by_id(self):
        SystemSettings.objects.all().delete()
        first = SystemSettings.objects.create(use_locations=False)
        SystemSettings.objects.create(use_locations=True)

        settings = SystemSettings.get_solo()

        self.assertEqual(settings.pk, first.pk)
        self.assertFalse(settings.use_locations)

    def test_warehouse_admin_can_open_settings_page(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("management_settings"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Налаштування складу")
        self.assertContains(response, "Використовувати локації")
        self.assertContains(response, "Зберегти")

    def test_auditor_cannot_open_settings_page(self):
        self.client.force_login(self.auditor)

        response = self.client.get(reverse("management_settings"))

        self.assertEqual(response.status_code, 403)

    def test_post_can_disable_and_enable_use_locations(self):
        self.client.force_login(self.admin)

        response = self.client.post(reverse("management_settings"), data={}, follow=True)

        self.assertEqual(response.status_code, 200)
        settings = SystemSettings.get_solo()
        self.assertFalse(settings.use_locations)
        self.assertContains(response, "Налаштування збережено.")

        response = self.client.post(
            reverse("management_settings"), data={"use_locations": "on"}, follow=True
        )

        self.assertEqual(response.status_code, 200)
        settings.refresh_from_db()
        self.assertTrue(settings.use_locations)
        self.assertContains(response, "Налаштування збережено.")

    def test_english_settings_page_uses_english_terms_only(self):
        self.client.force_login(self.admin)

        response = self.client.get("/en/management/settings/")
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn('<html lang="en">', html)
        self.assertIn('<form method="post"', html)
        self.assertContains(response, 'id="id_use_locations"')
        self.assertIn('type="submit" class="btn btn-primary"', html)
