from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from core.admin import make_active, make_inactive
from core.models import UsagePlace


class BaseTemplateReturnLinksTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name="Комірник")
        cls.user = get_user_model().objects.create_user(username="storekeeper", password="pw")
        cls.user.groups.add(Group.objects.get(name="Комірник"))

    def test_storekeeper_menu_has_stock_return_link_for_return_action(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, f'href="{reverse("stock_return")}"')
        self.assertContains(response, "Повернути товар")
        self.assertNotContains(response, f'href="{reverse("stock_receive")}">Повернути товар')


class AdminCustomizationTests(TestCase):
    def test_admin_site_titles_are_configured(self):
        self.assertEqual(admin.site.site_header, "YANTOS Warehouse Admin")
        self.assertEqual(admin.site.site_title, "YANTOS Warehouse")
        self.assertEqual(admin.site.index_title, "Панель керування складом")

    def test_make_active_and_make_inactive_actions_toggle_usage_place(self):
        usage_place = UsagePlace.objects.create(name="Склад", is_active=False)
        queryset = UsagePlace.objects.filter(pk=usage_place.pk)

        make_active(None, None, queryset)
        usage_place.refresh_from_db()
        self.assertTrue(usage_place.is_active)

        make_inactive(None, None, queryset)
        usage_place.refresh_from_db()
        self.assertFalse(usage_place.is_active)

    def test_usage_place_admin_changelist_shows_actions(self):
        superuser = get_user_model().objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="pw",
        )
        self.client.force_login(superuser)

        response = self.client.get(reverse("admin:core_usageplace_changelist"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Активувати вибрані записи")
        self.assertContains(response, "Архівувати вибрані записи")
