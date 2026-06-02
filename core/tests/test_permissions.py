from decimal import Decimal
from pathlib import Path
from unittest import mock
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone
from io import BytesIO, StringIO
from django.urls import reverse
from ..forms import CategoryForm, ItemForm, LocationForm, StockBalanceFilterForm, StockTransferForm
from .warehouse_access_utils import grant_warehouse_access
from ..permissions import (
    ANALYTICS_GROUPS,
    DIRECTORY_EDIT_GROUPS,
    PRINT_GROUPS,
    SETTINGS_GROUPS,
    STOREKEEPER_GROUP,
    USER_MANAGEMENT_GROUPS,
    WAREHOUSE_ADMIN_GROUP,
    can_assign_warehouse_access,
    can_cancel_movement,
    can_manage_directories,
    can_manage_settings,
    can_manage_users,
    can_print_labels,
    can_view_analytics,
    can_view_audit,
    can_view_warehouse_data,
)
from ..models import (
    BarcodeRegistry,
    BarcodeSequence,
    Category,
    InventoryCount,
    InventoryCountLine,
    Item,
    LabelTemplate,
    Location,
    PrintJob,
    Printer,
    Recipient,
    StockBalance,
    StockMovement,
    Unit,
    Warehouse,
)


class PermissionHelperTests(TestCase):
    def setUp(self):
        call_command("init_roles", stdout=StringIO())
        user_model = get_user_model()
        self.superuser = user_model.objects.create_superuser(
            username="root", password="pw", email="root@example.com"
        )
        self.admin = user_model.objects.create_user(username="admin", password="pw")
        self.admin.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.storekeeper = user_model.objects.create_user(username="keeper", password="pw")
        self.storekeeper.groups.add(Group.objects.get(name="Комірник"))
        self.auditor = user_model.objects.create_user(username="auditor", password="pw")
        self.auditor.groups.add(Group.objects.get(name="Перегляд / аудитор"))
        self.plain_user = user_model.objects.create_user(username="plain", password="pw")
        self.warehouse = Warehouse.objects.create(name="Основний склад")
        self.other_warehouse = Warehouse.objects.create(name="Резервний склад")
        grant_warehouse_access(self.admin, self.warehouse, can_delegate=True)
        grant_warehouse_access(self.storekeeper, self.warehouse)
        grant_warehouse_access(self.auditor, self.warehouse)

    def helper_results(self, user):
        return {
            "manage_users": can_manage_users(user),
            "view_audit": can_view_audit(user),
            "cancel_movement": can_cancel_movement(user),
            "assign_warehouse_access": can_assign_warehouse_access(user),
            "view_warehouse_data": can_view_warehouse_data(user),
            "view_analytics": can_view_analytics(user),
            "manage_directories": can_manage_directories(user),
            "print_labels": can_print_labels(user),
            "manage_settings": can_manage_settings(user),
        }

    def test_anonymous_user_returns_false_for_all_helpers(self):
        self.assertEqual(
            self.helper_results(AnonymousUser()),
            {
                "manage_users": False,
                "view_audit": False,
                "cancel_movement": False,
                "assign_warehouse_access": False,
                "view_warehouse_data": False,
                "view_analytics": False,
                "manage_directories": False,
                "print_labels": False,
                "manage_settings": False,
            },
        )

    def test_superuser_behavior(self):
        self.assertEqual(
            self.helper_results(self.superuser),
            {
                "manage_users": True,
                "view_audit": True,
                "cancel_movement": True,
                "assign_warehouse_access": True,
                "view_warehouse_data": True,
                "view_analytics": True,
                "manage_directories": True,
                "print_labels": True,
                "manage_settings": True,
            },
        )
        self.assertTrue(can_assign_warehouse_access(self.superuser, self.warehouse))
        self.assertTrue(can_view_warehouse_data(self.superuser, self.warehouse))

    def test_warehouse_admin_behavior(self):
        self.assertEqual(
            self.helper_results(self.admin),
            {
                "manage_users": True,
                "view_audit": False,
                "cancel_movement": False,
                "assign_warehouse_access": True,
                "view_warehouse_data": True,
                "view_analytics": True,
                "manage_directories": True,
                "print_labels": True,
                "manage_settings": True,
            },
        )
        self.assertTrue(can_assign_warehouse_access(self.admin, self.warehouse))
        self.assertFalse(can_assign_warehouse_access(self.admin, self.other_warehouse))

    def test_storekeeper_behavior(self):
        self.assertEqual(
            self.helper_results(self.storekeeper),
            {
                "manage_users": False,
                "view_audit": False,
                "cancel_movement": False,
                "assign_warehouse_access": False,
                "view_warehouse_data": True,
                "view_analytics": False,
                "manage_directories": False,
                "print_labels": True,
                "manage_settings": False,
            },
        )

    def test_user_without_groups_behavior(self):
        self.assertEqual(
            self.helper_results(self.plain_user),
            {
                "manage_users": False,
                "view_audit": False,
                "cancel_movement": False,
                "assign_warehouse_access": False,
                "view_warehouse_data": False,
                "view_analytics": False,
                "manage_directories": False,
                "print_labels": False,
                "manage_settings": False,
            },
        )

    def test_anonymous_user_cannot_view_audit(self):
        self.assertFalse(can_view_audit(AnonymousUser()))

    def test_regular_user_cannot_view_audit(self):
        self.assertFalse(can_view_audit(self.plain_user))

    def test_warehouse_admin_cannot_view_audit(self):
        self.assertFalse(can_view_audit(self.admin))

    def test_storekeeper_cannot_view_audit(self):
        self.assertFalse(can_view_audit(self.storekeeper))

    def test_superuser_can_view_audit(self):
        self.assertTrue(can_view_audit(self.superuser))

    def test_anonymous_user_cannot_cancel_movement(self):
        self.assertFalse(can_cancel_movement(AnonymousUser()))

    def test_regular_user_cannot_cancel_movement(self):
        self.assertFalse(can_cancel_movement(self.plain_user))

    def test_warehouse_admin_cannot_cancel_movement(self):
        self.assertFalse(can_cancel_movement(self.admin))

    def test_storekeeper_cannot_cancel_movement(self):
        self.assertFalse(can_cancel_movement(self.storekeeper))

    def test_superuser_can_cancel_movement(self):
        self.assertTrue(can_cancel_movement(self.superuser))

    def test_can_cancel_movement_accepts_none_movement(self):
        self.assertTrue(can_cancel_movement(self.superuser, movement=None))
        self.assertFalse(can_cancel_movement(self.plain_user, movement=None))

    def test_can_cancel_movement_ignores_movement_object(self):
        movement = object()

        self.assertTrue(can_cancel_movement(self.superuser, movement=movement))
        self.assertFalse(can_cancel_movement(self.plain_user, movement=movement))

    def test_anonymous_user_cannot_manage_directories(self):
        self.assertFalse(can_manage_directories(AnonymousUser()))

    def test_regular_user_cannot_manage_directories(self):
        self.assertFalse(can_manage_directories(self.plain_user))

    def test_superuser_can_manage_directories(self):
        self.assertTrue(can_manage_directories(self.superuser))

    def test_warehouse_admin_can_manage_directories_if_directory_edit_allows_it(self):
        self.assertEqual(
            can_manage_directories(self.admin),
            WAREHOUSE_ADMIN_GROUP in DIRECTORY_EDIT_GROUPS,
        )

    def test_storekeeper_can_manage_directories_if_directory_edit_allows_it(self):
        self.assertEqual(
            can_manage_directories(self.storekeeper),
            STOREKEEPER_GROUP in DIRECTORY_EDIT_GROUPS,
        )

    def test_user_with_no_groups_cannot_manage_directories(self):
        user = get_user_model().objects.create_user(
            username="directory-nogroups", password="pw"
        )

        self.assertFalse(can_manage_directories(user))

    def test_user_in_existing_directory_edit_group_can_manage_directories(self):
        user_model = get_user_model()
        for index, group_name in enumerate(sorted(DIRECTORY_EDIT_GROUPS)):
            with self.subTest(group_name=group_name):
                user = user_model.objects.create_user(
                    username=f"directory-edit-{index}", password="pw"
                )
                user.groups.add(Group.objects.get(name=group_name))

                self.assertTrue(can_manage_directories(user))

    def test_anonymous_user_cannot_print_labels(self):
        self.assertFalse(can_print_labels(AnonymousUser()))

    def test_regular_user_cannot_print_labels(self):
        self.assertFalse(can_print_labels(self.plain_user))

    def test_superuser_can_print_labels(self):
        self.assertTrue(can_print_labels(self.superuser))

    def test_warehouse_admin_can_print_labels_if_print_groups_allow_it(self):
        self.assertEqual(
            can_print_labels(self.admin),
            WAREHOUSE_ADMIN_GROUP in PRINT_GROUPS,
        )

    def test_storekeeper_can_print_labels_if_print_groups_allow_it(self):
        self.assertEqual(
            can_print_labels(self.storekeeper),
            STOREKEEPER_GROUP in PRINT_GROUPS,
        )

    def test_user_with_no_groups_cannot_print_labels(self):
        user = get_user_model().objects.create_user(
            username="print-labels-nogroups", password="pw"
        )

        self.assertFalse(can_print_labels(user))

    def test_user_in_existing_print_group_can_print_labels(self):
        user_model = get_user_model()
        for index, group_name in enumerate(sorted(PRINT_GROUPS)):
            with self.subTest(group_name=group_name):
                user = user_model.objects.create_user(
                    username=f"print-labels-{index}", password="pw"
                )
                user.groups.add(Group.objects.get(name=group_name))

                self.assertTrue(can_print_labels(user))

    def test_anonymous_user_cannot_manage_settings(self):
        self.assertFalse(can_manage_settings(AnonymousUser()))

    def test_regular_user_cannot_manage_settings(self):
        self.assertFalse(can_manage_settings(self.plain_user))

    def test_superuser_can_manage_settings(self):
        self.assertTrue(can_manage_settings(self.superuser))

    def test_warehouse_admin_can_manage_settings_if_settings_groups_allow_it(self):
        self.assertEqual(
            can_manage_settings(self.admin),
            WAREHOUSE_ADMIN_GROUP in SETTINGS_GROUPS,
        )

    def test_storekeeper_can_manage_settings_if_settings_groups_allow_it(self):
        self.assertEqual(
            can_manage_settings(self.storekeeper),
            STOREKEEPER_GROUP in SETTINGS_GROUPS,
        )

    def test_user_with_no_groups_cannot_manage_settings(self):
        user = get_user_model().objects.create_user(
            username="settings-nogroups", password="pw"
        )

        self.assertFalse(can_manage_settings(user))

    def test_user_in_existing_settings_group_can_manage_settings(self):
        user_model = get_user_model()
        for index, group_name in enumerate(sorted(SETTINGS_GROUPS)):
            with self.subTest(group_name=group_name):
                user = user_model.objects.create_user(
                    username=f"settings-{index}", password="pw"
                )
                user.groups.add(Group.objects.get(name=group_name))

                self.assertTrue(can_manage_settings(user))

    def test_anonymous_user_cannot_view_analytics(self):
        self.assertFalse(can_view_analytics(AnonymousUser()))

    def test_regular_user_cannot_view_analytics(self):
        self.assertFalse(can_view_analytics(self.plain_user))

    def test_superuser_can_view_analytics(self):
        self.assertTrue(can_view_analytics(self.superuser))

    def test_warehouse_admin_can_view_analytics_if_analytics_allows_it(self):
        self.assertEqual(
            can_view_analytics(self.admin),
            WAREHOUSE_ADMIN_GROUP in ANALYTICS_GROUPS,
        )

    def test_storekeeper_can_view_analytics_if_analytics_allows_it(self):
        self.assertEqual(
            can_view_analytics(self.storekeeper),
            STOREKEEPER_GROUP in ANALYTICS_GROUPS,
        )

    def test_user_with_no_groups_cannot_view_analytics(self):
        user = get_user_model().objects.create_user(
            username="analytics-nogroups", password="pw"
        )

        self.assertFalse(can_view_analytics(user))

    def test_user_in_existing_analytics_group_can_view_analytics(self):
        user_model = get_user_model()
        for index, group_name in enumerate(sorted(ANALYTICS_GROUPS)):
            with self.subTest(group_name=group_name):
                user = user_model.objects.create_user(
                    username=f"analytics-{index}", password="pw"
                )
                user.groups.add(Group.objects.get(name=group_name))

                self.assertTrue(can_view_analytics(user))

    def test_anonymous_user_cannot_manage_users(self):
        self.assertFalse(can_manage_users(AnonymousUser()))

    def test_regular_user_cannot_manage_users(self):
        self.assertFalse(can_manage_users(self.plain_user))

    def test_superuser_can_manage_users(self):
        self.assertTrue(can_manage_users(self.superuser))

    def test_warehouse_admin_can_manage_users_if_user_management_allows_it(self):
        if WAREHOUSE_ADMIN_GROUP in USER_MANAGEMENT_GROUPS:
            self.assertTrue(can_manage_users(self.admin))
        else:
            self.assertFalse(can_manage_users(self.admin))

    def test_storekeeper_cannot_manage_users_if_user_management_denies_it(self):
        if STOREKEEPER_GROUP in USER_MANAGEMENT_GROUPS:
            self.assertTrue(can_manage_users(self.storekeeper))
        else:
            self.assertFalse(can_manage_users(self.storekeeper))

    def test_user_with_no_groups_cannot_manage_users(self):
        user = get_user_model().objects.create_user(username="nogroups", password="pw")

        self.assertFalse(can_manage_users(user))

    def test_user_in_existing_user_management_group_can_manage_users(self):
        user_model = get_user_model()
        for group_name in USER_MANAGEMENT_GROUPS:
            with self.subTest(group_name=group_name):
                user = user_model.objects.create_user(
                    username=f"user-management-{group_name}", password="pw"
                )
                user.groups.add(Group.objects.get(name=group_name))

                self.assertTrue(can_manage_users(user))

    def test_anonymous_user_cannot_assign_warehouse_access(self):
        self.assertFalse(can_assign_warehouse_access(AnonymousUser(), self.warehouse))

    def test_regular_user_without_delegation_cannot_assign_warehouse_access(self):
        self.assertFalse(can_assign_warehouse_access(self.storekeeper, self.warehouse))

    def test_superuser_can_assign_warehouse_access(self):
        self.assertTrue(can_assign_warehouse_access(self.superuser, self.warehouse))

    def test_warehouse_admin_with_delegation_can_assign_access_for_that_warehouse(self):
        self.assertTrue(can_assign_warehouse_access(self.admin, self.warehouse))

    def test_warehouse_admin_without_delegation_cannot_assign_access_for_other_warehouse(self):
        self.assertFalse(can_assign_warehouse_access(self.admin, self.other_warehouse))

    def test_can_assign_warehouse_access_without_warehouse_requires_delegatable_warehouse(self):
        self.assertTrue(can_assign_warehouse_access(self.admin))
        self.assertFalse(can_assign_warehouse_access(self.storekeeper))

    def test_can_assign_warehouse_access_without_warehouse_returns_false_without_delegatable_warehouses(self):
        self.assertFalse(can_assign_warehouse_access(self.plain_user))

    def test_anonymous_user_cannot_view_warehouse_data(self):
        self.assertFalse(can_view_warehouse_data(AnonymousUser(), self.warehouse))

    def test_regular_user_without_warehouse_access_cannot_view_warehouse_data(self):
        self.assertFalse(can_view_warehouse_data(self.plain_user, self.warehouse))

    def test_superuser_can_view_warehouse_data(self):
        self.assertTrue(can_view_warehouse_data(self.superuser, self.warehouse))

    def test_user_with_access_can_view_that_warehouse_data(self):
        self.assertTrue(can_view_warehouse_data(self.storekeeper, self.warehouse))

    def test_user_without_access_cannot_view_other_warehouse_data(self):
        self.assertFalse(can_view_warehouse_data(self.storekeeper, self.other_warehouse))

    def test_can_view_warehouse_data_without_warehouse_requires_accessible_warehouse(self):
        self.assertTrue(can_view_warehouse_data(self.storekeeper))
        self.assertFalse(can_view_warehouse_data(self.plain_user))

    def test_can_view_warehouse_data_without_warehouse_returns_false_without_accessible_warehouses(self):
        no_access_user = get_user_model().objects.create_user(
            username="warehouse-data-nogroups", password="pw"
        )

        self.assertFalse(can_view_warehouse_data(no_access_user))

    def test_can_view_warehouse_data_respects_user_warehouse_access(self):
        self.assertTrue(can_view_warehouse_data(self.admin, self.warehouse))
        self.assertTrue(can_view_warehouse_data(self.storekeeper, self.warehouse))
        self.assertTrue(can_view_warehouse_data(self.auditor, self.warehouse))
        self.assertFalse(can_view_warehouse_data(self.admin, self.other_warehouse))
        self.assertFalse(can_view_warehouse_data(self.storekeeper, self.other_warehouse))
        self.assertFalse(can_view_warehouse_data(self.plain_user, self.warehouse))


class ManagementPermissionTests(TestCase):

    def setUp(self):
        call_command("init_roles", stdout=StringIO())
        self.admin = get_user_model().objects.create_user(
            username="admin", password="pw"
        )
        self.admin.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.storekeeper = get_user_model().objects.create_user(
            username="keeper", password="pw"
        )
        self.storekeeper.groups.add(Group.objects.get(name="Комірник"))
        self.auditor = get_user_model().objects.create_user(
            username="auditor", password="pw"
        )
        self.superuser = get_user_model().objects.create_superuser(
            username="root", password="pw", email="root@example.com"
        )
        self.auditor.groups.add(Group.objects.get(name="Перегляд / аудитор"))
        self.unit = Unit.objects.create(name="Штука", symbol="шт")
        self.category = Category.objects.create(name="Кабель")
        self.item = Item.objects.create(
            name="Кабель ВВГ",
            internal_code="CBL-1",
            category=self.category,
            unit=self.unit,
        )
        self.other_item = Item.objects.create(
            name="Автомат",
            internal_code="AUTO-1",
            category=self.category,
            unit=self.unit,
        )
        self.warehouse = Warehouse.objects.create(name="Основний склад")
        self.other_warehouse = Warehouse.objects.create(name="Резервний склад")
        grant_warehouse_access(
            self.admin,
            [self.warehouse, self.other_warehouse],
            can_delegate=True,
        )
        grant_warehouse_access(
            self.storekeeper,
            [self.warehouse, self.other_warehouse],
        )
        grant_warehouse_access(
            self.auditor,
            [self.warehouse, self.other_warehouse],
        )
        self.location = Location.objects.create(warehouse=self.warehouse, name="A1")
        self.other_location = Location.objects.create(
            warehouse=self.other_warehouse, name="B1"
        )
        self.recipient = Recipient.objects.create(name="Цех 1")
        self.balance = StockBalance.objects.create(
            item=self.item, location=self.location, qty=Decimal("7.000")
        )
        StockBalance.objects.create(
            item=self.other_item, location=self.other_location, qty=Decimal("0.000")
        )
        StockMovement.objects.create(
            movement_type=StockMovement.MovementType.IN,
            item=self.item,
            qty=Decimal("10.000"),
            destination_location=self.location,
            occurred_at=timezone.datetime(
                2026, 1, 10, 12, tzinfo=timezone.get_current_timezone()
            ),
        )
        StockMovement.objects.create(
            movement_type=StockMovement.MovementType.OUT,
            item=self.item,
            qty=Decimal("3.000"),
            source_location=self.location,
            recipient=self.recipient,
            occurred_at=timezone.datetime(
                2026, 1, 12, 12, tzinfo=timezone.get_current_timezone()
            ),
        )
        StockMovement.objects.create(
            movement_type=StockMovement.MovementType.IN,
            item=self.other_item,
            qty=Decimal("5.000"),
            destination_location=self.other_location,
            occurred_at=timezone.datetime(
                2026, 2, 1, 12, tzinfo=timezone.get_current_timezone()
            ),
        )

    def test_storekeeper_menu_hides_management_analytics_and_admin(self):
        self.client.force_login(self.storekeeper)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Склад самообслуговування")
        for label in [
            "Керування",
            "Аналітика",
            "Адмін-панель",
            "Категорії",
            "Одиниці виміру",
            "Принтери",
            "Шаблони етикеток",
        ]:
            self.assertNotContains(response, label)

    def test_storekeeper_cannot_open_analytics_urls(self):
        self.client.force_login(self.storekeeper)
        response = self.client.get(reverse("management_analytics"))
        self.assertEqual(response.status_code, 403)
        response = self.client.get(reverse("analytics"))
        self.assertEqual(response.status_code, 403)

    def test_storekeeper_cannot_manage_users(self):
        self.client.force_login(self.storekeeper)
        response = self.client.get(reverse("management_users"))
        self.assertEqual(response.status_code, 403)

    def test_auditor_cannot_edit_directories(self):
        self.client.force_login(self.auditor)
        response = self.client.post(
            reverse("unit_create"), {"name": "Кг", "symbol": "кг", "is_active": "on"}
        )
        self.assertEqual(response.status_code, 403)

    def test_auditor_cannot_create_stock_issue_or_transfer(self):
        self.client.force_login(self.auditor)
        response = self.client.get(reverse("stock_issue"))
        self.assertEqual(response.status_code, 403)

        response = self.client.post(reverse("stock_issue"), {})
        self.assertEqual(response.status_code, 403)

        response = self.client.get(reverse("stock_transfer"))
        self.assertEqual(response.status_code, 403)

        response = self.client.post(reverse("stock_transfer"), {})
        self.assertEqual(response.status_code, 403)

        response = self.client.get(reverse("stock_receive"))
        self.assertEqual(response.status_code, 403)

        response = self.client.post(reverse("stock_receive"), {})
        self.assertEqual(response.status_code, 403)

        response = self.client.get(reverse("stock_writeoff"))
        self.assertEqual(response.status_code, 403)

        response = self.client.post(reverse("stock_writeoff"), {})
        self.assertEqual(response.status_code, 403)


class DashboardPermissionTests(TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        call_command("compilemessages", verbosity=0)

    def setUp(self):
        call_command("init_roles", stdout=StringIO())
        User = get_user_model()
        self.admin = User.objects.create_user(username="dash-admin", password="pw")
        self.admin.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.storekeeper = User.objects.create_user(
            username="dash-storekeeper", password="pw"
        )
        self.storekeeper.groups.add(Group.objects.get(name="Комірник"))
        self.auditor = User.objects.create_user(username="dash-auditor", password="pw")
        self.auditor.groups.add(Group.objects.get(name="Перегляд / аудитор"))
        self.warehouse = Warehouse.objects.create(name="Dashboard warehouse")
        grant_warehouse_access(self.admin, self.warehouse, can_delegate=True)
        grant_warehouse_access(self.storekeeper, self.warehouse)
        grant_warehouse_access(self.auditor, self.warehouse)

    def dashboard_for(self, user, path=None):
        from django.utils import translation

        translation.activate("en" if path and path.startswith("/en/") else "uk")
        self.client.force_login(user)
        return self.client.get(path or reverse("dashboard"))

    def tearDown(self):
        from django.utils import translation

        translation.activate("uk")

    def test_admin_dashboard_shows_stock_transfer_card(self):
        response = self.dashboard_for(self.admin, "/uk/")

        self.assertContains(response, "Переміщення товару")

    def test_user_self_service_dashboard_hides_stock_transfer_card(self):
        response = self.dashboard_for(self.storekeeper, "/uk/")

        self.assertNotContains(response, "Перемістити товар")

    def test_auditor_dashboard_hides_stock_transfer_card(self):
        response = self.dashboard_for(self.auditor, "/uk/")

        self.assertNotContains(response, "Переміщення товару")

    def test_storekeeper_can_open_ukrainian_stock_transfer_page(self):
        response = self.dashboard_for(self.storekeeper, "/uk/stock/transfer/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Переміщення товару")

    def test_admin_dashboard_contains_required_groups_and_operations(self):
        response = self.dashboard_for(self.admin)

        self.assertContains(response, "Часті операції")
        self.assertContains(response, "Контроль")
        self.assertContains(response, "Номенклатура")
        html = response.content.decode()
        self.assertNotIn('class="sidebar-link"', html)
        for label in [
            "Прихід товару",
            "Видача товару",
            "Переміщення товару",
            "Інвентаризація",
        ]:
            self.assertContains(response, label)


    def test_admin_dashboard_has_polished_layout_sections_and_links(self):
        response = self.dashboard_for(self.admin)
        html = response.content.decode()

        self.assertNotContains(response, "dashboard-action-strip")
        self.assertNotContains(response, "quick-actions")
        self.assertContains(response, "compact-card-grid")
        self.assertContains(response, "dashboard-grid--compact")
        self.assertContains(response, "operation-card")
        self.assertContains(response, "Часті операції")
        self.assertContains(response, "Контроль")
        self.assertContains(response, "Номенклатура")
        html = response.content.decode()
        self.assertNotIn('class="sidebar-link"', html)
        for url_name in [
            "stock_receive",
            "stock_issue",
            "stock_return",
            "stock_transfer",
            "stock_writeoff",
            "inventory_list",
            "stockbalance_list",
            "movement_list",
        ]:
            self.assertIn(f'href="{reverse(url_name)}"', html)
        self.assertIn('class="operation-card clickable-card operation-card--issue"', html)
        self.assertNotIn('data-bs-target="#directoriesCollapse"', html)
        self.assertNotIn('data-bs-target="#adminCollapse"', html)
        self.assertNotIn("quick-action-btn--issue", html)
        self.assertNotIn("quick-action-btn--return", html)
        self.assertNotIn("quick-action-btn--receive", html)


    def test_admin_dashboard_has_item_create_quick_action(self):
        response = self.dashboard_for(self.admin, "/uk/")

        self.assertContains(response, reverse("item_create"))
        self.assertContains(response, "+ Створити товар / матеріал")

    def test_admin_dashboard_cards_are_fully_clickable_without_cta_buttons(self):
        response = self.dashboard_for(self.admin)
        html = response.content.decode()

        self.assertNotIn("Відкрити", html)
        self.assertNotIn("Відкрити операцію", html)
        self.assertNotIn("Перейти", html)
        self.assertNotIn("Основна дія", html)
        for label, url_name in [
            ("Видача товару", "stock_issue"),
            ("Повернення товару", "stock_return"),
            ("Прихід товару", "stock_receive"),
            ("Переміщення товару", "stock_transfer"),
            ("Залишки на складі", "stockbalance_list"),
            ("Журнал операцій", "movement_list"),
        ]:
            self.assertIn(label, html)
            self.assertIn(f'href="{reverse(url_name)}"', html)
        self.assertIn(f'href="{reverse("stock_return")}"', html)
        self.assertNotIn("Пошук товару", html)

    def test_storekeeper_dashboard_contains_workplace_actions_without_admin_items(self):
        response = self.dashboard_for(self.storekeeper, "/uk/")

        self.assertTemplateUsed(response, "core/storekeeper_workplace.html")
        self.assertTrue(response.context["is_storekeeper_workplace"])
        html = response.content.decode()
        for label in [
            "Склад самообслуговування",
            "Оберіть дію",
            "Взяти товар",
            "Повернути товар",
            "Зіскануйте товар і зафіксуйте видачу зі складу.",
            "Зіскануйте товар і зафіксуйте повернення на склад.",
        ]:
            self.assertContains(response, label)
        main_html = html[html.index('<main class="col-12">'):]
        for label in [
            "Категорії",
            "Одиниці виміру",
            "Принтери",
            "Шаблони етикеток",
            "Аналітика",
            "Керування",
            "Працівники / отримувачі",
            "Довідники",
            "Журнал операцій",
            "Залишки на складі",
            "Інвентаризація",
            "Налаштування складу",
            "Початкові залишки",
            "Знайти товар",
            "Відкрити",
            "Перемістити товар",
            "Списати товар",
            "Провести інвентаризацію",
            "Перевірити залишки",
            "Надрукувати етикетку",
            "Пошук товару",
            "Назва, внутрішній код або штрихкод",
            "Робоче місце комірника",
            "Комірник",
            "Допомога",
        ]:
            self.assertNotIn(label, main_html)

    def test_storekeeper_workplace_primary_cards_are_links(self):
        response = self.dashboard_for(self.storekeeper, "/uk/")
        html = response.content.decode()

        for label, url_name in [
            ("Взяти товар", "stock_issue"),
            ("Повернути товар", "stock_return"),
        ]:
            self.assertIn(
                f'<a class="card self-service-action-card text-decoration-none text-reset" href="{reverse(url_name)}"',
                html,
            )
            self.assertIn(
                f'<a class="card self-service-action-card text-decoration-none text-reset" href="{reverse(url_name)}" aria-label="{label}"',
                html,
            )
            self.assertIn(label, html)
        main_html = html[html.index('<main class="col-12">'):]
        for label in ["Перемістити товар", "Списати товар", "Видача товару", "Прихід товару"]:
            self.assertNotIn(label, main_html)

    def test_storekeeper_workplace_hides_sidebar_and_uses_full_width(self):
        response = self.dashboard_for(self.storekeeper, "/uk/")
        html = response.content.decode()

        self.assertContains(response, "Склад самообслуговування")
        self.assertNotContains(response, "Навігація")
        self.assertIn('<main class="col-12">', html)
        self.assertNotIn('<main class="col-lg-10">', html)
        for label in ["Взяти товар", "Повернути товар"]:
            self.assertContains(response, label)
        main_html = html[html.index('<main class="col-12">'):]
        for label in ["Перемістити товар", "Списати товар", "Видача товару", "Прихід товару"]:
            self.assertNotIn(label, main_html)

    def test_storekeeper_self_service_receive_page_hides_sidebar(self):
        response = self.dashboard_for(self.storekeeper, "/uk/stock/receive/")
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Навігація")
        self.assertIn('<main class="col-12">', html)
        self.assertNotIn('<main class="col-lg-10">', html)

    def test_warehouse_admin_keeps_full_dashboard(self):
        response = self.dashboard_for(self.admin, "/uk/")
        html = response.content.decode()

        self.assertTemplateUsed(response, "core/dashboard.html")
        self.assertTemplateNotUsed(response, "core/storekeeper_workplace.html")
        self.assertFalse(response.context["is_storekeeper_workplace"])
        self.assertTrue(response.context["hide_sidebar"])
        self.assertNotContains(response, "Навігація")
        self.assertContains(response, '<main class="col-12">')
        self.assertContains(response, "Головна")
        self.assertContains(response, "Часті операції")
        self.assertContains(response, "Контроль")
        self.assertContains(response, "Номенклатура")
        html = response.content.decode()
        main_html = html[html.index('<main class="col-12">'):]
        self.assertNotIn('class="sidebar-link"', html)
        for label in ["Принтери", "Шаблони етикеток", "Керування складом", "Аналітика складу"]:
            self.assertNotIn(label, main_html)
        self.assertIn(f'href="{reverse("stock_receive")}"', html)
        self.assertIn(f'href="{reverse("stock_issue")}"', html)
        self.assertIn(f'href="{reverse("stock_return")}"', html)
        self.assertNotContains(response, "Склад самообслуговування")
        self.assertNotContains(response, "Пошук товару")
        self.assertNotContains(response, "autofocus")

    def test_auditor_dashboard_is_view_only(self):
        response = self.dashboard_for(self.auditor)

        for label in ["Прихід товару", "Видача товару", "Переміщення товару", "Початкові залишки"]:
            self.assertNotContains(response, label)
        for label in ["Залишки на складі", "Журнал операцій", "Інвентаризація"]:
            self.assertContains(response, label)

    def test_storekeeper_sidebar_hides_recipients(self):
        response = self.dashboard_for(self.storekeeper)

        self.assertNotContains(response, "Працівники / отримувачі")
        self.assertNotContains(response, "Довідники")

    def test_auditor_sidebar_hides_create_operations(self):
        response = self.dashboard_for(self.auditor)

        for label in ["Прихід товару", "Видача товару", "Переміщення товару", "Початкові залишки"]:
            self.assertNotContains(response, label)
        self.assertContains(response, "Інвентаризація")

    def test_mobile_menu_hides_management_for_storekeeper(self):
        response = self.dashboard_for(self.storekeeper)
        html = response.content.decode()

        self.assertNotIn('data-bs-target="#mainNav"', html)
        self.assertNotIn('id="mainNav"', html)
        self.assertNotIn('<a class="nav-link"', html)
        self.assertNotIn("Керування", html)
        self.assertNotIn("management/", html)
