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
    LabelTemplateElementFormSet,
    LabelTemplateForm,
    DEFAULT_LABEL_TEMPLATE_ELEMENTS,
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
    LabelTemplateElement,
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
from ..services.labels import download_item_label_pdf, generate_item_label_pdf, get_default_label_template, print_item_label
from ..services.printers import (
    PrinterDiscoveryError,
    get_default_system_printer,
    list_system_printers,
    print_test_page,
    sync_system_printers_to_db,
)
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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        db_printers = {printer.system_name: printer for printer in Printer.objects.all()}
        try:
            default_system_name = get_default_system_printer()
            system_printers = []
            for system_printer in list_system_printers():
                db_printer = db_printers.get(system_printer["system_name"])
                system_printers.append(
                    {
                        **system_printer,
                        "db_printer": db_printer,
                        "in_db": db_printer is not None,
                        "is_cups_default": system_printer["system_name"] == default_system_name,
                    }
                )
            context["system_printers"] = system_printers
            context["cups_default_system_name"] = default_system_name
            context["cups_error"] = ""
        except PrinterDiscoveryError as exc:
            context["system_printers"] = []
            context["cups_default_system_name"] = None
            context["cups_error"] = str(exc)
        return context


class PrinterSyncView(LoginRequiredMixin, GroupRequiredMixin, View):
    group_names = SETTINGS_GROUPS

    def post(self, request):
        try:
            result = sync_system_printers_to_db()
            messages.success(
                request,
                _("Список принтерів оновлено: створено %(created)s, оновлено %(updated)s.")
                % {"created": result["created"], "updated": result["updated"]},
            )
        except PrinterDiscoveryError as exc:
            messages.error(request, str(exc))
        return redirect("printer_list")


class PrinterTestPrintView(LoginRequiredMixin, GroupRequiredMixin, View):
    group_names = SETTINGS_GROUPS

    def post(self, request, pk):
        printer = get_object_or_404(Printer, pk=pk)
        result = print_test_page(printer)
        if result["success"]:
            messages.success(request, result["message"])
        else:
            messages.error(request, result["message"])
        return redirect("printer_list")


class PrinterCreateView(LoginRequiredMixin, GroupRequiredMixin, CreateView):
    group_names = SETTINGS_GROUPS
    model = Printer
    form_class = PrinterForm
    template_name = "core/printer_form.html"
    success_url = reverse_lazy("printer_list")

    def form_valid(self, form):
        messages.success(self.request, _("Принтер збережено."))
        return super().form_valid(form)


class PrinterUpdateView(LoginRequiredMixin, GroupRequiredMixin, UpdateView):
    group_names = SETTINGS_GROUPS
    model = Printer
    form_class = PrinterForm
    template_name = "core/printer_form.html"
    success_url = reverse_lazy("printer_list")

    def form_valid(self, form):
        messages.success(self.request, _("Принтер збережено."))
        return super().form_valid(form)




class LabelTemplatePreviewView(LoginRequiredMixin, GroupRequiredMixin, View):
    group_names = tuple(SETTINGS_GROUPS | PRINT_GROUPS)

    def get(self, request, pk):
        template = get_object_or_404(LabelTemplate, pk=pk)
        item_id = request.GET.get("item")
        item_qs = Item.objects.filter(is_active=True).select_related("barcode")
        item = item_qs.filter(pk=item_id).first() if item_id else None
        item = item or item_qs.order_by("id").first()
        if not item:
            return HttpResponse(_("Немає активних товарів для перегляду етикетки. Створіть товар."), content_type="text/html; charset=utf-8")
        pdf = generate_item_label_pdf(item, template)
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="label-preview-{template.pk}.pdf"'
        return response


class LabelTemplateListView(LoginRequiredMixin, GroupRequiredMixin, ListView):
    group_names = SETTINGS_GROUPS
    model = LabelTemplate
    template_name = "core/labeltemplate_list.html"
    context_object_name = "label_templates"


class LabelTemplateCreateView(LoginRequiredMixin, GroupRequiredMixin, CreateView):
    group_names = SETTINGS_GROUPS
    model = LabelTemplate
    form_class = LabelTemplateForm
    template_name = "core/labeltemplate_form.html"
    success_url = reverse_lazy("labeltemplate_list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        element_formset = kwargs.get("element_formset")
        if element_formset is None:
            element_formset = LabelTemplateElementFormSet(prefix="elements", initial=self._default_element_initial())
        context["element_formset"] = element_formset
        return context

    def form_valid(self, form):
        formset = LabelTemplateElementFormSet(self.request.POST, instance=form.instance, prefix="elements")
        if not formset.is_valid():
            return self.form_invalid(form, formset=formset)
        messages.success(self.request, _("Шаблон етикетки збережено."))
        response = super().form_valid(form)
        formset.instance = self.object
        formset.save()
        self._ensure_default_elements(self.object)
        return response

    def form_invalid(self, form, formset=None):
        return self.render_to_response(self.get_context_data(form=form, element_formset=formset))

    @staticmethod
    def _default_element_initial():
        return [
            {
                "element_type": element_type,
                "x_mm": x,
                "y_mm": y,
                "width_mm": width,
                "height_mm": height,
                "font_size": 8,
                "is_visible": True,
                "sort_order": sort_order,
            }
            for element_type, x, y, width, height, sort_order in DEFAULT_LABEL_TEMPLATE_ELEMENTS
        ]

    @staticmethod
    def _ensure_default_elements(template):
        if template.elements.exists():
            return
        visibility = {
            "item_name": template.show_item_name,
            "internal_code": template.show_internal_code,
            "barcode": True,
            "barcode_text": template.show_barcode_text,
        }
        for element_type, x, y, width, height, sort_order in DEFAULT_LABEL_TEMPLATE_ELEMENTS:
            LabelTemplateElement.objects.create(
                template=template,
                element_type=element_type,
                x_mm=x,
                y_mm=y,
                width_mm=width,
                height_mm=height,
                font_size=8,
                is_visible=visibility.get(element_type, True),
                sort_order=sort_order,
            )


class LabelTemplateUpdateView(LoginRequiredMixin, GroupRequiredMixin, UpdateView):
    group_names = SETTINGS_GROUPS
    model = LabelTemplate
    form_class = LabelTemplateForm
    template_name = "core/labeltemplate_form.html"
    success_url = reverse_lazy("labeltemplate_list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        self._ensure_default_elements(self.object)
        context["element_formset"] = kwargs.get("element_formset") or LabelTemplateElementFormSet(
            instance=self.object, prefix="elements"
        )
        return context

    def form_valid(self, form):
        formset = LabelTemplateElementFormSet(self.request.POST, instance=form.instance, prefix="elements")
        if not formset.is_valid():
            return self.form_invalid(form, formset=formset)
        messages.success(self.request, _("Шаблон етикетки збережено."))
        response = super().form_valid(form)
        formset.instance = self.object
        formset.save()
        self._ensure_default_elements(self.object)
        return response

    def form_invalid(self, form, formset=None):
        return self.render_to_response(self.get_context_data(form=form, element_formset=formset))

    _ensure_default_elements = staticmethod(LabelTemplateCreateView._ensure_default_elements)
