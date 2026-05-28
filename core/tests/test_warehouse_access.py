from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Group
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from core.models import (
    AuditLog,
    InventoryCount,
    Item,
    Location,
    Recipient,
    StockBalance,
    StockMovement,
    Unit,
    UserWarehouseAccess,
    Warehouse,
)
from core.services.stock import can_cancel_stock_movement
from core.services.warehouse_access import (
    get_accessible_warehouses,
    get_delegatable_warehouses,
    user_can_access_warehouse,
    user_can_delegate_warehouse,
)


class WarehouseScopedAccessTests(TestCase):
    def setUp(self):
        call_command("init_roles", stdout=StringIO())
        User = get_user_model()
        self.superuser = User.objects.create_superuser(
            username="system-admin", password="pw", email="admin@example.com"
        )
        self.admin = User.objects.create_user(username="warehouse-admin", password="pw")
        self.admin.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.storekeeper = User.objects.create_user(
            username="warehouse-user", password="pw"
        )
        self.storekeeper.groups.add(Group.objects.get(name="Комірник"))
        self.no_access_user = User.objects.create_user(
            username="no-access", password="pw"
        )
        self.no_access_user.groups.add(Group.objects.get(name="Комірник"))

        self.unit = Unit.objects.create(name="Piece", symbol="pc")
        self.allowed_item = Item.objects.create(name="Allowed item", unit=self.unit)
        self.denied_item = Item.objects.create(name="Denied item", unit=self.unit)
        self.allowed_warehouse = Warehouse.objects.create(name="Allowed warehouse")
        self.denied_warehouse = Warehouse.objects.create(name="Denied warehouse")
        self.allowed_location = Location.objects.create(
            warehouse=self.allowed_warehouse, name="Allowed location"
        )
        self.denied_location = Location.objects.create(
            warehouse=self.denied_warehouse, name="Denied location"
        )
        self.recipient = Recipient.objects.create(name="Recipient")
        self.allowed_balance = StockBalance.objects.create(
            item=self.allowed_item,
            location=self.allowed_location,
            qty=Decimal("5.000"),
        )
        self.denied_balance = StockBalance.objects.create(
            item=self.denied_item,
            location=self.denied_location,
            qty=Decimal("7.000"),
        )
        self.allowed_movement = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.OUT,
            item=self.allowed_item,
            qty=Decimal("1.000"),
            source_location=self.allowed_location,
            recipient=self.recipient,
            document_number="ALLOWED",
        )
        self.denied_movement = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.OUT,
            item=self.denied_item,
            qty=Decimal("1.000"),
            source_location=self.denied_location,
            recipient=self.recipient,
            document_number="DENIED",
        )
        UserWarehouseAccess.objects.create(
            user=self.admin,
            warehouse=self.allowed_warehouse,
            can_delegate=True,
            created_by=self.superuser,
        )
        UserWarehouseAccess.objects.create(
            user=self.storekeeper,
            warehouse=self.allowed_warehouse,
            can_delegate=False,
            created_by=self.admin,
        )

    def visible_pks(self, response, context_name):
        return {obj.pk for obj in response.context[context_name]}

    def test_service_rules_for_superuser_admin_user_and_anonymous(self):
        self.assertCountEqual(
            get_accessible_warehouses(self.superuser),
            [self.allowed_warehouse, self.denied_warehouse],
        )
        self.assertEqual(
            list(get_accessible_warehouses(self.admin)), [self.allowed_warehouse]
        )
        self.assertEqual(
            list(get_accessible_warehouses(self.storekeeper)),
            [self.allowed_warehouse],
        )
        self.assertFalse(get_accessible_warehouses(self.no_access_user).exists())
        self.assertFalse(get_accessible_warehouses(AnonymousUser()).exists())
        self.assertTrue(user_can_access_warehouse(self.admin, self.allowed_warehouse))
        self.assertFalse(user_can_access_warehouse(self.admin, self.denied_warehouse))

    def test_delegation_rules_are_warehouse_scoped(self):
        self.assertEqual(
            list(get_delegatable_warehouses(self.admin)), [self.allowed_warehouse]
        )
        self.assertTrue(
            user_can_delegate_warehouse(self.admin, self.allowed_warehouse)
        )
        self.assertFalse(
            user_can_delegate_warehouse(self.admin, self.denied_warehouse)
        )
        self.assertFalse(
            user_can_delegate_warehouse(self.storekeeper, self.allowed_warehouse)
        )

    def test_warehouse_list_is_scoped_and_superuser_sees_everything(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("warehouse_list"))
        self.assertEqual(self.visible_pks(response, "objects"), {self.allowed_warehouse.pk})

        self.client.force_login(self.superuser)
        response = self.client.get(reverse("warehouse_list"))
        self.assertEqual(
            self.visible_pks(response, "objects"),
            {self.allowed_warehouse.pk, self.denied_warehouse.pk},
        )

    def test_user_without_access_sees_no_warehouse_data(self):
        self.client.force_login(self.no_access_user)
        balances = self.client.get(reverse("stockbalance_list"))
        movements = self.client.get(reverse("movement_list"))
        self.assertEqual(list(balances.context["balances"]), [])
        self.assertEqual(list(movements.context["movements"]), [])

        dashboard = self.client.get(reverse("dashboard"))
        self.assertContains(
            dashboard,
            "У вас немає доступу до жодного складу. Зверніться до адміністратора.",
        )

    def test_stock_balance_and_movement_lists_are_scoped(self):
        self.client.force_login(self.admin)
        balance_response = self.client.get(reverse("stockbalance_list"))
        movement_response = self.client.get(reverse("movement_list"))
        self.assertEqual(
            self.visible_pks(balance_response, "balances"), {self.allowed_balance.pk}
        )
        self.assertEqual(
            self.visible_pks(movement_response, "movements"),
            {self.allowed_movement.pk},
        )

    def test_movement_detail_and_print_reject_inaccessible_warehouse(self):
        self.client.force_login(self.storekeeper)
        detail = self.client.get(
            reverse("stock_issue_result", args=[self.denied_movement.pk])
        )
        slip = self.client.get(
            reverse("stock_movement_print", args=[self.denied_movement.pk])
        )
        self.assertEqual(detail.status_code, 404)
        self.assertEqual(slip.status_code, 404)

    def test_analytics_and_inventory_are_scoped(self):
        InventoryCount.objects.create(
            number="INV-ALLOWED",
            warehouse=self.allowed_warehouse,
            status=InventoryCount.Status.IN_PROGRESS,
        )
        denied_inventory = InventoryCount.objects.create(
            number="INV-DENIED",
            warehouse=self.denied_warehouse,
            status=InventoryCount.Status.IN_PROGRESS,
        )

        self.client.force_login(self.admin)
        analytics = self.client.get(reverse("management_analytics"))
        self.assertEqual(analytics.context["summary"]["operations_count"], 1)

        inventory_list = self.client.get(reverse("inventory_list"))
        self.assertEqual(
            self.visible_pks(inventory_list, "inventory_counts"),
            {InventoryCount.objects.get(number="INV-ALLOWED").pk},
        )
        inventory_detail = self.client.get(
            reverse("inventory_detail", args=[denied_inventory.pk])
        )
        self.assertEqual(inventory_detail.status_code, 404)

    def test_delegating_admin_can_assign_only_their_warehouses(self):
        group = Group.objects.get(name="Комірник")
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("management_user_create"),
            {
                "username": "delegated-user",
                "password1": "secret",
                "password2": "secret",
                "groups": [str(group.pk)],
                "is_active": "on",
                f"warehouse_access_{self.allowed_warehouse.pk}": "on",
                f"warehouse_delegate_{self.allowed_warehouse.pk}": "on",
            },
        )

        self.assertRedirects(response, reverse("management_users"))
        delegated_user = get_user_model().objects.get(username="delegated-user")
        access = UserWarehouseAccess.objects.get(
            user=delegated_user, warehouse=self.allowed_warehouse
        )
        self.assertTrue(access.can_delegate)
        self.assertEqual(access.created_by, self.admin)
        self.assertFalse(
            UserWarehouseAccess.objects.filter(
                user=delegated_user, warehouse=self.denied_warehouse, is_active=True
            ).exists()
        )

    def test_non_superuser_cannot_assign_warehouse_they_cannot_delegate(self):
        group = Group.objects.get(name="Комірник")
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("management_user_update", args=[self.storekeeper.pk]),
            {
                "first_name": "",
                "last_name": "",
                "email": "",
                "groups": [str(group.pk)],
                "is_active": "on",
                f"warehouse_access_{self.allowed_warehouse.pk}": "on",
                f"warehouse_access_{self.denied_warehouse.pk}": "on",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ви не можете надати доступ до цього складу.")
        self.assertFalse(
            UserWarehouseAccess.objects.filter(
                user=self.storekeeper,
                warehouse=self.denied_warehouse,
                is_active=True,
            ).exists()
        )

    def test_warehouse_access_create_update_and_remove_write_audit_log(self):
        group = Group.objects.get(name="Комірник")
        target = get_user_model().objects.create_user("audit-target", password="pw")
        target.groups.add(group)
        self.client.force_login(self.admin)

        self.client.post(
            reverse("management_user_update", args=[target.pk]),
            {
                "first_name": "",
                "last_name": "",
                "email": "",
                "groups": [str(group.pk)],
                "is_active": "on",
                f"warehouse_access_{self.allowed_warehouse.pk}": "on",
                f"warehouse_delegate_{self.allowed_warehouse.pk}": "on",
            },
        )
        self.client.post(
            reverse("management_user_update", args=[target.pk]),
            {
                "first_name": "",
                "last_name": "",
                "email": "",
                "groups": [str(group.pk)],
                "is_active": "on",
                f"warehouse_access_{self.allowed_warehouse.pk}": "on",
            },
        )
        self.client.post(
            reverse("management_user_update", args=[target.pk]),
            {
                "first_name": "",
                "last_name": "",
                "email": "",
                "groups": [str(group.pk)],
                "is_active": "on",
            },
        )

        actions = list(
            AuditLog.objects.filter(action__startswith="warehouse_access.")
            .order_by("id")
            .values_list("action", flat=True)
        )
        self.assertEqual(
            actions,
            [
                "warehouse_access.created",
                "warehouse_access.updated",
                "warehouse_access.removed",
            ],
        )
        log = AuditLog.objects.get(action="warehouse_access.created")
        self.assertEqual(log.actor, self.admin)
        self.assertEqual(log.changes["target_user_id"], target.pk)
        self.assertEqual(log.changes["warehouse_id"], self.allowed_warehouse.pk)
        self.assertTrue(log.changes["can_delegate"])
        self.assertEqual(log.changes["actor_id"], self.admin.pk)

    def test_cancellation_remains_superuser_only(self):
        self.assertTrue(can_cancel_stock_movement(self.superuser, self.allowed_movement))
        self.assertFalse(can_cancel_stock_movement(self.admin, self.allowed_movement))
