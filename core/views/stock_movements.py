from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import gettext_lazy as _
from django.views.generic import FormView, ListView, TemplateView

from ..forms import StockMovementCancellationForm, StockMovementFilterForm
from ..models import StockBalance, StockMovement
from ..permissions import (
    STOCK_EDIT_GROUPS,
    STOCK_VIEW_GROUPS,
    GroupRequiredMixin,
    can_cancel_movement,
)
from ..services.filter_memory import apply_remembered_filters, build_redirect_url, querydict_from_params
from ..services.stock import StockServiceError
from ..services.stock_cancellation import cancel_stock_movement
from ..services.warehouse_access import restrict_stock_movement_queryset_for_user
from .stock_operations import SelfServiceShellContextMixin


class StockMovementListView(LoginRequiredMixin, GroupRequiredMixin, ListView):
    group_names = STOCK_VIEW_GROUPS
    model = StockMovement
    template_name = "core/stockmovement_list.html"
    context_object_name = "movements"
    paginate_by = 50
    page_key = "movement_list"

    def get(self, request, *args, **kwargs):
        params, used_remembered_filters, should_redirect = apply_remembered_filters(request, self.page_key)
        self.used_remembered_filters = used_remembered_filters
        if should_redirect:
            return redirect(build_redirect_url(request.path, params))
        self.effective_get = querydict_from_params(params) if params else request.GET
        return super().get(request, *args, **kwargs)

    def get_filter_form(self):
        return StockMovementFilterForm(
            getattr(self, "effective_get", self.request.GET) or None,
            request_user=self.request.user,
        )

    def get_queryset(self):
        queryset = restrict_stock_movement_queryset_for_user(
            self.request.user,
            StockMovement.objects.select_related(
                "item",
                "item__barcode",
                "source_location",
                "source_warehouse",
                "source_location__warehouse",
                "destination_location",
                "destination_warehouse",
                "destination_location__warehouse",
                "recipient",
                "inventory_count",
                "performed_by",
                "cancelled_by",
                "reversal_of",
            ),
        )
        form = self.get_filter_form()
        if not form.is_valid():
            return queryset
        cd = form.cleaned_data
        if cd.get("movement_type"):
            queryset = queryset.filter(movement_type=cd["movement_type"])
        if cd.get("item"):
            queryset = queryset.filter(item=cd["item"])
        if cd.get("item_id"):
            queryset = queryset.filter(item_id=cd["item_id"])
        if cd.get("recipient"):
            queryset = queryset.filter(recipient=cd["recipient"])
        if cd.get("recipient_id"):
            queryset = queryset.filter(recipient_id=cd["recipient_id"])
        if cd.get("warehouse"):
            queryset = queryset.filter(
                Q(source_warehouse=cd["warehouse"]) | Q(destination_warehouse=cd["warehouse"]) | Q(source_location__warehouse=cd["warehouse"]) | Q(destination_location__warehouse=cd["warehouse"])
            )
        if cd.get("location"):
            queryset = queryset.filter(
                Q(source_location=cd["location"]) | Q(destination_location=cd["location"])
            )
        if cd.get("date_from"):
            queryset = queryset.filter(occurred_at__date__gte=cd["date_from"])
        if cd.get("date_to"):
            queryset = queryset.filter(occurred_at__date__lte=cd["date_to"])
        if cd.get("issue_reason"):
            queryset = queryset.filter(issue_reason=cd["issue_reason"])
        if cd.get("department"):
            queryset = queryset.filter(department__icontains=cd["department"])
        if cd.get("usage_place_id"):
            queryset = queryset.filter(department__iexact=cd["usage_place_id"])
        if cd.get("document_number"):
            queryset = queryset.filter(document_number__icontains=cd["document_number"])
        if cd.get("no_document"):
            queryset = queryset.filter(Q(document_number__isnull=True) | Q(document_number=""))
        if cd.get("missing_recipient"):
            queryset = queryset.filter(recipient__isnull=True)
        if cd.get("missing_usage_place"):
            queryset = queryset.filter(Q(department__isnull=True) | Q(department=""))
        if cd.get("missing_destination"):
            queryset = queryset.filter(destination_location__isnull=True)
        if cd.get("invalid_qty"):
            queryset = queryset.filter(qty__lte=0)
        if cd.get("q"):
            q = cd["q"]
            queryset = queryset.filter(
                Q(item__name__icontains=q) | Q(item__internal_code__icontains=q) | Q(item__barcode__barcode__icontains=q)
            )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.get_filter_form()
        context["used_remembered_filters"] = getattr(self, "used_remembered_filters", False)
        return context


class StockReceiveResultView(
    LoginRequiredMixin, SelfServiceShellContextMixin, GroupRequiredMixin, TemplateView
):
    group_names = STOCK_EDIT_GROUPS
    template_name = "core/stock_receive_result.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["movement"] = get_object_or_404(
            restrict_stock_movement_queryset_for_user(
                self.request.user,
                StockMovement.objects.select_related(
                    "item",
                    "item__barcode",
                    "destination_location",
                    "destination_warehouse",
                "destination_location__warehouse",
                    "recipient",
                    "performed_by",
                    "cancelled_by",
                    "reversal_of",
                ),
            ),
            pk=self.kwargs["pk"],
            movement_type__in=[StockMovement.MovementType.IN, StockMovement.MovementType.RETURN],
        )
        return context


class StockMovementCancelView(LoginRequiredMixin, FormView):
    template_name = "core/stock_movement_cancel.html"
    form_class = StockMovementCancellationForm

    def dispatch(self, request, *args, **kwargs):
        self.movement = get_object_or_404(
            StockMovement.objects.select_related(
                "item",
                "source_location",
                "source_warehouse",
                "source_location__warehouse",
                "destination_location",
                "destination_warehouse",
                "destination_location__warehouse",
                "recipient",
                "performed_by",
                "cancelled_by",
            ),
            pk=kwargs["pk"],
        )
        if not can_cancel_movement(request.user, self.movement):
            raise PermissionDenied(_("У вас немає прав для перегляду цієї сторінки."))
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["movement"] = self.movement
        return context

    def form_valid(self, form):
        try:
            cancellation_movement = cancel_stock_movement(
                movement=self.movement,
                cancelled_by=self.request.user,
                reason=form.cleaned_data["reason"],
                request=self.request,
            )
        except StockServiceError as exc:
            message = str(exc)
            messages.error(self.request, message)
            form.add_error(None, message)
            return self.form_invalid(form)
        messages.success(self.request, _("Рух анульовано."))
        return redirect("stock_movement_print", pk=cancellation_movement.pk)


class StockMovementPrintView(
    LoginRequiredMixin, SelfServiceShellContextMixin, GroupRequiredMixin, TemplateView
):
    group_names = STOCK_VIEW_GROUPS
    template_name = "core/stock_movement_print.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        movement = get_object_or_404(
            restrict_stock_movement_queryset_for_user(
                self.request.user,
                StockMovement.objects.select_related(
                    "item",
                    "item__barcode",
                    "source_location",
                    "source_warehouse",
                "source_location__warehouse",
                    "destination_location",
                    "destination_warehouse",
                "destination_location__warehouse",
                    "recipient",
                    "performed_by",
                    "cancelled_by",
                    "reversal_of",
                ),
            ),
            pk=self.kwargs["pk"],
        )
        location = movement.source_location or movement.destination_location
        is_self_service_movement = movement.movement_type in {
            StockMovement.MovementType.OUT,
            StockMovement.MovementType.RETURN,
        }
        if movement.movement_type == StockMovement.MovementType.OUT:
            operation_type = _("Видача товару")
            responsible_label = _("Хто взяв товар")
        elif movement.movement_type == StockMovement.MovementType.RETURN:
            operation_type = _("Повернення товару")
            responsible_label = _("Хто повернув товар")
        elif movement.movement_type == StockMovement.MovementType.IN:
            operation_type = _("Прихід товару")
            responsible_label = _("Отримувач / відповідальний")
        else:
            operation_type = movement.get_movement_type_display()
            responsible_label = _("Отримувач / відповідальний")
        labels = {
            "title": _("Контрольний талон складської операції"),
            "print": _("Друк"),
            "back": _("Назад"),
            "operation_id": _("ID операції"),
            "operation_type": _("Тип операції"),
            "occurred_at": _("Дата і час операції"),
            "item": _("Товар"),
            "internal_code": _("Внутрішній код"),
            "barcode": _("Штрихкод"),
            "qty": _("Кількість"),
            "warehouse": _("Склад"),
            "location": _("Локація"),
            "responsible": responsible_label,
            "department": _("Цех / місце використання"),
            "comment_document": _("Коментар / документ"),
            "video_time": _("Час для перевірки по відео:"),
        }
        context.update(
            {
                "labels": labels,
                "movement": movement,
                "operation_type": operation_type,
                "location": location,
                "warehouse": movement.resolved_source_warehouse or movement.resolved_destination_warehouse,
                "is_self_service_movement": is_self_service_movement,
            }
        )
        return context


class StockIssueResultView(
    LoginRequiredMixin, SelfServiceShellContextMixin, GroupRequiredMixin, TemplateView
):
    group_names = STOCK_EDIT_GROUPS
    template_name = "core/stock_issue_result.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        movement = get_object_or_404(
            restrict_stock_movement_queryset_for_user(
                self.request.user,
                StockMovement.objects.select_related(
                    "item",
                    "source_location",
                    "source_warehouse",
                "source_location__warehouse",
                    "recipient",
                    "performed_by",
                    "cancelled_by",
                    "reversal_of",
                ),
            ),
            pk=self.kwargs["pk"],
            movement_type=StockMovement.MovementType.OUT,
        )
        context["movement"] = movement
        context["balance_after"] = get_object_or_404(
            StockBalance, item=movement.item, warehouse=movement.resolved_source_warehouse, is_active=True
        ).qty
        return context


class StockWriteOffResultView(LoginRequiredMixin, GroupRequiredMixin, TemplateView):
    group_names = STOCK_VIEW_GROUPS
    template_name = "core/stock_writeoff_result.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["movement"] = get_object_or_404(
            restrict_stock_movement_queryset_for_user(
                self.request.user,
                StockMovement.objects.select_related(
                    "item", "source_location", "source_warehouse",
                "source_location__warehouse", "performed_by"
                ),
            ),
            pk=self.kwargs["pk"],
            movement_type=StockMovement.MovementType.WRITEOFF,
        )
        return context


class StockTransferResultView(LoginRequiredMixin, GroupRequiredMixin, TemplateView):
    group_names = STOCK_VIEW_GROUPS
    template_name = "core/stock_transfer_result.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["movement"] = get_object_or_404(
            restrict_stock_movement_queryset_for_user(
                self.request.user,
                StockMovement.objects.select_related(
                    "item",
                    "source_location",
                    "source_warehouse",
                "source_location__warehouse",
                    "destination_location",
                    "destination_warehouse",
                "destination_location__warehouse",
                    "performed_by",
                    "cancelled_by",
                    "reversal_of",
                ),
            ),
            pk=self.kwargs["pk"],
            movement_type=StockMovement.MovementType.TRANSFER,
        )
        return context
