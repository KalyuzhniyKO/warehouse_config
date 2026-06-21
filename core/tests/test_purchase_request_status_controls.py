from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from core.models import PurchaseRequest, Unit, Warehouse
from core.tests.warehouse_access_utils import grant_warehouse_access


class PurchaseRequestStatusControlTests(TestCase):
    def setUp(self):
        call_command("init_roles", stdout=StringIO())
        User = get_user_model()
        self.admin = User.objects.create_user("status-admin", password="pw")
        self.admin.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.requester = User.objects.create_user("status-requester", password="pw")
        self.tracker = User.objects.create_user("status-tracker", password="pw")
        self.warehouse = Warehouse.objects.create(name="Status controls warehouse")
        Unit.objects.create(name="Piece", symbol="pc")
        grant_warehouse_access(self.admin, self.warehouse, can_delegate=True)
        grant_warehouse_access(self.requester, self.warehouse)
        grant_warehouse_access(self.tracker, self.warehouse)
        self.purchase_request = PurchaseRequest.objects.create(
            requested_by=self.requester,
            title="Readable status controls",
            need_description="",
            requested_qty=Decimal("2.000"),
            unit="pc",
            status=PurchaseRequest.Status.APPROVED,
            approval_status=PurchaseRequest.ApprovalStatus.APPROVED,
        )

    def grant_permission(self, user, codename):
        user.user_permissions.add(Permission.objects.get(codename=codename))

    def test_tracking_user_sees_readable_status_control_classes(self):
        self.grant_permission(self.tracker, "can_view_purchase_requests")
        self.grant_permission(self.tracker, "can_update_purchase_request_tracking")
        self.client.force_login(self.tracker)

        response = self.client.get(reverse("purchase_request_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "purchase-request-status-form")
        self.assertContains(response, "purchase-request-status-select")
        self.assertContains(response, "purchase-request-payment-select")
        self.assertContains(response, "purchase-request-delivery-select")
        self.assertContains(response, "purchase-request-status-submit")
        self.assertContains(response, 'name="payment_status"')
        self.assertContains(response, 'name="delivery_status"')
        self.assertContains(
            response,
            reverse("purchase_request_tracking_status", args=[self.purchase_request.pk]),
        )

    def test_user_without_tracking_permission_sees_badges_not_controls(self):
        self.client.force_login(self.requester)

        response = self.client.get(reverse("purchase_request_list"))
        html = response.content.decode()
        table_body = html[html.index("<tbody>") : html.index("</tbody>")]

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("purchase-request-status-form", table_body)
        self.assertNotIn("purchase-request-payment-select", table_body)
        self.assertNotIn("purchase-request-delivery-select", table_body)
        self.assertNotIn('name="payment_status"', table_body)
        self.assertNotIn('name="delivery_status"', table_body)
        self.assertIn("purchase-status-badge", table_body)
