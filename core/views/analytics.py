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
    if form.is_valid():
        return {
            key: value
            for key, value in form.cleaned_data.items()
            if value not in (None, "")
        }
    return {}


class AnalyticsView(LoginRequiredMixin, GroupRequiredMixin, TemplateView):
    group_names = ANALYTICS_GROUPS
    template_name = "core/management/analytics.html"

    def get_filter_form(self):
        return AnalyticsFilterForm(self.request.GET or None)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = self.get_filter_form()
        filters = clean_analytics_filters(form)
        movement_summary = analytics_service.get_movement_summary(filters)
        stock_summary = analytics_service.get_stock_summary(filters)
        movements_by_day = analytics_service.get_movements_by_day(filters)
        movements_by_type = analytics_service.get_movements_by_type(filters)
        top_out = analytics_service.get_top_items_by_out(filters)
        top_in = analytics_service.get_top_items_by_in(filters)
        context.update(
            {
                "filter_form": form,
                "movement_summary": movement_summary,
                "stock_summary": stock_summary,
                "top_out": top_out,
                "top_in": top_in,
                "top_recipients": analytics_service.get_top_recipients(filters),
                "movements_by_day": movements_by_day,
                "movements_by_type": movements_by_type,
                "day_chart_json": json.dumps(
                    {
                        "labels": [str(row["day"]) for row in movements_by_day],
                        "in": [float(row["in_qty"] or 0) for row in movements_by_day],
                        "out": [float(row["out_qty"] or 0) for row in movements_by_day],
                        "writeoff": [
                            float(row["writeoff_qty"] or 0) for row in movements_by_day
                        ],
                    }
                ),
                "type_chart_json": json.dumps(
                    {
                        "labels": [
                            str(StockMovement.MovementType(row["movement_type"]).label)
                            for row in movements_by_type
                        ],
                        "values": [
                            float(row["total_qty"] or 0) for row in movements_by_type
                        ],
                    }
                ),
                "warehouse_chart_json": json.dumps(
                    {
                        "labels": [
                            row["location__warehouse__name"] or "—"
                            for row in stock_summary["by_warehouse"]
                        ],
                        "values": [
                            float(row["total_qty"] or 0)
                            for row in stock_summary["by_warehouse"]
                        ],
                    }
                ),
                "top_out_chart_json": json.dumps(
                    {
                        "labels": [row["item__name"] for row in top_out],
                        "values": [float(row["total_qty"] or 0) for row in top_out],
                    }
                ),
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
        writer.writerow(
            [
                _("Дата"),
                _("Тип операції"),
                _("Номенклатура"),
                _("Кількість"),
                _("Склад"),
                _("Локація"),
                _("Отримувач"),
            ]
        )
        for movement in analytics_service.filter_movements(filters).order_by(
            "occurred_at", "id"
        ):
            location = movement_export_location(movement, filters)
            writer.writerow(
                [
                    movement.occurred_at.strftime("%Y-%m-%d %H:%M"),
                    movement.get_movement_type_display(),
                    movement.item.name,
                    movement.qty,
                    location.warehouse.name if location else "",
                    location.name if location else "",
                    movement.recipient.name if movement.recipient else "",
                ]
            )
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
