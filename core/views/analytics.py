import csv
import json
from urllib.parse import urlencode

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
)



class AnalyticsRedirectView(LoginRequiredMixin, GroupRequiredMixin, View):
    group_names = ANALYTICS_GROUPS

    def get(self, request, *args, **kwargs):
        return redirect("management_analytics")


def clean_analytics_filters(form):
    if not form.is_valid():
        return {}
    filters = {key: value for key, value in form.cleaned_data.items() if value not in (None, "")}
    filters.update(analytics_service.get_analytics_filters(form.cleaned_data))
    return filters


class AnalyticsView(LoginRequiredMixin, GroupRequiredMixin, TemplateView):
    group_names = ANALYTICS_GROUPS
    template_name = "core/management/analytics.html"

    def get_filter_form(self):
        return AnalyticsFilterForm(self.request.GET or None)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = self.get_filter_form()
        filters = clean_analytics_filters(form)
        summary = analytics_service.get_analytics_summary(filters)
        previous_filters = analytics_service.get_previous_period(filters)
        previous_summary = analytics_service.get_analytics_summary(previous_filters) if previous_filters.get("date_from") else None
        summary_deltas = {}
        for key in ["operations_count", "receive_qty", "issue_qty", "return_qty", "writeoff_qty"]:
            summary_deltas[key] = analytics_service.get_kpi_delta(summary.get(key), previous_summary.get(key) if previous_summary else None)

        query_base = {k: v for k, v in self.request.GET.items() if v}
        date_params = {"date_from": filters.get("date_from"), "date_to": filters.get("date_to")}
        movement_query = {**{k: str(v) for k, v in query_base.items() if k in {"warehouse", "location"}}, **{k: str(v) for k, v in date_params.items() if v}}
        daily_movement = analytics_service.get_daily_movement(filters)
        top_issued_items = analytics_service.get_top_issued_items(filters)
        top_usage_places = analytics_service.get_top_usage_places(filters)
        top_recipients = analytics_service.get_top_recipients(filters)
        context.update(
            {
                "filter_form": form,
                "summary": summary,
                "summary_deltas": summary_deltas,
                "daily_movement": daily_movement,
                "operation_mix": analytics_service.get_operation_mix(filters),
                "top_issued_items": top_issued_items,
                "top_usage_places": top_usage_places,
                "top_recipients": top_recipients,
                "inactive_stock_items": analytics_service.get_inactive_stock_items(filters),
                "recent_movements": analytics_service.get_recent_movements(filters),
                "movement_list_base_url": reverse("movement_list"),
                "movement_query": urlencode(movement_query),
            }
        )
        return context


def movement_export_location(movement, filters):
    if filters.get("location"):
        location = filters["location"]
        if movement.source_location_id == location.pk:
            return movement.source_location
        if movement.destination_location_id == location.pk:
            return movement.destination_location
    if filters.get("warehouse"):
        warehouse = filters["warehouse"]
        if (
            movement.source_location
            and movement.source_location.warehouse_id == warehouse.pk
        ):
            return movement.source_location
        if (
            movement.destination_location
            and movement.destination_location.warehouse_id == warehouse.pk
        ):
            return movement.destination_location
    return movement.destination_location or movement.source_location


class AnalyticsCSVExportView(LoginRequiredMixin, GroupRequiredMixin, View):
    group_names = ANALYTICS_GROUPS

    def get(self, request, *args, **kwargs):
        form = AnalyticsFilterForm(request.GET or None)
        filters = clean_analytics_filters(form)
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = (
            'attachment; filename="warehouse-analytics.csv"'
        )
        response.write("\ufeff")
        writer = csv.writer(response)
        summary = analytics_service.get_analytics_summary(filters)
        writer.writerow([_("Розділ"), _("Показник"), _("Значення")])
        for key, label in [("operations_count", _("Операцій за період")), ("receive_qty", _("Прихід")), ("issue_qty", _("Видача")), ("return_qty", _("Повернення")), ("writeoff_qty", _("Списання"))]:
            writer.writerow([_("Зведення"), label, summary[key]])
        writer.writerow([])
        writer.writerow([_("Рух по днях"), _("Дата"), _("Операції"), _("Прихід"), _("Видача"), _("Повернення"), _("Списання")])
        for row in analytics_service.get_daily_movement(filters):
            writer.writerow(["", row["day"], row["operations"], row["receive_qty"], row["issue_qty"], row["return_qty"], row["writeoff_qty"]])
        writer.writerow([])
        writer.writerow([_("Топ товарів"), _("Номенклатура"), _("Кількість"), _("Операції")])
        for row in analytics_service.get_top_issued_items(filters):
            writer.writerow(["", row["item__name"], row["total_qty"], row["operations"]])
        writer.writerow([])
        writer.writerow([_("Топ цехів"), _("Цех"), _("Кількість"), _("Операції")])
        for row in analytics_service.get_top_usage_places(filters):
            writer.writerow(["", row["department"], row["total_qty"], row["operations"]])
        writer.writerow([])
        writer.writerow([_("Топ отримувачів"), _("Отримувач"), _("Кількість"), _("Операції")])
        for row in analytics_service.get_top_recipients(filters):
            writer.writerow(["", row["recipient__name"], row["total_qty"], row["operations"]])
        writer.writerow([])
        writer.writerow([_("Останні операції"), _("Дата"), _("Тип"), _("Номенклатура"), _("Кількість"), _("Документ")])
        for movement in analytics_service.get_recent_movements(filters):
            writer.writerow(["", movement.occurred_at.strftime("%Y-%m-%d %H:%M"), movement.get_movement_type_display(), movement.item.name, movement.qty, movement.document_number or ""])
        return response


class AnalyticsXLSXExportView(LoginRequiredMixin, GroupRequiredMixin, View):
    group_names = ANALYTICS_GROUPS

    def get(self, request, *args, **kwargs):
        try:
            from openpyxl import Workbook
        except ImportError:
            return HttpResponse(
                _("XLSX експорт недоступний: openpyxl не встановлено."), status=501
            )
        form = AnalyticsFilterForm(request.GET or None)
        filters = clean_analytics_filters(form)
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Аналітика"
        sheet.append(
            [
                "Дата",
                "Тип операції",
                "Номенклатура",
                "Кількість",
                "Склад",
                "Локація",
                "Отримувач",
            ]
        )
        for movement in analytics_service.filter_movements(filters).order_by(
            "occurred_at", "id"
        ):
            location = movement_export_location(movement, filters)
            sheet.append(
                [
                    movement.occurred_at.strftime("%Y-%m-%d %H:%M"),
                    movement.get_movement_type_display(),
                    movement.item.name,
                    float(movement.qty),
                    location.warehouse.name if location else "",
                    location.name if location else "",
                    movement.recipient.name if movement.recipient else "",
                ]
            )
        response = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = (
            'attachment; filename="warehouse-analytics.xlsx"'
        )
        workbook.save(response)
        return response
