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



def get_inventory_export_queryset(inventory_count):
    return inventory_count.lines.select_related(
        "item", "item__barcode", "location", "location__warehouse"
    ).order_by("item__name", "location__name", "id")


def inventory_line_export_row(inventory_count, line):
    return [
        inventory_count.number,
        inventory_count.get_status_display(),
        inventory_count.warehouse.name,
        inventory_count.location.name if inventory_count.location else "",
        line.item.name,
        line.item.internal_code,
        line.barcode or (line.item.barcode.barcode if line.item.barcode_id else ""),
        line.location.name,
        line.expected_qty,
        line.actual_qty if line.actual_qty is not None else "",
        line.difference_qty,
        line.comment,
    ]


INVENTORY_EXPORT_HEADERS = [
    _("Номер інвентаризації"),
    _("Статус"),
    _("Склад"),
    _("Локація інвентаризації"),
    _("Номенклатура"),
    _("Internal code"),
    _("Barcode"),
    _("Локація"),
    _("Облікова кількість"),
    _("Фактична кількість"),
    _("Різниця"),
    _("Коментар рядка"),
]


class InventoryCSVExportView(LoginRequiredMixin, GroupRequiredMixin, View):
    group_names = STOCK_VIEW_GROUPS

    def get(self, request, pk, *args, **kwargs):
        inventory_count = get_object_or_404(
            InventoryCount.objects.select_related("warehouse", "location"), pk=pk
        )
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = (
            f'attachment; filename="inventory_{inventory_count.number}.csv"'
        )
        response.write("\ufeff")
        writer = csv.writer(response)
        writer.writerow(INVENTORY_EXPORT_HEADERS)
        for line in get_inventory_export_queryset(inventory_count):
            writer.writerow(inventory_line_export_row(inventory_count, line))
        return response


class InventoryXLSXExportView(LoginRequiredMixin, GroupRequiredMixin, View):
    group_names = STOCK_VIEW_GROUPS

    def get(self, request, pk, *args, **kwargs):
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font
        except ImportError:
            return HttpResponse(_("XLSX export requires openpyxl."), status=503)

        inventory_count = get_object_or_404(
            InventoryCount.objects.select_related("warehouse", "location"), pk=pk
        )
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Inventory"
        sheet.append([str(header) for header in INVENTORY_EXPORT_HEADERS])
        for cell in sheet[1]:
            cell.font = Font(bold=True)

        for line in get_inventory_export_queryset(inventory_count):
            row = inventory_line_export_row(inventory_count, line)
            row[8] = float(line.expected_qty)
            row[9] = float(line.actual_qty) if line.actual_qty is not None else None
            row[10] = float(line.difference_qty)
            sheet.append(row)

        widths = [22, 14, 24, 24, 32, 18, 18, 24, 18, 18, 14, 32]
        for index, width in enumerate(widths, start=1):
            column_letter = sheet.cell(row=1, column=index).column_letter
            sheet.column_dimensions[column_letter].width = width

        response = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = (
            f'attachment; filename="inventory_{inventory_count.number}.xlsx"'
        )
        workbook.save(response)
        return response


class InventoryListView(LoginRequiredMixin, GroupRequiredMixin, ListView):
    group_names = STOCK_VIEW_GROUPS
    model = InventoryCount
    template_name = "core/inventory_list.html"
    context_object_name = "inventory_counts"
    paginate_by = 50

    def get_queryset(self):
        return InventoryCount.objects.select_related(
            "warehouse", "location", "created_by"
        ).order_by("-started_at", "-id")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["can_edit_inventory"] = user_in_groups(self.request.user, STOCK_EDIT_GROUPS)
        return context


class InventoryCreateView(LoginRequiredMixin, GroupRequiredMixin, FormView):
    group_names = STOCK_EDIT_GROUPS
    template_name = "core/inventory_create.html"
    form_class = InventoryCountCreateForm

    def form_valid(self, form):
        inventory_count = create_inventory_count(
            warehouse=form.cleaned_data["warehouse"],
            location=form.cleaned_data["location"],
            user=self.request.user,
            comment=form.cleaned_data["comment"],
        )
        messages.success(self.request, _("Інвентаризацію створено."))
        return redirect("inventory_count", pk=inventory_count.pk)


class InventoryDetailView(LoginRequiredMixin, GroupRequiredMixin, TemplateView):
    group_names = STOCK_VIEW_GROUPS
    template_name = "core/inventory_detail.html"

    def get_inventory_count(self):
        return get_object_or_404(
            InventoryCount.objects.select_related("warehouse", "location", "created_by"),
            pk=self.kwargs["pk"],
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        inventory_count = self.get_inventory_count()
        context["inventory_count"] = inventory_count
        lines = inventory_count.lines.select_related(
            "item", "item__barcode", "location", "location__warehouse"
        )
        summary = inventory_count.lines.aggregate(
            total_lines=Count("id"),
            difference_lines=Count("id", filter=~Q(difference_qty=0)),
            total_surplus=Sum("difference_qty", filter=Q(difference_qty__gt=0)),
            total_shortage=Sum("difference_qty", filter=Q(difference_qty__lt=0)),
        )
        context["lines"] = lines
        context["inventory_summary"] = {
            "total_lines": summary["total_lines"] or 0,
            "difference_lines": summary["difference_lines"] or 0,
            "total_surplus": summary["total_surplus"] or 0,
            "total_shortage": abs(summary["total_shortage"] or 0),
        }
        context["can_export_inventory"] = user_in_groups(
            self.request.user, STOCK_VIEW_GROUPS
        )
        context["can_edit_inventory"] = user_in_groups(
            self.request.user, STOCK_EDIT_GROUPS
        )
        context["can_complete_inventory"] = user_in_groups(
            self.request.user, STOCK_EDIT_GROUPS
        )
        return context


class InventoryCompleteView(LoginRequiredMixin, GroupRequiredMixin, View):
    group_names = STOCK_EDIT_GROUPS

    def post(self, request, pk):
        inventory_count = get_object_or_404(InventoryCount, pk=pk)
        try:
            complete_inventory_count(inventory_count=inventory_count, user=request.user)
        except InventoryServiceError as exc:
            messages.error(request, exc)
        else:
            messages.success(
                request,
                _("Інвентаризацію завершено. Залишки скориговано."),
            )
        return redirect("inventory_detail", pk=pk)


class InventoryCountView(LoginRequiredMixin, GroupRequiredMixin, TemplateView):
    group_names = STOCK_EDIT_GROUPS
    template_name = "core/inventory_count.html"

    def get_inventory_count(self):
        return get_object_or_404(
            InventoryCount.objects.select_related("warehouse", "location", "created_by"),
            pk=self.kwargs["pk"],
            status=InventoryCount.Status.IN_PROGRESS,
        )

    def get_lines(self, inventory_count):
        queryset = inventory_count.lines.select_related(
            "item", "item__barcode", "location", "location__warehouse"
        )
        query = self.request.GET.get("q", "").strip()
        if query:
            queryset = queryset.filter(
                Q(item__name__icontains=query)
                | Q(item__internal_code__icontains=query)
                | Q(barcode__icontains=query)
                | Q(item__barcode__barcode__icontains=query)
                | Q(location__name__icontains=query)
                | Q(location__barcode__barcode__icontains=query)
            )
        return queryset

    def build_line_forms(self, lines, data=None):
        return [
            InventoryCountLineForm(data=data, instance=line, prefix=f"line-{line.pk}")
            for line in lines
        ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        inventory_count = kwargs.get("inventory_count") or self.get_inventory_count()
        lines = list(kwargs.get("lines") or self.get_lines(inventory_count))
        context["inventory_count"] = inventory_count
        context["lines"] = lines
        context["line_forms"] = kwargs.get("line_forms") or self.build_line_forms(lines)
        context["search_query"] = self.request.GET.get("q", "").strip()
        return context

    def post(self, request, *args, **kwargs):
        inventory_count = self.get_inventory_count()
        lines = list(self.get_lines(inventory_count))
        line_forms = self.build_line_forms(lines, data=request.POST)
        if not all(form.is_valid() for form in line_forms):
            return self.render_to_response(
                self.get_context_data(
                    inventory_count=inventory_count, lines=lines, line_forms=line_forms
                )
            )
        for form in line_forms:
            actual_qty = form.cleaned_data.get("actual_qty")
            if actual_qty is None:
                continue
            update_inventory_line_actual_qty(
                line=form.instance,
                actual_qty=actual_qty,
                user=request.user,
                comment=form.cleaned_data.get("comment", ""),
            )
        messages.success(request, _("Підрахунок збережено."))
        url = reverse("inventory_count", kwargs={"pk": inventory_count.pk})
        query = request.GET.urlencode()
        if query:
            url = f"{url}?{query}"
        return redirect(url)
