import csv
import json

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.forms.models import model_to_dict
from django.db.models import Count, Q, Sum
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.html import format_html, linebreaks, urlize
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, FormView, ListView, TemplateView, UpdateView, View

from ..forms import (
    AnalyticsFilterForm,
    CategoryForm,
    ItemForm,
    InitialBalanceForm,
    InventoryCountCreateForm,
    InventoryCountLineForm,
    LabelTemplateForm,
    LocationForm,
    PrintLabelForm,
    PrinterForm,
    RecipientForm,
    StockBalanceFilterForm,
    StockIssueForm,
    StockMovementFilterForm,
    StockReceiveForm,
    StockTransferForm,
    StockWriteOffForm,
    UnitForm,
    WarehouseForm,
)
from ..models import (
    Category,
    InventoryCount,
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
from ..permissions import (
    ANALYTICS_GROUPS,
    MANAGEMENT_GROUPS,
    DIRECTORY_EDIT_GROUPS,
    PRINT_GROUPS,
    SETTINGS_GROUPS,
    STOCK_EDIT_GROUPS,
    STOCK_VIEW_GROUPS,
    USER_MANAGEMENT_GROUPS,
    GroupRequiredMixin,
    user_in_groups,
)
from ..services import analytics as analytics_service
from ..services.inventory import (
    InventoryServiceError,
    complete_inventory_count,
    create_inventory_count,
    update_inventory_line_actual_qty,
)
from ..services.labels import download_item_label_pdf, get_default_label_template, print_item_label
from ..services.stock import (
    InsufficientStockError,
    SameLocationTransferError,
    StockServiceError,
    create_initial_balance,
    issue_stock,
    receive_stock,
    transfer_stock,
    writeoff_stock,
)



class StockReceiveView(LoginRequiredMixin, GroupRequiredMixin, FormView):
    group_names = STOCK_EDIT_GROUPS
    template_name = "core/stock_receive_form.html"
    form_class = StockReceiveForm

    def get_initial(self):
        initial = super().get_initial()
        initial["occurred_at"] = timezone.localtime(timezone.now()).strftime("%Y-%m-%dT%H:%M")
        return initial

    def form_valid(self, form):
        try:
            movement = receive_stock(
                item=form.cleaned_data["item"],
                location=form.cleaned_data["location"],
                qty=form.cleaned_data["qty"],
                comment=form.cleaned_data["comment"],
                occurred_at=form.cleaned_data["occurred_at"],
            )
        except StockServiceError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        url = reverse("stock_receive_result", kwargs={"pk": movement.pk})
        if form.cleaned_data.get("print_label"):
            return redirect("item_label_print", pk=movement.item_id)
        return redirect(url)


class StockReceiveResultView(LoginRequiredMixin, GroupRequiredMixin, TemplateView):
    group_names = STOCK_EDIT_GROUPS
    template_name = "core/stock_receive_result.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["movement"] = get_object_or_404(
            StockMovement.objects.select_related(
                "item", "item__barcode", "destination_location", "destination_location__warehouse"
            ),
            pk=self.kwargs["pk"],
            movement_type=StockMovement.MovementType.IN,
        )
        return context


class StockIssueView(LoginRequiredMixin, GroupRequiredMixin, FormView):
    group_names = STOCK_EDIT_GROUPS
    template_name = "core/stock_issue_form.html"
    form_class = StockIssueForm

    def get_initial(self):
        initial = super().get_initial()
        initial["occurred_at"] = timezone.localtime(timezone.now()).strftime("%Y-%m-%dT%H:%M")
        return initial

    def form_valid(self, form):
        try:
            movement = issue_stock(
                item=form.cleaned_data["item"],
                location=form.cleaned_data["location"],
                qty=form.cleaned_data["qty"],
                recipient=form.cleaned_data["recipient"],
                issue_reason=form.cleaned_data["issue_reason"],
                department=form.cleaned_data["department"],
                document_number=form.cleaned_data["document_number"],
                comment=form.cleaned_data["comment"],
                occurred_at=form.cleaned_data["occurred_at"],
            )
        except InsufficientStockError:
            form.add_error(None, _("Недостатньо залишку для видачі."))
            return self.form_invalid(form)
        except StockServiceError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        return redirect("stock_issue_result", pk=movement.pk)


class StockIssueResultView(LoginRequiredMixin, GroupRequiredMixin, TemplateView):
    group_names = STOCK_EDIT_GROUPS
    template_name = "core/stock_issue_result.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        movement = get_object_or_404(
            StockMovement.objects.select_related(
                "item", "source_location", "source_location__warehouse", "recipient"
            ),
            pk=self.kwargs["pk"],
            movement_type=StockMovement.MovementType.OUT,
        )
        context["movement"] = movement
        context["balance_after"] = get_object_or_404(
            StockBalance, item=movement.item, location=movement.source_location
        ).qty
        return context


def _format_writeoff_comment(*, reason, document_number, comment):
    lines = [_("Причина списання: %(reason)s") % {"reason": reason}]
    if document_number:
        lines.append(_("Номер документа: %(document_number)s") % {"document_number": document_number})
    if comment:
        lines.append(_("Коментар: %(comment)s") % {"comment": comment})
    return "\n".join(lines)


class StockWriteOffView(LoginRequiredMixin, GroupRequiredMixin, FormView):
    group_names = STOCK_EDIT_GROUPS
    template_name = "core/stock_writeoff_form.html"
    form_class = StockWriteOffForm

    def get_initial(self):
        initial = super().get_initial()
        initial["occurred_at"] = timezone.localtime(timezone.now()).strftime("%Y-%m-%dT%H:%M")
        return initial

    def form_valid(self, form):
        reason = dict(form.fields["writeoff_reason"].choices).get(
            form.cleaned_data["writeoff_reason"], form.cleaned_data["writeoff_reason"]
        )
        comment = _format_writeoff_comment(
            reason=reason,
            document_number=form.cleaned_data["document_number"],
            comment=form.cleaned_data["comment"],
        )
        try:
            movement = writeoff_stock(
                item=form.cleaned_data["item"],
                location=form.cleaned_data["location"],
                qty=form.cleaned_data["qty"],
                comment=comment,
                occurred_at=form.cleaned_data["occurred_at"],
            )
        except InsufficientStockError:
            form.add_error(None, _("Недостатньо залишку для списання."))
            return self.form_invalid(form)
        except StockServiceError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        return redirect("stock_writeoff_result", pk=movement.pk)


class StockWriteOffResultView(LoginRequiredMixin, GroupRequiredMixin, TemplateView):
    group_names = STOCK_VIEW_GROUPS
    template_name = "core/stock_writeoff_result.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["movement"] = get_object_or_404(
            StockMovement.objects.select_related(
                "item", "source_location", "source_location__warehouse"
            ),
            pk=self.kwargs["pk"],
            movement_type=StockMovement.MovementType.WRITEOFF,
        )
        return context


class StockTransferView(LoginRequiredMixin, GroupRequiredMixin, FormView):
    group_names = STOCK_EDIT_GROUPS
    template_name = "core/stock_transfer_form.html"
    form_class = StockTransferForm

    def get_initial(self):
        initial = super().get_initial()
        initial["occurred_at"] = timezone.localtime(timezone.now()).strftime("%Y-%m-%dT%H:%M")
        return initial

    def form_valid(self, form):
        try:
            movement = transfer_stock(
                item=form.cleaned_data["item"],
                source_location=form.cleaned_data["source_location"],
                target_location=form.cleaned_data["destination_location"],
                qty=form.cleaned_data["qty"],
                comment=form.cleaned_data["comment"],
                occurred_at=form.cleaned_data["occurred_at"],
            )
        except InsufficientStockError:
            form.add_error(None, _("Недостатньо залишку для переміщення."))
            return self.form_invalid(form)
        except SameLocationTransferError:
            form.add_error(None, _("Неможливо перемістити товар у ту саму локацію."))
            return self.form_invalid(form)
        except StockServiceError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        return redirect("stock_transfer_result", pk=movement.pk)


class StockTransferResultView(LoginRequiredMixin, GroupRequiredMixin, TemplateView):
    group_names = STOCK_VIEW_GROUPS
    template_name = "core/stock_transfer_result.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["movement"] = get_object_or_404(
            StockMovement.objects.select_related(
                "item",
                "source_location",
                "source_location__warehouse",
                "destination_location",
                "destination_location__warehouse",
            ),
            pk=self.kwargs["pk"],
            movement_type=StockMovement.MovementType.TRANSFER,
        )
        return context


class InitialBalanceView(LoginRequiredMixin, GroupRequiredMixin, FormView):
    group_names = STOCK_EDIT_GROUPS
    template_name = "core/initial_balance_form.html"
    form_class = InitialBalanceForm

    def get_initial(self):
        initial = super().get_initial()
        initial["occurred_at"] = timezone.localtime(timezone.now()).strftime("%Y-%m-%dT%H:%M")
        return initial

    def form_valid(self, form):
        try:
            create_initial_balance(
                item=form.cleaned_data["item"],
                location=form.cleaned_data["location"],
                qty=form.cleaned_data["qty"],
                comment=form.cleaned_data["comment"],
                occurred_at=form.cleaned_data["occurred_at"],
            )
        except StockServiceError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, _("Початковий залишок збережено."))
        return redirect("movement_list")
