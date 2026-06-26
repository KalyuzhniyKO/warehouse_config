from decimal import Decimal
from io import StringIO

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from core.models import (
    AuditLog,
    Item,
    PurchaseRequest,
    StockBalance,
    StockMovement,
    Unit,
    Warehouse,
)


class SecurityHardeningTests(TestCase):
    def setUp(self):
        call_command("init_roles", stdout=StringIO())
        User = get_user_model()
        self.admin_user = User.objects.create_user(
            username="security-admin",
            password="strong-password",
        )
        self.admin_user.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.superuser = User.objects.create_superuser(
            username="security-root",
            password="strong-password",
        )
        self.unit = Unit.objects.create(name="Piece", symbol="шт")
        self.item = Item.objects.create(name="Security item", unit=self.unit)
        self.warehouse = Warehouse.objects.create(name="Security warehouse")
        self.balance = StockBalance.objects.create(
            item=self.item,
            warehouse=self.warehouse,
            qty=Decimal("1.000"),
        )
        self.movement = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.IN,
            item=self.item,
            destination_warehouse=self.warehouse,
            qty=Decimal("1.000"),
        )

    @override_settings(
        AUTH_PASSWORD_VALIDATORS=[
            {
                "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
                "OPTIONS": {"min_length": 8},
            },
            {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
            {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
        ]
    )
    def test_user_management_rejects_weak_passwords(self):
        self.client.force_login(self.admin_user)

        create_response = self.client.post(
            reverse("management_user_create"),
            {
                "username": "weak-user",
                "password1": "123",
                "password2": "123",
                "groups": [],
                "is_active": "on",
            },
        )
        password_response = self.client.post(
            reverse("management_user_password", args=[self.admin_user.pk]),
            {"password1": "123", "password2": "123"},
        )

        self.assertEqual(create_response.status_code, 200)
        self.assertContains(create_response, "id_password1_error")
        self.assertContains(create_response, "занадто короткий")
        self.assertFalse(get_user_model().objects.filter(username="weak-user").exists())
        self.assertEqual(password_response.status_code, 200)
        self.assertContains(password_response, "id_password1_error")

    def test_auth_events_are_written_to_audit_log(self):
        self.client.post(
            reverse("login"),
            {"username": "security-admin", "password": "wrong-password"},
        )
        self.client.post(
            reverse("login"),
            {"username": "security-admin", "password": "strong-password"},
        )
        self.client.post(reverse("logout"))

        self.assertTrue(AuditLog.objects.filter(action="auth.login_failed").exists())
        self.assertTrue(
            AuditLog.objects.filter(
                actor=self.admin_user,
                action="auth.login",
            ).exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(
                actor=self.admin_user,
                action="auth.logout",
            ).exists()
        )

    def test_user_management_actions_are_written_to_audit_log(self):
        self.client.force_login(self.admin_user)
        group = Group.objects.get(name="Комірник")

        self.client.post(
            reverse("management_user_create"),
            {
                "username": "audited-user",
                "password1": "strong-password",
                "password2": "strong-password",
                "groups": [str(group.pk)],
                "is_active": "on",
            },
        )
        target = get_user_model().objects.get(username="audited-user")
        self.client.post(
            reverse("management_user_update", args=[target.pk]),
            {
                "first_name": "Audit",
                "last_name": "User",
                "email": "audit@example.com",
                "groups": [str(group.pk)],
                "is_active": "on",
            },
        )
        self.client.post(
            reverse("management_user_password", args=[target.pk]),
            {"password1": "new-strong-password", "password2": "new-strong-password"},
        )

        self.assertTrue(AuditLog.objects.filter(action="user.created").exists())
        self.assertTrue(AuditLog.objects.filter(action="user.updated").exists())
        self.assertTrue(AuditLog.objects.filter(action="user.password_changed").exists())

    def test_purchase_request_actions_are_written_to_audit_log(self):
        self.client.force_login(self.admin_user)
        purchase_request = PurchaseRequest.objects.create(
            title="Security request",
            requested_qty=Decimal("1.000"),
            unit="шт",
            requested_by=self.admin_user,
            status=PurchaseRequest.Status.PENDING_APPROVAL,
        )

        self.client.post(reverse("purchase_request_approve", args=[purchase_request.pk]))
        self.client.post(
            reverse("purchase_request_tracking_status", args=[purchase_request.pk]),
            {"payment_status": PurchaseRequest.PaymentStatus.PAID},
        )
        self.client.post(
            reverse("purchase_request_archive_action", args=[purchase_request.pk]),
            {"archive_reason": "Security audit"},
        )
        self.client.post(
            reverse("purchase_request_restore_action", args=[purchase_request.pk])
        )

        self.assertTrue(AuditLog.objects.filter(action="purchase_request.approve").exists())
        self.assertTrue(
            AuditLog.objects.filter(action="purchase_request.tracking_updated").exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(action="purchase_request.archived").exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(action="purchase_request.restored").exists()
        )

    def test_stock_and_audit_admin_are_read_only(self):
        request = RequestFactory().get("/")
        request.user = self.superuser
        stock_balance_admin = admin.site._registry[StockBalance]
        stock_movement_admin = admin.site._registry[StockMovement]
        audit_log_admin = admin.site._registry[AuditLog]

        for model_admin, obj in (
            (stock_balance_admin, self.balance),
            (stock_movement_admin, self.movement),
        ):
            self.assertFalse(model_admin.has_add_permission(request))
            self.assertFalse(model_admin.has_change_permission(request, obj))
            self.assertFalse(model_admin.has_delete_permission(request, obj))
            self.assertIsNone(model_admin.actions)

        audit_log = AuditLog.objects.create(action="security.test")
        self.assertFalse(audit_log_admin.has_add_permission(request))
        self.assertFalse(audit_log_admin.has_change_permission(request, audit_log))
        self.assertFalse(audit_log_admin.has_delete_permission(request, audit_log))
