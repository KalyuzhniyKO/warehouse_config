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
from django.utils.translation import get_language, gettext_lazy as _
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
from ..services.items import find_item_by_barcode
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
    find_best_stock_balance_for_issue,
    issue_stock,
    receive_stock,
    transfer_stock,
    writeoff_stock,
)



def stock_operation_barcode_context(item):
    if item is None:
        return None
    available_qty = (
        StockBalance.objects.filter(item=item, is_active=True).aggregate(total=Sum("qty"))["total"]
        or 0
    )
    return {"item": item, "available_qty": available_qty}


class BarcodePrefillMixin:
    barcode_param = "barcode"
    barcode_not_found_message = _("Товар за цим штрихкодом не знайдено.")

    def dispatch(self, request, *args, **kwargs):
        self.scanned_barcode = request.GET.get(self.barcode_param, "").strip()
        self.scanned_item = None
        if request.method == "GET" and self.scanned_barcode:
            self.scanned_item = find_item_by_barcode(self.scanned_barcode)
            if self.scanned_item is None:
                messages.warning(request, self.barcode_not_found_message)
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        if self.scanned_item is not None:
            initial["item"] = self.scanned_item
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["barcode_query"] = self.scanned_barcode
        context["scanned_item"] = self.scanned_item
        context["scanned_item_context"] = stock_operation_barcode_context(self.scanned_item)
        return context


class StockReceiveView(LoginRequiredMixin, GroupRequiredMixin, BarcodePrefillMixin, FormView):
    group_names = STOCK_EDIT_GROUPS
    template_name = "core/stock_receive_form.html"
    form_class = StockReceiveForm

    def get_initial(self):
        initial = super().get_initial()
        initial["occurred_at"] = timezone.localtime(timezone.now()).strftime(
            "%Y-%m-%dT%H:%M"
        )
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
            message = str(exc)
            messages.error(self.request, message)
            form.add_error(None, message)
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


class StockIssueView(LoginRequiredMixin, GroupRequiredMixin, BarcodePrefillMixin, FormView):
    group_names = STOCK_EDIT_GROUPS
    template_name = "core/stock_issue_form.html"
    form_class = StockIssueForm
    auto_selected_message = _("Склад і локацію визначено автоматично.")
    no_available_stock_message = _(
        "Товар знайдено, але доступного залишку для видачі немає."
    )

    def get_best_stock_balance(self):
        if not hasattr(self, "best_stock_balance"):
            self.best_stock_balance = find_best_stock_balance_for_issue(
                self.scanned_item
            )
        return self.best_stock_balance

    def get_initial(self):
        initial = super().get_initial()
        initial["occurred_at"] = timezone.localtime(timezone.now()).strftime(
            "%Y-%m-%dT%H:%M"
        )
        initial["issue_reason"] = StockMovement.IssueReason.OTHER
        initial["document_number"] = ""
        initial["comment"] = ""
        best_balance = self.get_best_stock_balance()
        if best_balance is not None:
            initial["warehouse"] = best_balance.location.warehouse
            initial["location"] = best_balance.location
        return initial

    def get(self, request, *args, **kwargs):
        if self.scanned_item is not None:
            if self.get_best_stock_balance() is not None:
                messages.success(request, self.auto_selected_message)
            else:
                messages.warning(request, self.no_available_stock_message)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["best_stock_balance"] = self.get_best_stock_balance()
        context["show_issue_form"] = (
            self.request.method == "POST"
            or (
                self.scanned_item is not None
                and self.get_best_stock_balance() is not None
            )
        )
        return context

    def form_valid(self, form):
        try:
            movement = issue_stock(
                item=form.cleaned_data["item"],
                location=form.cleaned_data["location"],
                qty=form.cleaned_data["qty"],
                recipient=form.cleaned_data["recipient"],
                issue_reason=(
                    form.cleaned_data["issue_reason"] or StockMovement.IssueReason.OTHER
                ),
                department=form.cleaned_data["department"],
                document_number=form.cleaned_data["document_number"],
                comment=form.cleaned_data["comment"],
                occurred_at=form.cleaned_data["occurred_at"],
            )
        except InsufficientStockError:
            message = _(
                "Недостатньо залишку для видачі. Перевірте залишки перед видачею."
            )
            messages.error(self.request, message)
            form.add_error(None, message)
            return self.form_invalid(form)
        except StockServiceError as exc:
            message = str(exc)
            messages.error(self.request, message)
            form.add_error(None, message)
            return self.form_invalid(form)
        return redirect("stock_issue_result", pk=movement.pk)


class StockMovementPrintView(LoginRequiredMixin, GroupRequiredMixin, TemplateView):
    group_names = STOCK_VIEW_GROUPS
    template_name = "core/stock_movement_print.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        movement = get_object_or_404(
            StockMovement.objects.select_related(
                "item",
                "item__barcode",
                "source_location",
                "source_location__warehouse",
                "destination_location",
                "destination_location__warehouse",
                "recipient",
            ),
            pk=self.kwargs["pk"],
        )
        location = movement.source_location or movement.destination_location
        is_english = get_language() == "en"
        if movement.movement_type == StockMovement.MovementType.OUT:
            operation_type = "Issue item" if is_english else _("Видача товару")
            responsible_label = (
                "Who takes the item" if is_english else _("Хто взяв товар")
            )
        elif movement.movement_type in {
            StockMovement.MovementType.IN,
            StockMovement.MovementType.RETURN,
        }:
            operation_type = "Return item" if is_english else _("Повернення товару")
            responsible_label = (
                "Recipient / responsible person"
                if is_english
                else _("Отримувач / відповідальний")
            )
        else:
            operation_type = movement.get_movement_type_display()
            responsible_label = (
                "Recipient / responsible person"
                if is_english
                else _("Отримувач / відповідальний")
            )
        labels = {
            "title": (
                "Warehouse operation control slip"
                if is_english
                else _("Контрольний талон складської операції")
            ),
            "print": "Print" if is_english else _("Друк"),
            "back": "Back" if is_english else _("Назад"),
            "operation_id": "Operation ID" if is_english else _("ID операції"),
            "operation_type": "Operation type" if is_english else _("Тип операції"),
            "occurred_at": (
                "Operation date and time"
                if is_english
                else _("Дата і час операції")
            ),
            "item": "Item" if is_english else _("Номенклатура"),
            "internal_code": "Internal code" if is_english else _("Внутрішній код"),
            "barcode": "Barcode" if is_english else _("Штрихкод"),
            "qty": "Quantity" if is_english else _("Кількість"),
            "warehouse": "Warehouse" if is_english else _("Склад"),
            "location": "Location" if is_english else _("Локація"),
            "responsible": responsible_label,
            "department": (
                "Department / place of use"
                if is_english
                else _("Цех / місце використання")
            ),
            "comment_document": (
                "Comment / document" if is_english else _("Коментар / документ")
            ),
            "video_time": (
                "Video check time:"
                if is_english
                else _("Час для перевірки по відео:")
            ),
        }
        context.update(
            {
                "labels": labels,
                "movement": movement,
                "operation_type": operation_type,
                "location": location,
                "warehouse": location.warehouse if location else None,
            }
        )
        return context


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
        initial["occurred_at"] = timezone.localtime(timezone.now()).strftime(
            "%Y-%m-%dT%H:%M"
        )
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
            message = _(
                "Недостатньо залишку для списання. Перевірте залишки перед списанням."
            )
            messages.error(self.request, message)
            form.add_error(None, message)
            return self.form_invalid(form)
        except StockServiceError as exc:
            message = str(exc)
            messages.error(self.request, message)
            form.add_error(None, message)
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
        initial["occurred_at"] = timezone.localtime(timezone.now()).strftime(
            "%Y-%m-%dT%H:%M"
        )
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
            message = _(
                "Недостатньо залишку на локації-відправнику. Перевірте залишки перед переміщенням."
            )
            messages.error(self.request, message)
            form.add_error(None, message)
            return self.form_invalid(form)
        except SameLocationTransferError:
            message = _(
                "Неможливо перемістити товар у ту саму локацію. Виберіть іншу локацію-отримувач."
            )
            messages.error(self.request, message)
            form.add_error(None, message)
            return self.form_invalid(form)
        except StockServiceError as exc:
            message = str(exc)
            messages.error(self.request, message)
            form.add_error(None, message)
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
        initial["occurred_at"] = timezone.localtime(timezone.now()).strftime(
            "%Y-%m-%dT%H:%M"
        )
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
            message = str(exc)
            messages.error(self.request, message)
            form.add_error(None, message)
            return self.form_invalid(form)
        messages.success(self.request, _("Початковий залишок збережено."))
        return redirect("movement_list")
