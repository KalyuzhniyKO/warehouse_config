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



class ItemLabelDownloadView(LoginRequiredMixin, GroupRequiredMixin, View):
    group_names = PRINT_GROUPS

    def get(self, request, pk):
        item = get_object_or_404(Item.objects.select_related("barcode"), pk=pk, is_active=True)
        return download_item_label_pdf(item)


class ItemLabelPrintView(LoginRequiredMixin, GroupRequiredMixin, FormView):
    group_names = PRINT_GROUPS
    template_name = "core/item_label_print.html"
    form_class = PrintLabelForm

    def dispatch(self, request, *args, **kwargs):
        self.item = get_object_or_404(Item.objects.select_related("barcode"), pk=kwargs["pk"], is_active=True)
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        default_template = get_default_label_template()
        if default_template:
            initial["label_template"] = default_template
        printer = Printer.objects.filter(is_active=True, is_default=True).first()
        if printer:
            initial["printer"] = printer
        return initial

    def form_valid(self, form):
        job = print_item_label(
            item=self.item,
            printer=form.cleaned_data["printer"],
            label_template=form.cleaned_data["label_template"],
            copies=form.cleaned_data["copies"],
            user=self.request.user,
        )
        if job.status == PrintJob.Status.PRINTED:
            messages.success(self.request, _("Етикетку відправлено на друк."))
        else:
            messages.error(self.request, _("Не вдалося надрукувати етикетку: %(error)s") % {"error": job.error_message})
        return redirect("item_label_print", pk=self.item.pk)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["item"] = self.item
        return context


class PrinterListView(LoginRequiredMixin, GroupRequiredMixin, ListView):
    group_names = SETTINGS_GROUPS
    model = Printer
    template_name = "core/printer_list.html"
    context_object_name = "printers"


class PrinterCreateView(LoginRequiredMixin, GroupRequiredMixin, CreateView):
    group_names = SETTINGS_GROUPS
    model = Printer
    form_class = PrinterForm
    template_name = "core/simple_form.html"
    success_url = reverse_lazy("printer_list")

    def form_valid(self, form):
        messages.success(self.request, _("Принтер збережено."))
        return super().form_valid(form)


class LabelTemplateListView(LoginRequiredMixin, GroupRequiredMixin, ListView):
    group_names = SETTINGS_GROUPS
    model = LabelTemplate
    template_name = "core/labeltemplate_list.html"
    context_object_name = "label_templates"


class LabelTemplateCreateView(LoginRequiredMixin, GroupRequiredMixin, CreateView):
    group_names = SETTINGS_GROUPS
    model = LabelTemplate
    form_class = LabelTemplateForm
    template_name = "core/simple_form.html"
    success_url = reverse_lazy("labeltemplate_list")

    def form_valid(self, form):
        messages.success(self.request, _("Шаблон етикетки збережено."))
        return super().form_valid(form)
