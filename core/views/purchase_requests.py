from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View

from core.forms import (
    PurchaseRequestFilterForm,
    PurchaseRequestForm,
    PurchaseRequestManagerForm,
)
from core.models import PurchaseRequest
from core.permissions import (
    can_create_purchase_requests,
    can_manage_purchase_requests,
    can_view_purchase_requests,
)
from core.services.purchase_requests import can_receive_against_purchase_request
from core.services.warehouse_access import restrict_stock_movement_queryset_for_user


def purchase_requests_for_user(user):
    queryset = PurchaseRequest.objects.select_related(
        "requested_by", "approved_by", "rejected_by"
    )
    if can_manage_purchase_requests(user):
        return queryset
    return queryset.filter(requested_by=user)


class PurchaseRequestAccessMixin(UserPassesTestMixin):
    permission_denied_message = _("У вас немає прав для перегляду цієї сторінки.")

    def test_func(self):
        return can_view_purchase_requests(self.request.user)

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            raise PermissionDenied(self.get_permission_denied_message())
        return super().handle_no_permission()


class PurchaseRequestListView(LoginRequiredMixin, PurchaseRequestAccessMixin, ListView):
    model = PurchaseRequest
    template_name = "core/purchase_requests/list.html"
    context_object_name = "purchase_requests"
    paginate_by = 40

    def get_filter_form(self):
        users = get_user_model().objects.filter(
            purchase_requests__in=purchase_requests_for_user(self.request.user)
        ).distinct().order_by("last_name", "first_name", "username")
        return PurchaseRequestFilterForm(self.request.GET or None, users=users)

    def get_queryset(self):
        queryset = purchase_requests_for_user(self.request.user)
        form = self.get_filter_form()
        if not form.is_valid():
            return queryset
        filters = form.cleaned_data
        if filters.get("order_type"):
            queryset = queryset.filter(order_type=filters["order_type"])
        if filters.get("approval_status"):
            queryset = queryset.filter(approval_status=filters["approval_status"])
        if filters.get("payment_status"):
            queryset = queryset.filter(payment_status=filters["payment_status"])
        if filters.get("delivery_status"):
            queryset = queryset.filter(delivery_status=filters["delivery_status"])
        if filters.get("requested_by"):
            queryset = queryset.filter(requested_by=filters["requested_by"])
        if filters.get("date_from"):
            queryset = queryset.filter(request_date__gte=filters["date_from"])
        if filters.get("date_to"):
            queryset = queryset.filter(request_date__lte=filters["date_to"])
        if filters.get("q"):
            query = filters["q"]
            queryset = queryset.filter(
                Q(title__icontains=query)
                | Q(need_description__icontains=query)
                | Q(product_url__icontains=query)
            )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.get_filter_form()
        context["can_create_purchase_request"] = can_create_purchase_requests(
            self.request.user
        )
        return context


class PurchaseRequestCreateView(LoginRequiredMixin, UserPassesTestMixin, CreateView):
    model = PurchaseRequest
    form_class = PurchaseRequestForm
    template_name = "core/purchase_requests/form.html"

    def test_func(self):
        return can_create_purchase_requests(self.request.user)

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            raise PermissionDenied(_("У вас немає прав для створення заявки на закупівлю."))
        return super().handle_no_permission()

    def form_valid(self, form):
        form.instance.requested_by = self.request.user
        response = super().form_valid(form)
        messages.success(self.request, _("Заявку на закупівлю створено."))
        return response

    def get_success_url(self):
        return reverse("purchase_request_detail", args=[self.object.pk])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("Нова заявка на закупівлю")
        return context


class PurchaseRequestDetailView(
    LoginRequiredMixin, PurchaseRequestAccessMixin, DetailView
):
    model = PurchaseRequest
    template_name = "core/purchase_requests/detail.html"
    context_object_name = "purchase_request"

    def get_queryset(self):
        return purchase_requests_for_user(self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        purchase_request = self.object
        context["can_edit"] = (
            purchase_request.status == PurchaseRequest.Status.DRAFT
            or can_manage_purchase_requests(self.request.user)
        )
        context["can_send"] = purchase_request.status == PurchaseRequest.Status.DRAFT
        context["can_manage"] = can_manage_purchase_requests(self.request.user)
        context["can_receive"] = can_receive_against_purchase_request(
            self.request.user, purchase_request
        )
        context["linked_receive_movements"] = (
            restrict_stock_movement_queryset_for_user(
                self.request.user,
                purchase_request.linked_receive_movements.filter(
                    movement_type="in",
                    is_cancelled=False,
                    reversal_of__isnull=True,
                ),
            )
            .select_related(
                "item",
                "destination_warehouse",
                "destination_location",
                "performed_by",
            )
            .order_by("-occurred_at", "-id")
        )
        return context


class PurchaseRequestUpdateView(
    LoginRequiredMixin, PurchaseRequestAccessMixin, UpdateView
):
    model = PurchaseRequest
    template_name = "core/purchase_requests/form.html"

    def get_form_class(self):
        if can_manage_purchase_requests(self.request.user):
            return PurchaseRequestManagerForm
        return PurchaseRequestForm

    def get_queryset(self):
        queryset = purchase_requests_for_user(self.request.user)
        if can_manage_purchase_requests(self.request.user):
            return queryset
        return queryset.filter(status=PurchaseRequest.Status.DRAFT)

    def get_success_url(self):
        return reverse("purchase_request_detail", args=[self.object.pk])

    def form_valid(self, form):
        purchase_request = form.instance
        if can_manage_purchase_requests(self.request.user):
            if purchase_request.approval_status == PurchaseRequest.ApprovalStatus.APPROVED:
                if purchase_request.approved_by_id is None:
                    purchase_request.approved_by = self.request.user
                    purchase_request.approved_at = timezone.now()
                if purchase_request.status in {
                    PurchaseRequest.Status.DRAFT,
                    PurchaseRequest.Status.PENDING_APPROVAL,
                    PurchaseRequest.Status.REJECTED,
                }:
                    purchase_request.status = PurchaseRequest.Status.APPROVED
            elif purchase_request.approval_status == PurchaseRequest.ApprovalStatus.REJECTED:
                if purchase_request.rejected_by_id is None:
                    purchase_request.rejected_by = self.request.user
                    purchase_request.rejected_at = timezone.now()
                if purchase_request.status not in {
                    PurchaseRequest.Status.PARTIALLY_RECEIVED,
                    PurchaseRequest.Status.RECEIVED,
                }:
                    purchase_request.status = PurchaseRequest.Status.REJECTED
            elif purchase_request.status in {
                PurchaseRequest.Status.APPROVED,
                PurchaseRequest.Status.ORDERED,
                PurchaseRequest.Status.REJECTED,
            }:
                purchase_request.status = PurchaseRequest.Status.PENDING_APPROVAL
        messages.success(self.request, _("Заявку на закупівлю оновлено."))
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("Редагувати заявку на закупівлю")
        return context


class PurchaseRequestStatusActionView(
    LoginRequiredMixin, PurchaseRequestAccessMixin, View
):
    http_method_names = ["post"]
    action = None
    transitions = {
        "send": {
            "from": {PurchaseRequest.Status.DRAFT},
            "to": PurchaseRequest.Status.PENDING_APPROVAL,
            "message": _("Заявку надіслано на погодження."),
        },
        "approve": {
            "from": {PurchaseRequest.Status.PENDING_APPROVAL},
            "to": PurchaseRequest.Status.APPROVED,
            "message": _("Заявку погоджено."),
            "admin": True,
        },
        "reject": {
            "from": {PurchaseRequest.Status.PENDING_APPROVAL},
            "to": PurchaseRequest.Status.REJECTED,
            "message": _("Заявку відхилено."),
            "admin": True,
        },
        "order": {
            "from": {PurchaseRequest.Status.APPROVED},
            "to": PurchaseRequest.Status.ORDERED,
            "message": _("Заявку позначено як замовлену."),
            "admin": True,
        },
        "cancel": {
            "from": {
                PurchaseRequest.Status.DRAFT,
                PurchaseRequest.Status.PENDING_APPROVAL,
                PurchaseRequest.Status.APPROVED,
                PurchaseRequest.Status.REJECTED,
                PurchaseRequest.Status.ORDERED,
                PurchaseRequest.Status.PARTIALLY_RECEIVED,
                PurchaseRequest.Status.RECEIVED,
            },
            "to": PurchaseRequest.Status.CANCELLED,
            "message": _("Заявку скасовано."),
            "admin": True,
        },
    }

    def post(self, request, *args, **kwargs):
        transition = self.transitions.get(self.action)
        if transition is None:
            return HttpResponseBadRequest()
        if transition.get("admin") and not can_manage_purchase_requests(request.user):
            raise PermissionDenied(_("Лише адміністратор може змінити цей статус."))

        with transaction.atomic():
            queryset = purchase_requests_for_user(request.user).select_for_update()
            purchase_request = get_object_or_404(queryset, pk=kwargs["pk"])
            if purchase_request.status not in transition["from"]:
                return HttpResponseBadRequest(_("Недоступний перехід статусу."))

            now = timezone.now()
            purchase_request.status = transition["to"]
            update_fields = ["status", "updated_at"]
            if self.action == "approve":
                purchase_request.approval_status = PurchaseRequest.ApprovalStatus.APPROVED
                purchase_request.approved_by = request.user
                purchase_request.approved_at = now
                update_fields += ["approval_status", "approved_by", "approved_at"]
            elif self.action == "reject":
                purchase_request.approval_status = PurchaseRequest.ApprovalStatus.REJECTED
                purchase_request.rejected_by = request.user
                purchase_request.rejected_at = now
                update_fields += ["approval_status", "rejected_by", "rejected_at"]
            purchase_request.save(update_fields=update_fields)

        messages.success(request, transition["message"])
        return redirect("purchase_request_detail", pk=purchase_request.pk)
