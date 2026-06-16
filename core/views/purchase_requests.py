from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View

from core.forms import (
    PurchaseRequestEditForm,
    PurchaseRequestFilterForm,
    PurchaseRequestForm,
    PurchaseRequestManagerForm,
)
from core.models import Item, PurchaseRequest, Unit
from core.permissions import (
    can_approve_purchase_requests,
    can_create_purchase_requests,
    can_manage_purchase_requests,
    can_update_purchase_request_tracking,
    can_view_purchase_requests,
    has_purchase_request_view_permission,
)
from core.services.exports.purchase_requests_excel import (
    build_purchase_requests_workbook,
)
from core.services.purchase_requests import can_receive_against_purchase_request
from core.services.warehouse_access import restrict_stock_movement_queryset_for_user


def purchase_requests_for_user(user):
    queryset = PurchaseRequest.objects.select_related(
        "requested_by", "approved_by", "rejected_by"
    )
    if can_manage_purchase_requests(user) or has_purchase_request_view_permission(user):
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
        filter_form = self.get_filter_form()
        active_filter_names = [
            name
            for name in filter_form.fields
            if self.request.GET.get(name) not in (None, "")
        ]
        context["filter_form"] = filter_form
        context["active_filter_names"] = active_filter_names
        context["can_create_purchase_request"] = can_create_purchase_requests(
            self.request.user
        )
        context["can_manage_purchase_requests"] = can_manage_purchase_requests(
            self.request.user
        )
        context["can_update_purchase_request_tracking"] = (
            can_update_purchase_request_tracking(self.request.user)
        )
        context["payment_status_choices"] = PurchaseRequest.PaymentStatus.choices
        context["delivery_status_choices"] = PurchaseRequest.DeliveryStatus.choices
        return context


class PurchaseRequestXLSXExportView(
    LoginRequiredMixin, PurchaseRequestAccessMixin, View
):
    def get(self, request, *args, **kwargs):
        list_view = PurchaseRequestListView()
        list_view.request = request
        purchase_requests = list(
            list_view.get_queryset().select_related(
                "requested_by", "approved_by", "rejected_by"
            )
        )
        try:
            workbook = build_purchase_requests_workbook(purchase_requests)
        except ImportError:
            return HttpResponse(_("XLSX export requires openpyxl."), status=503)

        response = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        filename = timezone.localdate().strftime("purchase_requests_%Y-%m-%d.xlsx")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        workbook.save(response)
        return response


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
        form.instance.request_date = timezone.localdate()
        form.instance.status = PurchaseRequest.Status.PENDING_APPROVAL
        form.instance.approval_status = PurchaseRequest.ApprovalStatus.PENDING
        form.instance.payment_status = PurchaseRequest.PaymentStatus.INVOICE_NOT_RECEIVED
        form.instance.delivery_status = PurchaseRequest.DeliveryStatus.NOT_SHIPPED
        response = super().form_valid(form)
        messages.success(self.request, _("Заявку на закупівлю створено."))
        return response

    def get_success_url(self):
        return reverse("purchase_request_detail", args=[self.object.pk])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("Нова заявка на закупівлю")
        context["purchase_item_options"] = Item.objects.filter(is_active=True).order_by(
            "name"
        )
        context["purchase_unit_options"] = Unit.objects.filter(is_active=True).order_by(
            "name"
        )
        context["is_create"] = True
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
        context["can_approve_purchase_request"] = can_approve_purchase_requests(
            self.request.user
        )
        context["can_update_purchase_request_tracking"] = (
            can_update_purchase_request_tracking(self.request.user)
        )
        context["payment_status_choices"] = PurchaseRequest.PaymentStatus.choices
        context["delivery_status_choices"] = PurchaseRequest.DeliveryStatus.choices
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
        if can_update_purchase_request_tracking(self.request.user):
            return PurchaseRequestManagerForm
        return PurchaseRequestEditForm

    def get_queryset(self):
        queryset = purchase_requests_for_user(self.request.user)
        if can_update_purchase_request_tracking(self.request.user):
            return queryset
        return queryset.filter(status=PurchaseRequest.Status.DRAFT)

    def get_success_url(self):
        return reverse("purchase_request_detail", args=[self.object.pk])

    def form_valid(self, form):
        # Requester and approval audit fields are not part of normal edit forms.
        # They are assigned only on create and approve/reject actions.
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
        if self.action in {"approve", "reject"} and not can_approve_purchase_requests(
            request.user
        ):
            raise PermissionDenied(_("У вас немає прав погоджувати заявки."))
        if (
            self.action in {"order", "cancel"}
            and transition.get("admin")
            and not can_manage_purchase_requests(request.user)
        ):
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
                purchase_request.rejection_comment = request.POST.get(
                    "rejection_comment", ""
                ).strip()
                update_fields += [
                    "approval_status",
                    "rejected_by",
                    "rejected_at",
                    "rejection_comment",
                ]
            purchase_request.save(update_fields=update_fields)

        messages.success(request, transition["message"])
        return redirect("purchase_request_detail", pk=purchase_request.pk)


class PurchaseRequestTrackingStatusUpdateView(
    LoginRequiredMixin, PurchaseRequestAccessMixin, View
):
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        if not can_update_purchase_request_tracking(request.user):
            raise PermissionDenied(_("У вас немає прав змінювати оплату та доставку."))

        purchase_request = get_object_or_404(
            purchase_requests_for_user(request.user), pk=kwargs["pk"]
        )
        update_fields = []
        payment_status = request.POST.get("payment_status")
        delivery_status = request.POST.get("delivery_status")

        if payment_status:
            valid_payment_statuses = {
                value for value, _label in PurchaseRequest.PaymentStatus.choices
            }
            if payment_status not in valid_payment_statuses:
                return HttpResponseBadRequest(_("Недоступний статус оплати."))
            purchase_request.payment_status = payment_status
            update_fields.append("payment_status")

        if delivery_status:
            valid_delivery_statuses = {
                value for value, _label in PurchaseRequest.DeliveryStatus.choices
            }
            if delivery_status not in valid_delivery_statuses:
                return HttpResponseBadRequest(_("Недоступний статус доставки."))
            purchase_request.delivery_status = delivery_status
            update_fields.append("delivery_status")

        if not update_fields:
            return HttpResponseBadRequest(_("Не вибрано статус для оновлення."))

        purchase_request.save(update_fields=[*update_fields, "updated_at"])
        messages.success(request, _("Статус заявки оновлено."))
        next_url = request.POST.get("next")
        if next_url and next_url.startswith("/") and not next_url.startswith("//"):
            return redirect(next_url)
        return redirect("purchase_request_detail", pk=purchase_request.pk)
