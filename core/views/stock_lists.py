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



class StockBalanceListView(LoginRequiredMixin, GroupRequiredMixin, ListView):
    group_names = STOCK_VIEW_GROUPS
    model = StockBalance
    template_name = "core/stockbalance_list.html"
    context_object_name = "balances"
    paginate_by = 50

    def get_filter_form(self):
        return StockBalanceFilterForm(self.request.GET or None)

    def get_queryset(self):
        queryset = (
            StockBalance.objects.select_related(
                "item",
                "item__unit",
                "item__barcode",
                "location",
                "location__warehouse",
            )
            .filter(
                item__is_active=True,
                location__is_active=True,
                location__warehouse__is_active=True,
            )
            .order_by("item__name", "location__warehouse__name", "location__name")
        )
        form = self.get_filter_form()
        if not form.is_valid():
            return queryset

        warehouse = form.cleaned_data.get("warehouse")
        location = form.cleaned_data.get("location")
        item = form.cleaned_data.get("item")
        query = form.cleaned_data.get("q")

        if warehouse:
            queryset = queryset.filter(location__warehouse=warehouse)
        if location:
            queryset = queryset.filter(location=location)
        if item:
            queryset = queryset.filter(item=item)
        if query:
            queryset = queryset.filter(
                Q(item__name__icontains=query)
                | Q(item__internal_code__icontains=query)
                | Q(item__barcode__barcode__icontains=query)
            )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.get_filter_form()
        return context


class StockMovementListView(LoginRequiredMixin, GroupRequiredMixin, ListView):
    group_names = STOCK_VIEW_GROUPS
    model = StockMovement
    template_name = "core/stockmovement_list.html"
    context_object_name = "movements"
    paginate_by = 50

    def get_filter_form(self):
        return StockMovementFilterForm(self.request.GET or None)

    def get_queryset(self):
        queryset = StockMovement.objects.select_related(
            "item", "item__barcode", "source_location", "source_location__warehouse",
            "destination_location", "destination_location__warehouse", "recipient",
            "inventory_count"
        )
        form = self.get_filter_form()
        if not form.is_valid():
            return queryset
        cd = form.cleaned_data
        if cd.get("movement_type"):
            queryset = queryset.filter(movement_type=cd["movement_type"])
        if cd.get("item"):
            queryset = queryset.filter(item=cd["item"])
        if cd.get("warehouse"):
            queryset = queryset.filter(
                Q(source_location__warehouse=cd["warehouse"]) | Q(destination_location__warehouse=cd["warehouse"])
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
        if cd.get("document_number"):
            queryset = queryset.filter(document_number__icontains=cd["document_number"])
        if cd.get("q"):
            q = cd["q"]
            queryset = queryset.filter(
                Q(item__name__icontains=q) | Q(item__internal_code__icontains=q) | Q(item__barcode__barcode__icontains=q)
            )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.get_filter_form()
        return context
