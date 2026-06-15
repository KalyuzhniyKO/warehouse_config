from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import (
    Item,
    Location,
    PurchaseRequest,
    StockBalance,
    StockMovement,
    Unit,
    Warehouse,
)
from core.services.locations import get_default_location_for_warehouse
from core.services.stock import StockServiceError, cancel_stock_movement, receive_stock
from core.tests.warehouse_access_utils import grant_warehouse_access


class PurchaseRequestReceivingTests(TestCase):
    def setUp(self):
        call_command("init_roles", stdout=StringIO())
        User = get_user_model()
        self.admin = User.objects.create_user("receive-admin", password="pw")
        self.admin.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.owner = User.objects.create_user("receive-owner", password="pw")
        self.owner.groups.add(Group.objects.get(name="Комірник"))
        self.other_user = User.objects.create_user("receive-other", password="pw")
        self.other_user.groups.add(Group.objects.get(name="Комірник"))
        self.unit = Unit.objects.create(name="Piece", symbol="pc")
        self.item = Item.objects.create(name="Purchase receive item", unit=self.unit)
        self.warehouse = Warehouse.objects.create(name="Purchase receive warehouse")
        self.location = Location.objects.create(
            warehouse=self.warehouse, name="Purchase receive location"
        )
        grant_warehouse_access(self.admin, self.warehouse, can_delegate=True)
        grant_warehouse_access(self.owner, self.warehouse)
        grant_warehouse_access(self.other_user, self.warehouse)

    def create_request(self, *, user=None, status=PurchaseRequest.Status.APPROVED):
        return PurchaseRequest.objects.create(
            title="Planned cables",
            description="",
            requested_qty=Decimal("10.000"),
            unit="pc",
            estimated_unit_price=Decimal("2.00"),
            currency="UAH",
            supplier_name="Cable supplier",
            requested_by=user or self.owner,
            status=status,
        )

    def receive_via_form(self, *, user, qty, purchase_request=None):
        self.client.force_login(user)
        query = f"?barcode={self.item.barcode.barcode}"
        if purchase_request is not None:
            query += f"&purchase_request={purchase_request.pk}"
        get_response = self.client.get(reverse("stock_receive") + query)
        token = get_response.context["operation_token"]
        data = {
            "operation_token": token,
            "item": self.item.pk,
            "warehouse": self.warehouse.pk,
            "location": self.location.pk,
            "qty": str(qty),
            "comment": "",
            "occurred_at": timezone.now().strftime("%Y-%m-%dT%H:%M"),
        }
        if purchase_request is not None:
            data["purchase_request"] = purchase_request.pk
        return self.client.post(reverse("stock_receive"), data)

    def test_existing_receive_without_purchase_request_still_works(self):
        purchase_request = self.create_request()

        response = self.receive_via_form(user=self.owner, qty="3.000")

        movement = StockMovement.objects.get(movement_type=StockMovement.MovementType.IN)
        purchase_request.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(movement.purchase_request)
        self.assertEqual(purchase_request.status, PurchaseRequest.Status.APPROVED)

    def test_owner_can_receive_from_own_approved_request(self):
        purchase_request = self.create_request()

        response = self.receive_via_form(
            user=self.owner, qty="3.000", purchase_request=purchase_request
        )

        movement = StockMovement.objects.get(movement_type=StockMovement.MovementType.IN)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(movement.purchase_request, purchase_request)

    def test_admin_can_receive_from_another_users_request(self):
        purchase_request = self.create_request(user=self.other_user)

        response = self.receive_via_form(
            user=self.admin, qty="3.000", purchase_request=purchase_request
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(StockMovement.objects.get().purchase_request, purchase_request)

    def test_regular_user_cannot_receive_from_another_users_request(self):
        purchase_request = self.create_request(user=self.other_user)

        response = self.receive_via_form(
            user=self.owner, qty="3.000", purchase_request=purchase_request
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("purchase_request", response.context["form"].errors)
        self.assertFalse(StockMovement.objects.exists())

    def test_partial_and_full_receives_update_quantities_and_status(self):
        purchase_request = self.create_request()

        self.receive_via_form(
            user=self.owner, qty="4.000", purchase_request=purchase_request
        )
        purchase_request.refresh_from_db()
        self.assertEqual(
            purchase_request.status, PurchaseRequest.Status.PARTIALLY_RECEIVED
        )
        self.assertEqual(purchase_request.received_qty, Decimal("4.000"))
        self.assertEqual(purchase_request.remaining_qty, Decimal("6.000"))

        self.receive_via_form(
            user=self.owner, qty="6.000", purchase_request=purchase_request
        )
        purchase_request.refresh_from_db()
        self.assertEqual(purchase_request.status, PurchaseRequest.Status.RECEIVED)
        self.assertEqual(purchase_request.received_qty, Decimal("10.000"))
        self.assertEqual(purchase_request.remaining_qty, Decimal("0.000"))

    def test_receive_more_than_remaining_is_prevented(self):
        purchase_request = self.create_request()
        receive_stock(
            item=self.item,
            location=self.location,
            qty=Decimal("8.000"),
            performed_by=self.owner,
            purchase_request=purchase_request,
        )

        response = self.receive_via_form(
            user=self.owner, qty="3.000", purchase_request=purchase_request
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("qty", response.context["form"].errors)
        self.assertEqual(purchase_request.received_qty, Decimal("8.000"))

    def test_draft_rejected_and_cancelled_requests_cannot_be_received(self):
        for status in [
            PurchaseRequest.Status.DRAFT,
            PurchaseRequest.Status.REJECTED,
            PurchaseRequest.Status.CANCELLED,
        ]:
            with self.subTest(status=status):
                purchase_request = self.create_request(status=status)
                response = self.receive_via_form(
                    user=self.owner, qty="1.000", purchase_request=purchase_request
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn("purchase_request", response.context["form"].errors)
                self.assertFalse(
                    StockMovement.objects.filter(purchase_request=purchase_request).exists()
                )

    def test_service_rejects_non_receivable_request(self):
        purchase_request = self.create_request(status=PurchaseRequest.Status.DRAFT)

        with self.assertRaises(StockServiceError):
            receive_stock(
                item=self.item,
                location=self.location,
                qty=Decimal("1.000"),
                performed_by=self.owner,
                purchase_request=purchase_request,
            )

        self.assertFalse(StockMovement.objects.exists())

    def test_cancelling_linked_receive_recalculates_received_quantity(self):
        superuser = get_user_model().objects.create_superuser(
            "receive-super", "super@example.com", "pw"
        )
        purchase_request = self.create_request()
        movement = receive_stock(
            item=self.item,
            location=self.location,
            qty=Decimal("4.000"),
            performed_by=self.owner,
            purchase_request=purchase_request,
        )

        cancel_stock_movement(
            movement=movement, cancelled_by=superuser, reason="Wrong receipt"
        )

        purchase_request.refresh_from_db()
        self.assertEqual(purchase_request.received_qty, Decimal("0"))
        self.assertEqual(purchase_request.remaining_qty, Decimal("10.000"))
        self.assertEqual(purchase_request.status, PurchaseRequest.Status.APPROVED)

    def test_linked_receive_appears_in_journal_and_increases_balance(self):
        purchase_request = self.create_request()

        self.receive_via_form(
            user=self.owner, qty="3.000", purchase_request=purchase_request
        )
        movement = StockMovement.objects.get(purchase_request=purchase_request)
        default_location = get_default_location_for_warehouse(self.warehouse)
        self.assertEqual(
            StockBalance.objects.get(item=self.item, location=default_location).qty,
            Decimal("3.000"),
        )

        self.client.force_login(self.admin)
        response = self.client.get(reverse("movement_list"))
        self.assertContains(response, self.item.name)
        self.assertIn(movement, response.context["movements"])

    def test_purchase_request_detail_shows_linked_movements_and_receive_shortcut(self):
        purchase_request = self.create_request()
        movement = receive_stock(
            item=self.item,
            location=self.location,
            qty=Decimal("3.000"),
            performed_by=self.owner,
            purchase_request=purchase_request,
        )
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse("purchase_request_detail", args=[purchase_request.pk])
        )

        shortcut = (
            f'{reverse("stock_receive")}?purchase_request={purchase_request.pk}'
        )
        self.assertContains(response, "Прийняти на склад")
        self.assertContains(response, shortcut)
        self.assertContains(response, self.item.name)
        self.assertIn(movement, response.context["linked_receive_movements"])
        self.assertContains(response, "Залишилось отримати")

    def test_receive_shortcut_preselects_request_and_shows_receiving_summary(self):
        purchase_request = self.create_request()
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse("stock_receive"), {"purchase_request": purchase_request.pk}
        )

        self.assertEqual(
            response.context["form"].initial["purchase_request"], purchase_request
        )
        self.assertEqual(response.context["selected_purchase_request"], purchase_request)
        self.assertContains(response, purchase_request.title)
        self.assertContains(response, purchase_request.supplier_name)
        self.assertContains(response, "Залишилось отримати")
