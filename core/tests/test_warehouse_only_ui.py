from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.utils import translation
from django.urls import reverse

from core.forms import (
    InitialBalanceForm,
    StockIssueForm,
    StockReceiveForm,
    StockReturnForm,
    StockTransferForm,
    StockWriteOffForm,
)
from core.models import (
    Item,
    Location,
    Recipient,
    StockBalance,
    StockMovement,
    SystemSettings,
    Unit,
    UsagePlace,
    Warehouse,
)
from core.services.locations import get_default_location_for_warehouse
from core.services.stock import receive_stock
from core.tests.warehouse_access_utils import grant_warehouse_access


class WarehouseOnlyOperationFormTests(TestCase):
    def setUp(self):
        call_command("init_roles", stdout=StringIO())
        SystemSettings.objects.update_or_create(pk=1, defaults={"use_locations": True})
        User = get_user_model()
        self.user = User.objects.create_user(username="operator", password="pw")
        self.user.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.unit = Unit.objects.create(name="Piece", symbol="pc")
        self.item = Item.objects.create(name="Cable", unit=self.unit)
        self.warehouse = Warehouse.objects.create(name="Shop warehouse")
        self.second_warehouse = Warehouse.objects.create(name="Tech warehouse")
        self.default_location = get_default_location_for_warehouse(self.warehouse)
        self.second_default_location = get_default_location_for_warehouse(
            self.second_warehouse
        )
        self.injected_location = Location.objects.create(
            warehouse=self.second_warehouse, name="Injected location"
        )
        self.recipient = Recipient.objects.create(name="Worker")
        self.department = UsagePlace.objects.create(name="Service")

    def base_data(self, **overrides):
        data = {
            "item": self.item.pk,
            "warehouse": self.warehouse.pk,
            "location": self.injected_location.pk,
            "qty": "1.000",
            "comment": "note",
            "occurred_at": "2026-01-15T10:30",
            "recipient": self.recipient.pk,
            "department": self.department.pk,
            "issue_reason": "other",
            "document_number": "DOC-1",
            "writeoff_reason": "other",
        }
        data.update(overrides)
        return data

    def test_regular_operation_forms_hide_location_fields(self):
        grant_warehouse_access(self.user, [self.warehouse, self.second_warehouse])

        for form_class in [
            StockReceiveForm,
            StockIssueForm,
            StockReturnForm,
            StockWriteOffForm,
            InitialBalanceForm,
        ]:
            form = form_class(user=self.user)
            self.assertNotIn("location", form.fields)

    def test_one_accessible_warehouse_hides_warehouse_and_location(self):
        grant_warehouse_access(self.user, self.warehouse)

        form = StockReceiveForm(user=self.user)

        self.assertNotIn("warehouse", form.fields)
        self.assertNotIn("location", form.fields)

    def test_two_accessible_warehouses_show_only_warehouse_selection(self):
        grant_warehouse_access(self.user, [self.warehouse, self.second_warehouse])

        form = StockReceiveForm(user=self.user)

        self.assertIn("warehouse", form.fields)
        self.assertNotIn("location", form.fields)
        self.assertCountEqual(
            form.fields["warehouse"].queryset, [self.warehouse, self.second_warehouse]
        )

    def test_default_location_is_assigned_automatically_for_stock_operation_forms(self):
        grant_warehouse_access(self.user, [self.warehouse, self.second_warehouse])
        StockMovement.objects.create(
            item=self.item,
            source_warehouse=self.warehouse,
            movement_type=StockMovement.MovementType.OUT,
            qty=Decimal("1.000"),
            recipient=self.recipient,
        )
        form_classes = [
            StockReceiveForm,
            StockIssueForm,
            StockReturnForm,
            StockWriteOffForm,
            InitialBalanceForm,
        ]

        for form_class in form_classes:
            form = form_class(data=self.base_data(), user=self.user)
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(form.cleaned_data["location"], self.default_location)

    def test_single_warehouse_default_location_is_assigned_automatically(self):
        grant_warehouse_access(self.user, self.warehouse)

        form = StockReceiveForm(
            data=self.base_data(warehouse=self.second_warehouse.pk), user=self.user
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["warehouse"], self.warehouse)
        self.assertEqual(form.cleaned_data["location"], self.default_location)

    def test_transfer_hides_locations_and_assigns_default_locations(self):
        grant_warehouse_access(self.user, [self.warehouse, self.second_warehouse])
        receive_stock(
            item=self.item, location=self.default_location, qty=Decimal("5.000")
        )

        form = StockTransferForm(
            data={
                "item": self.item.pk,
                "source_warehouse": self.warehouse.pk,
                "source_location": self.injected_location.pk,
                "destination_warehouse": self.second_warehouse.pk,
                "destination_location": self.injected_location.pk,
                "qty": "1.000",
                "comment": "move",
                "occurred_at": "2026-01-15T10:30",
            },
            user=self.user,
        )

        self.assertNotIn("source_location", form.fields)
        self.assertNotIn("destination_location", form.fields)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["source_location"], self.default_location)
        self.assertEqual(
            form.cleaned_data["destination_location"], self.second_default_location
        )

    def test_post_cannot_inject_inaccessible_location(self):
        grant_warehouse_access(self.user, self.warehouse)

        form = StockReceiveForm(data=self.base_data(), user=self.user)

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["warehouse"], self.warehouse)
        self.assertEqual(form.cleaned_data["location"], self.default_location)


class CompactDashboardAndNavbarTests(TestCase):
    def setUp(self):
        call_command("init_roles", stdout=StringIO())
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin", password="pw", first_name="Admin", last_name="User"
        )
        self.admin.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.superuser = User.objects.create_superuser(
            username="owner",
            password="pw",
            first_name="Very Long Owner",
            last_name="Full Name For Navbar",
        )
        self.warehouse = Warehouse.objects.create(name="Shop warehouse")
        grant_warehouse_access(self.admin, self.warehouse)

    def test_dashboard_main_content_excludes_rare_functions(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard"))
        html = response.content.decode()
        main = html.split('<div class="dashboard-main">', 1)[1].split("</main>", 1)[0]

        for label in [
            "Локації",
            "Категорії",
            "Одиниці виміру",
            "Початкові залишки",
            "Друк етикеток",
            "Допомога",
        ]:
            self.assertNotIn(label, main)

    def user_menu_html(self, response):
        html = response.content.decode()
        start = html.index('<div class="dropdown-menu dropdown-menu-end shadow user-menu-dropdown">')
        return html[start:html.index("</form>", start)]

    def test_admin_dropdown_excludes_warehouse_work_actions(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard"))
        dropdown_html = self.user_menu_html(response)

        self.assertIn("Керування складом", dropdown_html)
        self.assertIn(f'href="{reverse("management_dashboard")}"', dropdown_html)
        for label in [
            "Склади",
            "Локації",
            "Працівники / отримувачі",
            "Категорії",
            "Одиниці виміру",
            "Початкові залишки",
            "Друк етикеток",
            "Принтери",
            "Шаблони етикеток",
            "Допомога",
        ]:
            self.assertNotIn(label, dropdown_html)
        self.assertIn("Користувачі та ролі", dropdown_html)
        self.assertIn("Вийти", dropdown_html)

    def test_superuser_dropdown_contains_audit_log(self):
        self.client.force_login(self.superuser)
        html = self.client.get(reverse("dashboard")).content.decode()

        self.assertIn("Журнал аудиту", html)
        self.assertIn("Власник", html)
        self.assertNotIn(">root<", html.lower())

    def test_admin_dropdown_does_not_contain_audit_log(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse("dashboard")).content.decode()

        self.assertNotIn("Журнал аудиту", html)
        self.assertIn("Адміністратор", html)

    def test_navbar_role_badge_renders_business_labels_by_locale(self):
        expectations = {
            "uk": (self.superuser, "Власник"),
            "ru": (self.superuser, "Владелец"),
            "en": (self.superuser, "Owner"),
        }

        for language_code, (user, label) in expectations.items():
            with self.subTest(language_code=language_code), translation.override(language_code):
                self.client.force_login(user)
                html = self.client.get(reverse("dashboard")).content.decode()

            self.assertIn(f'<span class="user-role-badge">{label}</span>', html)
            self.assertNotIn(">root<", html.lower())

    def test_warehouse_user_navbar_uses_business_label(self):
        user = get_user_model().objects.create_user(username="keeper", password="pw")
        user.groups.add(Group.objects.get(name="Комірник"))
        grant_warehouse_access(user, self.warehouse)

        self.client.force_login(user)
        html = self.client.get(reverse("dashboard")).content.decode()

        self.assertIn('<span class="user-role-badge">Користувач</span>', html)
        self.assertNotIn("Комірник", html)

    def test_navbar_name_width_is_not_too_aggressive(self):
        css = open("static/core/css/app.css", encoding="utf-8").read()
        base = open("templates/base.html", encoding="utf-8").read()

        self.assertIn("max-width: 300px", base)
        self.assertIn("user-role-badge", base)
        self.assertIn("max-width: 140px", css)
