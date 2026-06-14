from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase
from django.urls import reverse

from core.admin import (
    LabelTemplateAdmin,
    PrintJobAdmin,
    PrinterAdmin,
    StockMovementAdmin,
    UsagePlaceAdmin,
    make_active,
    make_inactive,
)
from core.models import LabelTemplate, PrintJob, Printer, StockMovement, UsagePlace, Warehouse
from core.tests.warehouse_access_utils import grant_warehouse_access


class BaseTemplateReturnLinksTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name="Комірник")
        cls.user = get_user_model().objects.create_user(username="storekeeper", password="pw")
        cls.user.groups.add(Group.objects.get(name="Комірник"))
        cls.warehouse = Warehouse.objects.create(name="Storekeeper warehouse")
        grant_warehouse_access(cls.user, cls.warehouse)

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
        self.assertEqual(admin.site.index_title, "Панель адміністрування")

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


class AdminIndexPolishTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.superuser = get_user_model().objects.create_superuser("admin", "admin@example.com", "pw")
        cls.user = get_user_model().objects.create_user("user", password="pw")

    def test_admin_index_only_superuser_access(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 302)

    def test_admin_index_contains_quick_link_and_sections(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("admin:index"))
        self.assertContains(response, "Панель керування")
        self.assertContains(response, "Довідники")
        self.assertContains(response, "Довідники")
        self.assertContains(response, "Друк")
        self.assertContains(response, "Система")

    def test_only_light_admin_css_is_loaded(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("admin:index"))
        self.assertContains(response, "core/css/admin-light.css")
        self.assertNotContains(response, "admin/css/custom_admin.css")
        self.assertNotContains(response, 'class="theme-toggle"')

    def test_admin_user_change_page_has_light_css_and_selector_widgets(self):
        self.client.force_login(self.superuser)

        response = self.client.get(
            reverse("admin:auth_user_change", args=[self.superuser.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "core/css/admin-light.css")
        self.assertNotContains(response, "admin/css/custom_admin.css")
        self.assertNotContains(response, 'class="theme-toggle"')
        self.assertContains(response, 'class="selectfilter"')
        self.assertContains(response, 'id="id_groups"')
        self.assertContains(response, 'id="id_user_permissions"')

    def test_standard_admin_content_still_renders(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("admin:index"))
        self.assertContains(response, 'id="content-main"')
        self.assertContains(response, "data-admin-landing")
        self.assertContains(response, admin.site.site_header)

    def test_admin_index_keeps_sidebar_without_duplicating_app_list(self):
        self.client.force_login(self.superuser)

        response = self.client.get(reverse("admin:index"))
        item_changelist_url = reverse("admin:core_item_changelist")
        central_content = response.content.decode().split(
            '<div id="content-main" data-admin-landing>', 1
        )[1]

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="nav-sidebar"')
        self.assertContains(response, f'href="{item_changelist_url}"', count=1)
        self.assertNotIn('class="app-core module"', central_content)
        self.assertNotIn('class="app-auth module"', central_content)

    def test_normal_warehouse_page_does_not_load_admin_light_css(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "core/css/admin-light.css")

    def test_admin_index_anonymous_redirected(self):
        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 302)

    def test_superuser_can_open_key_changelists(self):
        self.client.force_login(self.superuser)
        for name in [
            "admin:core_item_changelist",
            "admin:core_stockmovement_changelist",
            "admin:core_usageplace_changelist",
            "admin:core_printer_changelist",
            "admin:core_labeltemplate_changelist",
        ]:
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_admin_index_has_new_group_labels_and_quick_links(self):
        self.client.force_login(self.superuser)
        response = self.client.get(reverse("admin:index"))
        self.assertContains(response, "Відкрити систему складу")
        self.assertContains(response, "Панель керування")
        self.assertContains(response, "Журнал операцій")
        self.assertContains(response, "Склад")
        self.assertContains(response, "Довідники")
        self.assertContains(response, "Друк")
        self.assertContains(response, "Система")


class AdminBadgeHelpersTests(TestCase):
    def setUp(self):
        self.site = admin.site
        self.factory = RequestFactory()

    def test_printjob_status_badge_html(self):
        ma = PrintJobAdmin(PrintJob, self.site)
        printed = ma.status_badge(type("Obj", (), {"status": "printed"})())
        failed = ma.status_badge(type("Obj", (), {"status": "failed"})())
        pending = ma.status_badge(type("Obj", (), {"status": "pending"})())

        self.assertIn('status-badge--printed', printed)
        self.assertIn('status-badge--failed', failed)
        self.assertIn('status-badge--pending', pending)

    def test_usage_place_active_badge_labels(self):
        ma = UsagePlaceAdmin(UsagePlace, self.site)
        active_html = ma.active_badge(type("Obj", (), {"is_active": True})())
        archive_html = ma.active_badge(type("Obj", (), {"is_active": False})())

        self.assertIn("Активний", active_html)
        self.assertIn("Архів", archive_html)


class AdminModelConfigurationTests(TestCase):
    def test_usage_place_and_printer_actions_configured(self):
        self.assertIn(make_active, UsagePlaceAdmin.actions)
        self.assertIn(make_inactive, UsagePlaceAdmin.actions)
        self.assertIn(make_active, PrinterAdmin.actions)
        self.assertIn(make_inactive, PrinterAdmin.actions)

    def test_stockmovement_search_and_filters_configured(self):
        self.assertIn("movement_type", StockMovementAdmin.list_filter)
        self.assertIn("occurred_at", StockMovementAdmin.list_filter)
        self.assertIn("item__name", StockMovementAdmin.search_fields)
        self.assertIn("item__barcode__barcode", StockMovementAdmin.search_fields)

    def test_label_template_fieldsets_include_layout(self):
        fieldset_titles = [name for name, _ in LabelTemplateAdmin.fieldsets]
        self.assertIn("Макет", fieldset_titles)
