from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from django.utils import translation

from core.models import PurchaseRequest, StockBalance, StockMovement, Warehouse
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
        grant_warehouse_access(self.admin, self.warehouse, can_delegate=True)
        grant_warehouse_access(self.requester, self.warehouse)
        grant_warehouse_access(self.other_requester, self.warehouse)

    def request_data(self, **overrides):
        data = {
            "title": "Safety gloves",
            "description": "Planned purchase",
            "requested_qty": "12.000",
            "unit": "pairs",
            "estimated_unit_price": "55.50",
            "currency": "UAH",
            "supplier_name": "Safety supplier",
            "supplier_url": "",
            "comment": "Needed next month",
        }
        data.update(overrides)
        return data

    def create_request(self, user=None, status=PurchaseRequest.Status.DRAFT, **overrides):
        return PurchaseRequest.objects.create(
            requested_by=user or self.requester,
            status=status,
            **self.request_data(**overrides),
        )

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
        self.assertEqual(purchase_request.status, PurchaseRequest.Status.DRAFT)

    def test_warehouse_admin_can_create_without_assigned_warehouse(self):
        self.admin.warehouse_accesses.all().delete()
        self.login(self.admin)

        response = self.client.post(reverse("purchase_request_create"), self.request_data())

        self.assertEqual(response.status_code, 302)
        self.assertEqual(PurchaseRequest.objects.get().requested_by, self.admin)

    def test_supplier_url_is_optional(self):
        self.login(self.requester)

        response = self.client.post(
            reverse("purchase_request_create"), self.request_data(supplier_url="")
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(PurchaseRequest.objects.get().supplier_url, "")

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

    def test_list_filters_by_status_requester_date_and_search(self):
        matching = self.create_request(
            status=PurchaseRequest.Status.APPROVED,
            title="Matching purchase",
            supplier_name="Target supplier",
        )
        self.create_request(user=self.other_requester, title="Unrelated")
        self.login(self.admin)

        response = self.client.get(
            reverse("purchase_request_list"),
            {
                "status": PurchaseRequest.Status.APPROVED,
                "requested_by": self.requester.pk,
                "date_from": matching.created_at.date().isoformat(),
                "date_to": matching.created_at.date().isoformat(),
                "q": "Target supplier",
            },
        )

        self.assertContains(response, matching.title)
        self.assertNotContains(response, "Unrelated")

    def test_detail_page_is_visible_to_owner_and_admin_only(self):
        purchase_request = self.create_request()
        url = reverse("purchase_request_detail", args=[purchase_request.pk])

        self.login(self.requester)
        self.assertContains(self.client.get(url), purchase_request.title)
        self.login(self.admin)
        self.assertContains(self.client.get(url), purchase_request.title)
        self.login(self.other_requester)
        self.assertEqual(self.client.get(url).status_code, 404)

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
        self.assertEqual(purchase_request.approved_by, self.admin)
        self.assertIsNotNone(purchase_request.approved_at)

    def test_admin_can_reject_pending_request(self):
        purchase_request = self.create_request(status=PurchaseRequest.Status.PENDING_APPROVAL)

        self.post_action(purchase_request, "reject")

        purchase_request.refresh_from_db()
        self.assertEqual(purchase_request.status, PurchaseRequest.Status.REJECTED)
        self.assertEqual(purchase_request.rejected_by, self.admin)
        self.assertIsNotNone(purchase_request.rejected_at)

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

    def test_purchase_list_title_is_localized(self):
        expected_titles = {
            "uk": "Закупки",
            "ru": "Закупки",
            "en": "Purchases",
            "pl": "Zakupy",
            "it": "Acquisti",
        }
        self.login(self.admin)

        for language, title in expected_titles.items():
            with self.subTest(language=language), translation.override(language):
                response = self.client.get(f"/{language}/purchases/")
                self.assertContains(response, title)
