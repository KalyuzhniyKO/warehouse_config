from io import StringIO
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from django.utils import translation
from django.utils import timezone

from core.models import Item, PurchaseRequest, StockBalance, StockMovement, Unit, Warehouse
from core.tests.i18n_test_utils import compile_test_messages
from core.tests.warehouse_access_utils import grant_warehouse_access


class PurchaseRequestTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        compile_test_messages()

    def setUp(self):
        from django.core.management import call_command

        call_command("init_roles", stdout=StringIO())
        User = get_user_model()
        self.admin = User.objects.create_user("purchase-admin", password="pw")
        self.admin.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.requester = User.objects.create_user("purchase-requester", password="pw")
        self.other_requester = User.objects.create_user("purchase-other", password="pw")
        self.no_access_user = User.objects.create_user("purchase-no-access", password="pw")
        self.warehouse = Warehouse.objects.create(name="Purchase warehouse")
        self.unit = Unit.objects.create(name="Pair", symbol="pairs")
        self.item = Item.objects.create(name="Safety gloves", unit=self.unit)
        grant_warehouse_access(self.admin, self.warehouse, can_delegate=True)
        grant_warehouse_access(self.requester, self.warehouse)
        grant_warehouse_access(self.other_requester, self.warehouse)

    def request_data(self, **overrides):
        data = {
            "request_date": "2026-06-15",
            "requested_item": "Safety gloves",
            "title": "Safety gloves",
            "need_description": "Planned purchase",
            "requested_qty": "12.000",
            "unit": "pairs",
            "unit_price_uah": "55.50",
            "order_type": PurchaseRequest.OrderType.PLANNED,
            "product_url": "",
            "comment": "Needed next month",
        }
        data.update(overrides)
        return data

    def create_request(self, user=None, status=PurchaseRequest.Status.DRAFT, **overrides):
        data = self.request_data(**overrides)
        data.pop("requested_item", None)
        purchase_request = PurchaseRequest.objects.create(
            requested_by=user or self.requester,
            status=status,
            **data,
        )
        purchase_request.refresh_from_db()
        return purchase_request

    def login(self, user):
        self.client.force_login(user)

    def post_action(self, purchase_request, action, user=None):
        self.login(user or self.admin)
        return self.client.post(reverse(f"purchase_request_{action}", args=[purchase_request.pk]))

    def test_user_with_warehouse_access_can_create_purchase_request(self):
        self.login(self.requester)

        response = self.client.post(reverse("purchase_request_create"), self.request_data())

        purchase_request = PurchaseRequest.objects.get()
        self.assertRedirects(
            response, reverse("purchase_request_detail", args=[purchase_request.pk])
        )
        self.assertEqual(purchase_request.requested_by, self.requester)
        self.assertEqual(purchase_request.status, PurchaseRequest.Status.PENDING_APPROVAL)
        self.assertEqual(
            purchase_request.approval_status, PurchaseRequest.ApprovalStatus.PENDING
        )
        self.assertEqual(
            purchase_request.payment_status,
            PurchaseRequest.PaymentStatus.INVOICE_NOT_RECEIVED,
        )
        self.assertEqual(
            purchase_request.delivery_status, PurchaseRequest.DeliveryStatus.NOT_SHIPPED
        )
        self.assertEqual(purchase_request.request_date, timezone.localdate())
        self.assertEqual(purchase_request.item, self.item)

    def test_warehouse_admin_can_create_without_assigned_warehouse(self):
        self.admin.warehouse_accesses.all().delete()
        self.login(self.admin)

        response = self.client.post(reverse("purchase_request_create"), self.request_data())

        self.assertEqual(response.status_code, 302)
        self.assertEqual(PurchaseRequest.objects.get().requested_by, self.admin)

    def test_product_url_is_optional(self):
        self.login(self.requester)

        response = self.client.post(
            reverse("purchase_request_create"), self.request_data(product_url="")
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(PurchaseRequest.objects.get().product_url, "")

    def test_create_form_is_minimal_and_hides_tracking_and_audit_fields(self):
        self.login(self.requester)

        response = self.client.get(reverse("purchase_request_create"))

        fields = list(response.context["form"].fields)
        self.assertEqual(
            fields,
            [
                "requested_item",
                "requested_qty",
                "unit",
                "need_description",
                "product_url",
                "order_type",
            ],
        )
        for field in [
            "request_date",
            "title",
            "unit_price_uah",
            "approval_status",
            "payment_status",
            "delivery_status",
            "requested_by",
            "approved_by",
            "approved_at",
            "rejected_by",
            "rejected_at",
            "received_qty",
        ]:
            self.assertNotIn(field, response.context["form"].fields)
            self.assertNotContains(response, f'name="{field}"')
        self.assertNotContains(response, "<table", html=False)

    def test_new_requested_item_text_does_not_create_item(self):
        self.login(self.requester)
        item_count = Item.objects.count()

        response = self.client.post(
            reverse("purchase_request_create"),
            self.request_data(requested_item="Custom bearing", title="Ignored title"),
        )

        purchase_request = PurchaseRequest.objects.get(title="Custom bearing")
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(purchase_request.item)
        self.assertEqual(Item.objects.count(), item_count)

    def test_unit_price_is_optional_and_total_is_empty_without_it(self):
        self.login(self.requester)

        response = self.client.post(
            reverse("purchase_request_create"), self.request_data(unit_price_uah="")
        )

        purchase_request = PurchaseRequest.objects.get()
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(purchase_request.unit_price_uah)
        self.assertIsNone(purchase_request.total_price_uah)

    def test_total_price_is_quantity_times_unit_price(self):
        purchase_request = self.create_request(
            requested_qty="3.000", unit_price_uah="12.50"
        )

        self.assertEqual(purchase_request.total_price_uah, Decimal("37.50"))

    def test_requested_qty_is_required_and_positive(self):
        self.login(self.requester)
        url = reverse("purchase_request_create")

        missing = self.client.post(url, self.request_data(requested_qty=""))
        non_positive = self.client.post(url, self.request_data(requested_qty="0"))

        self.assertEqual(missing.status_code, 200)
        self.assertEqual(non_positive.status_code, 200)
        self.assertTrue(missing.context["form"].errors["requested_qty"])
        self.assertTrue(non_positive.context["form"].errors["requested_qty"])
        self.assertEqual(PurchaseRequest.objects.count(), 0)

    def test_admin_list_contains_all_requests_and_regular_list_only_own(self):
        own = self.create_request()
        other = self.create_request(user=self.other_requester, title="Other request")

        self.login(self.requester)
        regular_response = self.client.get(reverse("purchase_request_list"))
        self.assertContains(regular_response, own.title)
        self.assertNotContains(regular_response, other.title)

        self.login(self.admin)
        admin_response = self.client.get(reverse("purchase_request_list"))
        self.assertContains(admin_response, own.title)
        self.assertContains(admin_response, other.title)

    def test_list_shows_requester_name(self):
        self.requester.first_name = "Ivan"
        self.requester.last_name = "Petrenko"
        self.requester.save(update_fields=["first_name", "last_name"])
        self.create_request()
        self.login(self.admin)

        response = self.client.get(reverse("purchase_request_list"))

        self.assertContains(response, "Ivan Petrenko")

    def test_list_filters_by_tracking_fields_requester_date_and_search(self):
        matching = self.create_request(
            status=PurchaseRequest.Status.APPROVED,
            order_type=PurchaseRequest.OrderType.URGENT,
            approval_status=PurchaseRequest.ApprovalStatus.APPROVED,
            payment_status=PurchaseRequest.PaymentStatus.PAID,
            delivery_status=PurchaseRequest.DeliveryStatus.IN_TRANSIT,
            title="Matching purchase",
            product_url="https://example.com/target-product",
        )
        self.create_request(user=self.other_requester, title="Unrelated")
        self.login(self.admin)

        response = self.client.get(
            reverse("purchase_request_list"),
            {
                "order_type": PurchaseRequest.OrderType.URGENT,
                "approval_status": PurchaseRequest.ApprovalStatus.APPROVED,
                "payment_status": PurchaseRequest.PaymentStatus.PAID,
                "delivery_status": PurchaseRequest.DeliveryStatus.IN_TRANSIT,
                "requested_by": self.requester.pk,
                "date_from": matching.request_date.isoformat(),
                "date_to": matching.request_date.isoformat(),
                "q": "target-product",
            },
        )

        self.assertContains(response, matching.title)
        self.assertNotContains(response, "Unrelated")

    def test_each_tracking_status_filter_works(self):
        matching = self.create_request(
            title="Filter target",
            order_type=PurchaseRequest.OrderType.EMERGENCY,
            approval_status=PurchaseRequest.ApprovalStatus.APPROVED,
            payment_status=PurchaseRequest.PaymentStatus.SENT_FOR_PAYMENT,
            delivery_status=PurchaseRequest.DeliveryStatus.IN_TRANSIT,
        )
        other = self.create_request(user=self.other_requester, title="Filter other")
        self.login(self.admin)

        filters = {
            "order_type": matching.order_type,
            "approval_status": matching.approval_status,
            "payment_status": matching.payment_status,
            "delivery_status": matching.delivery_status,
        }
        for field, value in filters.items():
            with self.subTest(field=field):
                response = self.client.get(
                    reverse("purchase_request_list"), {field: value}
                )
                self.assertContains(response, matching.title)
                self.assertNotContains(response, other.title)

    def test_search_works_by_item_name_description_and_product_url(self):
        purchase_request = self.create_request(
            title="Hydraulic hose",
            need_description="Repair press line",
            product_url="https://example.com/hose-42",
        )
        self.login(self.admin)

        for query in ["Hydraulic", "press line", "hose-42"]:
            with self.subTest(query=query):
                response = self.client.get(reverse("purchase_request_list"), {"q": query})
                self.assertContains(response, purchase_request.title)

    def test_detail_page_is_visible_to_owner_and_admin_only(self):
        purchase_request = self.create_request()
        url = reverse("purchase_request_detail", args=[purchase_request.pk])

        self.login(self.requester)
        self.assertContains(self.client.get(url), purchase_request.title)
        self.login(self.admin)
        self.assertContains(self.client.get(url), purchase_request.title)
        self.login(self.other_requester)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_detail_page_shows_audit_fields(self):
        purchase_request = self.create_request(
            status=PurchaseRequest.Status.REJECTED,
            approved_by=self.admin,
            approved_at=timezone.now(),
            rejected_by=self.admin,
            rejected_at=timezone.now(),
            rejection_comment="Budget refused",
        )
        self.login(self.admin)

        response = self.client.get(
            reverse("purchase_request_detail", args=[purchase_request.pk])
        )

        self.assertContains(response, self.requester.username)
        self.assertContains(response, self.admin.username)
        self.assertContains(response, "Budget refused")

    def test_owner_can_edit_draft_but_not_submitted_request(self):
        draft = self.create_request()
        self.login(self.requester)

        response = self.client.post(
            reverse("purchase_request_update", args=[draft.pk]),
            self.request_data(title="Updated title"),
        )
        draft.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(draft.title, "Updated title")

        draft.status = PurchaseRequest.Status.PENDING_APPROVAL
        draft.save(update_fields=["status"])
        self.assertEqual(
            self.client.get(reverse("purchase_request_update", args=[draft.pk])).status_code,
            404,
        )

    def test_owner_can_send_draft_for_approval(self):
        purchase_request = self.create_request()

        response = self.post_action(purchase_request, "send", self.requester)

        purchase_request.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(purchase_request.status, PurchaseRequest.Status.PENDING_APPROVAL)

    def test_admin_can_approve_pending_request(self):
        purchase_request = self.create_request(status=PurchaseRequest.Status.PENDING_APPROVAL)

        self.post_action(purchase_request, "approve")

        purchase_request.refresh_from_db()
        self.assertEqual(purchase_request.status, PurchaseRequest.Status.APPROVED)
        self.assertEqual(
            purchase_request.approval_status,
            PurchaseRequest.ApprovalStatus.APPROVED,
        )
        self.assertEqual(purchase_request.approved_by, self.admin)
        self.assertIsNotNone(purchase_request.approved_at)

    def test_admin_can_reject_pending_request(self):
        purchase_request = self.create_request(status=PurchaseRequest.Status.PENDING_APPROVAL)

        self.login(self.admin)
        self.client.post(
            reverse("purchase_request_reject", args=[purchase_request.pk]),
            {"rejection_comment": "Too expensive"},
        )

        purchase_request.refresh_from_db()
        self.assertEqual(purchase_request.status, PurchaseRequest.Status.REJECTED)
        self.assertEqual(
            purchase_request.approval_status,
            PurchaseRequest.ApprovalStatus.REJECTED,
        )
        self.assertEqual(purchase_request.rejected_by, self.admin)
        self.assertIsNotNone(purchase_request.rejected_at)
        self.assertEqual(purchase_request.rejection_comment, "Too expensive")

    def test_admin_can_mark_approved_request_as_ordered(self):
        purchase_request = self.create_request(status=PurchaseRequest.Status.APPROVED)

        self.post_action(purchase_request, "order")

        purchase_request.refresh_from_db()
        self.assertEqual(purchase_request.status, PurchaseRequest.Status.ORDERED)

    def test_admin_can_cancel_request(self):
        purchase_request = self.create_request(status=PurchaseRequest.Status.ORDERED)

        self.post_action(purchase_request, "cancel")

        purchase_request.refresh_from_db()
        self.assertEqual(purchase_request.status, PurchaseRequest.Status.CANCELLED)

    def test_regular_user_cannot_approve_reject_order_or_cancel(self):
        transitions = [
            ("approve", PurchaseRequest.Status.PENDING_APPROVAL),
            ("reject", PurchaseRequest.Status.PENDING_APPROVAL),
            ("order", PurchaseRequest.Status.APPROVED),
            ("cancel", PurchaseRequest.Status.DRAFT),
        ]
        for action, status in transitions:
            with self.subTest(action=action):
                purchase_request = self.create_request(status=status)
                response = self.post_action(purchase_request, action, self.requester)
                purchase_request.refresh_from_db()
                self.assertEqual(response.status_code, 403)
                self.assertEqual(purchase_request.status, status)

    def test_user_without_warehouse_access_cannot_list_or_create(self):
        self.login(self.no_access_user)

        self.assertEqual(self.client.get(reverse("purchase_request_list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("purchase_request_create")).status_code, 403)

    def test_invalid_status_transition_is_rejected(self):
        purchase_request = self.create_request(status=PurchaseRequest.Status.DRAFT)

        response = self.post_action(purchase_request, "approve")

        purchase_request.refresh_from_db()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(purchase_request.status, PurchaseRequest.Status.DRAFT)

    def test_purchase_workflow_does_not_create_movements_or_balances(self):
        purchase_request = self.create_request()
        movement_count = StockMovement.objects.count()
        balance_count = StockBalance.objects.count()

        self.post_action(purchase_request, "send", self.requester)
        self.post_action(purchase_request, "approve")
        self.post_action(purchase_request, "order")

        self.assertEqual(StockMovement.objects.count(), movement_count)
        self.assertEqual(StockBalance.objects.count(), balance_count)

    def test_regular_user_cannot_manage_tracking_statuses(self):
        purchase_request = self.create_request()
        self.login(self.requester)
        data = self.request_data(
            approval_status=PurchaseRequest.ApprovalStatus.APPROVED,
            payment_status=PurchaseRequest.PaymentStatus.PAID,
            delivery_status=PurchaseRequest.DeliveryStatus.DELIVERED,
        )

        self.client.post(
            reverse("purchase_request_update", args=[purchase_request.pk]), data
        )

        purchase_request.refresh_from_db()
        self.assertEqual(
            purchase_request.approval_status, PurchaseRequest.ApprovalStatus.PENDING
        )
        self.assertEqual(
            purchase_request.payment_status,
            PurchaseRequest.PaymentStatus.INVOICE_NOT_RECEIVED,
        )
        self.assertEqual(
            purchase_request.delivery_status,
            PurchaseRequest.DeliveryStatus.NOT_SHIPPED,
        )

    def test_admin_can_update_payment_and_delivery_without_stock_effects(self):
        purchase_request = self.create_request()
        self.login(self.admin)
        movement_count = StockMovement.objects.count()
        balance_count = StockBalance.objects.count()

        response = self.client.post(
            reverse("purchase_request_update", args=[purchase_request.pk]),
            self.request_data(
                approval_status=PurchaseRequest.ApprovalStatus.PENDING,
                payment_status=PurchaseRequest.PaymentStatus.PAID,
                delivery_status=PurchaseRequest.DeliveryStatus.DELIVERED,
            ),
        )

        purchase_request.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            purchase_request.approval_status, PurchaseRequest.ApprovalStatus.PENDING
        )
        self.assertEqual(purchase_request.payment_status, PurchaseRequest.PaymentStatus.PAID)
        self.assertEqual(
            purchase_request.delivery_status, PurchaseRequest.DeliveryStatus.DELIVERED
        )
        self.assertEqual(StockMovement.objects.count(), movement_count)
        self.assertEqual(StockBalance.objects.count(), balance_count)

    def test_edit_page_cannot_update_approval_status_or_audit_fields(self):
        purchase_request = self.create_request(
            approved_by=self.requester,
            approved_at=timezone.now(),
            rejected_by=self.other_requester,
            rejected_at=timezone.now(),
            rejection_comment="Original rejection",
        )
        original_requested_by = purchase_request.requested_by
        original_approved_by = purchase_request.approved_by
        original_approved_at = purchase_request.approved_at
        original_rejected_by = purchase_request.rejected_by
        original_rejected_at = purchase_request.rejected_at
        self.login(self.admin)

        response = self.client.post(
            reverse("purchase_request_update", args=[purchase_request.pk]),
            self.request_data(
                requested_by=self.other_requester.pk,
                approval_status=PurchaseRequest.ApprovalStatus.APPROVED,
                payment_status=PurchaseRequest.PaymentStatus.INVOICE_NOT_RECEIVED,
                delivery_status=PurchaseRequest.DeliveryStatus.NOT_SHIPPED,
                approved_by=self.admin.pk,
                approved_at=timezone.now().isoformat(),
                rejected_by=self.admin.pk,
                rejected_at=timezone.now().isoformat(),
                rejection_comment="Tampered",
            ),
        )

        purchase_request.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            purchase_request.approval_status, PurchaseRequest.ApprovalStatus.PENDING
        )
        self.assertEqual(purchase_request.status, PurchaseRequest.Status.DRAFT)
        self.assertEqual(purchase_request.requested_by, original_requested_by)
        self.assertEqual(purchase_request.approved_by, original_approved_by)
        self.assertEqual(purchase_request.approved_at, original_approved_at)
        self.assertEqual(purchase_request.rejected_by, original_rejected_by)
        self.assertEqual(purchase_request.rejected_at, original_rejected_at)
        self.assertEqual(purchase_request.rejection_comment, "Original rejection")

    def test_sheet_fields_do_not_include_code_or_invoice_fields(self):
        self.login(self.requester)

        response = self.client.get(reverse("purchase_request_create"))

        fields = response.context["form"].fields
        self.assertNotIn("code", fields)
        self.assertNotIn("item_code", fields)
        self.assertNotIn("order_number", fields)
        self.assertNotIn("invoice_number", fields)

    def test_purchase_list_title_is_localized(self):
        expected_titles = {
            "uk": "Заявки на закупівлю",
            "ru": "Заявки на закупку",
            "en": "Purchase requests",
            "pl": "Wnioski zakupowe",
            "it": "Richieste di acquisto",
        }
        self.login(self.admin)

        for language, title in expected_titles.items():
            with self.subTest(language=language), translation.override(language):
                response = self.client.get(f"/{language}/purchases/")
                self.assertContains(response, title)
