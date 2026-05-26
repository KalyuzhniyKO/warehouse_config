from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from core.models import Recipient
from core.services.filter_memory import get_filter_memory_key


class FilterMemoryTests(TestCase):
    def setUp(self):
        call_command("init_roles", stdout=StringIO())
        self.admin1 = get_user_model().objects.create_user("admin1", password="pw")
        self.admin1.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.admin2 = get_user_model().objects.create_user("admin2", password="pw")
        self.admin2.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.recipient = Recipient.objects.create(name="R1")

    def test_analytics_remembers_filters(self):
        self.client.force_login(self.admin1)
        url = reverse("management_analytics")
        self.client.get(url, {"period": "7d", "movement_type": "out"})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("period=7d", response.url)
        self.assertIn("movement_type=out", response.url)

    def test_analytics_reset(self):
        self.client.force_login(self.admin1)
        url = reverse("management_analytics")
        self.client.get(url, {"period": "7d", "movement_type": "out"})
        self.client.get(url, {"reset_filters": "1"})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("period=7d", response.request["QUERY_STRING"])

    def test_journal_remembers_filters(self):
        self.client.force_login(self.admin1)
        url = reverse("movement_list")
        self.client.get(url, {"no_document": "1", "movement_type": "out"})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("no_document=1", response.url)
        self.assertIn("movement_type=out", response.url)

    def test_get_has_priority(self):
        self.client.force_login(self.admin1)
        url = reverse("movement_list")
        self.client.get(url, {"no_document": "1"})
        response = self.client.get(url, {"recipient_id": str(self.recipient.pk)})
        self.assertEqual(response.status_code, 200)
        key = get_filter_memory_key(response.wsgi_request, "movement_list")
        remembered = self.client.session[key]
        self.assertEqual(remembered.get("recipient_id"), str(self.recipient.pk))
        self.assertNotIn("no_document", remembered)

    def test_whitelist_excludes_bad_params(self):
        self.client.force_login(self.admin1)
        url = reverse("movement_list")
        response = self.client.get(url, {"bad_param": "123", "page": "5", "movement_type": "out"})
        key = get_filter_memory_key(response.wsgi_request, "movement_list")
        remembered = self.client.session[key]
        self.assertIn("movement_type", remembered)
        self.assertNotIn("bad_param", remembered)
        self.assertNotIn("page", remembered)

    def test_user_isolation(self):
        self.client.force_login(self.admin1)
        journal = reverse("movement_list")
        self.client.get(journal, {"movement_type": "out"})
        self.client.logout()
        self.client.force_login(self.admin2)
        response = self.client.get(journal)
        self.assertEqual(response.status_code, 200)

    def test_reset_ui_present(self):
        self.client.force_login(self.admin1)
        response = self.client.get(reverse("movement_list"))
        self.assertContains(response, "reset_filters=1")

    def test_data_quality_remembers_filters(self):
        self.client.force_login(self.admin1)
        url = reverse("management_analytics_data_quality")
        self.client.get(url, {"period": "30d", "movement_type": "out"})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("period=30d", response.url)
        self.assertIn("movement_type=out", response.url)

    def test_remembered_filters_redirect_happens_only_once(self):
        self.client.force_login(self.admin1)
        url = reverse("management_analytics")
        self.client.get(url, {"period": "7d", "movement_type": "out"})

        first = self.client.get(url)
        self.assertEqual(first.status_code, 302)
        self.assertIn("period=7d", first.url)

        second = self.client.get(first.url)
        self.assertEqual(second.status_code, 200)
