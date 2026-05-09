import csv
import json

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.mixins import LoginRequiredMixin
from django.conf import settings
from django.forms.models import model_to_dict
from django.db.models import Q
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.html import format_html, linebreaks, urlize
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, FormView, ListView, TemplateView, UpdateView, View

from .forms import (
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
    UnitForm,
    WarehouseForm,
)
from .models import (
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
from .permissions import (
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
from .services import analytics as analytics_service
from .services.inventory import (
    InventoryServiceError,
    complete_inventory_count,
    create_inventory_count,
    update_inventory_line_actual_qty,
)
from .services.labels import download_item_label_pdf, get_default_label_template, print_item_label
from .services.stock import InsufficientStockError, StockServiceError, create_initial_balance, issue_stock, receive_stock


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "core/dashboard.html"


class DirectoryConfigMixin:
    model = None
    form_class = None
    list_title = ""
    create_title = ""
    update_title = ""
    archive_title = ""
    list_url_name = ""
    create_url_name = ""
    update_url_name = ""
    archive_url_name = ""
    restore_url_name = ""
    search_fields = ("name",)
    columns = ()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "list_title": self.list_title,
                "create_title": self.create_title,
                "update_title": self.update_title,
                "archive_title": self.archive_title,
                "list_url_name": self.list_url_name,
                "create_url_name": self.create_url_name,
                "update_url_name": self.update_url_name,
                "archive_url_name": self.archive_url_name,
                "restore_url_name": self.restore_url_name,
                "columns": self.columns,
            }
        )
        return context

    def get_success_url(self):
        return reverse_lazy(self.list_url_name)


class ActiveDirectoryQuerysetMixin:
    def get_queryset(self):
        queryset = self.model.objects.all()
        status = self.request.GET.get("status", "active")
        query = self.request.GET.get("q", "").strip()

        if status == "archived":
            queryset = queryset.filter(is_active=False)
        elif status != "all":
            status = "active"
            queryset = queryset.filter(is_active=True)

        searchable_fields = getattr(self, "search_fields", ("name",))
        if query:
            search_filter = Q()
            for field_name in searchable_fields:
                search_filter |= Q(**{f"{field_name}__icontains": query})
            queryset = queryset.filter(search_filter)
        return queryset


class DirectoryListView(
    LoginRequiredMixin, DirectoryConfigMixin, ActiveDirectoryQuerysetMixin, ListView
):
    template_name = "core/directory_list.html"
    context_object_name = "objects"
    paginate_by = 50

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        status = self.request.GET.get("status", "active")
        context["current_status"] = (
            status if status in {"active", "archived", "all"} else "active"
        )
        context["search_query"] = self.request.GET.get("q", "").strip()
        return context


class DirectoryCreateView(
    LoginRequiredMixin, GroupRequiredMixin, DirectoryConfigMixin, CreateView
):
    group_names = DIRECTORY_EDIT_GROUPS
    template_name = "core/directory_form.html"

    def form_valid(self, form):
        response = super().form_valid(form)
        if isinstance(self.object, Item) and self.object.barcode_id:
            messages.success(
                self.request,
                _("Номенклатуру створено. Штрихкод: %(barcode)s")
                % {"barcode": self.object.barcode.barcode},
            )
        else:
            messages.success(self.request, _("Запис успішно створено."))
        return response


class DirectoryUpdateView(
    LoginRequiredMixin, GroupRequiredMixin, DirectoryConfigMixin, UpdateView
):
    group_names = DIRECTORY_EDIT_GROUPS
    template_name = "core/directory_form.html"

    def form_valid(self, form):
        messages.success(self.request, _("Запис успішно оновлено."))
        return super().form_valid(form)


class DirectoryArchiveView(
    LoginRequiredMixin, GroupRequiredMixin, DirectoryConfigMixin, View
):
    group_names = DIRECTORY_EDIT_GROUPS

    def get_blocking_message(self, obj):
        if isinstance(obj, Category):
            if obj.children.filter(is_active=True).exists():
                return _(
                    "Категорію не можна архівувати, бо вона має активні дочірні категорії."
                )
            if obj.items.filter(is_active=True).exists():
                return _(
                    "Категорію не можна архівувати, бо вона використовується в активній номенклатурі."
                )
        elif isinstance(obj, Unit) and obj.items.filter(is_active=True).exists():
            return _(
                "Одиницю виміру не можна архівувати, бо вона використовується в активній номенклатурі."
            )
        elif (
            isinstance(obj, Warehouse) and obj.locations.filter(is_active=True).exists()
        ):
            return _("Склад не можна архівувати, бо він має активні локації.")
        elif isinstance(obj, Location) and obj.stock_balances.exclude(qty=0).exists():
            return _("Локацію не можна архівувати, бо на ній є ненульові залишки.")
        elif isinstance(obj, Item) and obj.stock_balances.exclude(qty=0).exists():
            return _("Номенклатуру не можна архівувати, бо за нею є ненульові залишки.")
        return None

    def post(self, request, *args, **kwargs):
        obj = self.model.objects.get(pk=kwargs["pk"])
        blocking_message = self.get_blocking_message(obj)
        if blocking_message:
            messages.error(request, blocking_message)
        else:
            obj.is_active = False
            obj.save(update_fields=["is_active", "updated_at"])
            messages.success(request, _("Запис переміщено в архів."))
        return HttpResponseRedirect(reverse(self.list_url_name))


class DirectoryRestoreView(
    LoginRequiredMixin, GroupRequiredMixin, DirectoryConfigMixin, View
):
    group_names = DIRECTORY_EDIT_GROUPS

    def post(self, request, *args, **kwargs):
        obj = self.model.objects.get(pk=kwargs["pk"])
        data = model_to_dict(obj, fields=self.form_class.Meta.fields)
        data["is_active"] = True
        form = self.form_class(data=data, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, _("Запис відновлено з архіву."))
        else:
            first_errors = next(iter(form.errors.values()), [])
            message = (
                first_errors[0] if first_errors else _("Запис не можна відновити.")
            )
            messages.error(request, message)
        return HttpResponseRedirect(reverse(self.list_url_name))


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
        context["lines"] = inventory_count.lines.select_related(
            "item", "item__barcode", "location", "location__warehouse"
        )
        context["can_edit_inventory"] = user_in_groups(self.request.user, STOCK_EDIT_GROUPS)
        context["can_complete_inventory"] = user_in_groups(self.request.user, STOCK_EDIT_GROUPS)
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


DIRECTORIES = {
    "unit": {
        "model": Unit,
        "form_class": UnitForm,
        "list_title": _("Одиниці виміру"),
        "create_title": _("Створити одиницю виміру"),
        "update_title": _("Редагувати одиницю виміру"),
        "archive_title": _("Архівувати одиницю виміру"),
        "list_url_name": "unit_list",
        "create_url_name": "unit_create",
        "update_url_name": "unit_update",
        "archive_url_name": "unit_archive",
        "restore_url_name": "unit_restore",
        "columns": (("name", _("Назва")), ("symbol", _("Позначення"))),
        "search_fields": ("name", "symbol"),
    },
    "category": {
        "model": Category,
        "form_class": CategoryForm,
        "list_title": _("Категорії"),
        "create_title": _("Створити категорію"),
        "update_title": _("Редагувати категорію"),
        "archive_title": _("Архівувати категорію"),
        "list_url_name": "category_list",
        "create_url_name": "category_create",
        "update_url_name": "category_update",
        "archive_url_name": "category_archive",
        "restore_url_name": "category_restore",
        "columns": (("name", _("Назва")), ("parent", _("Батьківська категорія"))),
    },
    "recipient": {
        "model": Recipient,
        "form_class": RecipientForm,
        "list_title": _("Отримувачі"),
        "create_title": _("Створити отримувача"),
        "update_title": _("Редагувати отримувача"),
        "archive_title": _("Архівувати отримувача"),
        "list_url_name": "recipient_list",
        "create_url_name": "recipient_create",
        "update_url_name": "recipient_update",
        "archive_url_name": "recipient_archive",
        "restore_url_name": "recipient_restore",
        "columns": (
            ("name", _("Назва")),
            ("contact_name", _("Контакт")),
            ("phone", _("Телефон")),
        ),
        "search_fields": ("name", "contact_name", "phone"),
    },
    "item": {
        "model": Item,
        "form_class": ItemForm,
        "list_title": _("Номенклатура"),
        "create_title": _("Створити номенклатуру"),
        "update_title": _("Редагувати номенклатуру"),
        "archive_title": _("Архівувати номенклатуру"),
        "list_url_name": "item_list",
        "create_url_name": "item_create",
        "update_url_name": "item_update",
        "archive_url_name": "item_archive",
        "restore_url_name": "item_restore",
        "columns": (
            ("name", _("Назва")),
            ("internal_code", _("Внутрішній код")),
            ("barcode_value", _("Штрихкод")),
            ("category", _("Категорія")),
            ("unit", _("Одиниця")),
        ),
        "search_fields": ("name", "internal_code"),
    },
    "warehouse": {
        "model": Warehouse,
        "form_class": WarehouseForm,
        "list_title": _("Склади"),
        "create_title": _("Створити склад"),
        "update_title": _("Редагувати склад"),
        "archive_title": _("Архівувати склад"),
        "list_url_name": "warehouse_list",
        "create_url_name": "warehouse_create",
        "update_url_name": "warehouse_update",
        "archive_url_name": "warehouse_archive",
        "restore_url_name": "warehouse_restore",
        "columns": (("name", _("Назва")), ("barcode_value", _("Штрихкод")), ("address", _("Адреса"))),
    },
    "location": {
        "model": Location,
        "form_class": LocationForm,
        "list_title": _("Локації"),
        "create_title": _("Створити локацію"),
        "update_title": _("Редагувати локацію"),
        "archive_title": _("Архівувати локацію"),
        "list_url_name": "location_list",
        "create_url_name": "location_create",
        "update_url_name": "location_update",
        "archive_url_name": "location_archive",
        "restore_url_name": "location_restore",
        "columns": (
            ("warehouse", _("Склад")),
            ("name", _("Назва")),
            ("location_type", _("Тип")),
            ("barcode_value", _("Штрихкод")),
        ),
    },
}


def directory_view(view_class, directory_key):
    return view_class.as_view(**DIRECTORIES[directory_key])


class PlaceholderPageView(LoginRequiredMixin, TemplateView):
    template_name = "core/placeholder.html"
    title = ""
    description = ""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = self.title
        context["description"] = self.description
        return context


class ManagementDashboardView(LoginRequiredMixin, GroupRequiredMixin, TemplateView):
    group_names = MANAGEMENT_GROUPS
    template_name = "core/management/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "can_manage_users": user_in_groups(
                    self.request.user, USER_MANAGEMENT_GROUPS
                ),
                "can_manage_directories": user_in_groups(
                    self.request.user, DIRECTORY_EDIT_GROUPS
                ),
                "can_view_analytics": user_in_groups(
                    self.request.user, ANALYTICS_GROUPS
                ),
                "show_technical_admin": self.request.user.is_superuser,
                "counts": {
                    "items": Item.objects.count(),
                    "warehouses": Warehouse.objects.count(),
                    "locations": Location.objects.count(),
                    "users": get_user_model().objects.count(),
                },
            }
        )
        return context


class ManagementDirectoriesView(LoginRequiredMixin, GroupRequiredMixin, TemplateView):
    group_names = DIRECTORY_EDIT_GROUPS
    template_name = "core/management/directories.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["directories"] = [
            {
                "title": _("Номенклатура"),
                "count": Item.objects.count(),
                "url": reverse("item_list"),
            },
            {
                "title": _("Категорії"),
                "count": Category.objects.count(),
                "url": reverse("category_list"),
            },
            {
                "title": _("Одиниці виміру"),
                "count": Unit.objects.count(),
                "url": reverse("unit_list"),
            },
            {
                "title": _("Склади"),
                "count": Warehouse.objects.count(),
                "url": reverse("warehouse_list"),
            },
            {
                "title": _("Локації"),
                "count": Location.objects.count(),
                "url": reverse("location_list"),
            },
            {
                "title": _("Отримувачі"),
                "count": Recipient.objects.count(),
                "url": reverse("recipient_list"),
            },
        ]
        return context


class ManagementUsersView(LoginRequiredMixin, GroupRequiredMixin, TemplateView):
    group_names = USER_MANAGEMENT_GROUPS
    template_name = "core/management/users.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["users"] = (
            get_user_model().objects.prefetch_related("groups").order_by("username")
        )
        context["groups"] = Group.objects.order_by("name")
        return context


class ManagementSettingsView(LoginRequiredMixin, GroupRequiredMixin, TemplateView):
    group_names = USER_MANAGEMENT_GROUPS
    template_name = "core/management/settings.html"


HELP_SECTIONS = [
    {
        "title": _("Як почати склад з нуля"),
        "filename": "START_WAREHOUSE_FROM_ZERO.md",
        "admin_only": True,
    },
    {"title": _("Інструкція користувача"), "filename": "USER_GUIDE.md", "admin_only": False},
    {"title": _("Інструкція адміністратора"), "filename": "ADMIN_GUIDE.md", "admin_only": True},
    {"title": _("Типові помилки"), "filename": "ADMIN_GUIDE.md", "anchor": "Типові помилки", "admin_only": True},
    {"title": _("Backup і відновлення"), "filename": "BACKUP_AND_RESTORE.md", "admin_only": True},
    {"title": _("Принтери і друк етикеток"), "filename": "USER_GUIDE.md", "anchor": "Друк етикеток", "admin_only": True},
    {"title": _("Штрихкоди"), "filename": "USER_GUIDE.md", "anchor": "Штрихкоди", "admin_only": False},
    {"title": _("Прихід товару"), "filename": "USER_GUIDE.md", "anchor": "Прихід товару", "admin_only": False},
    {"title": _("Початковий залишок"), "filename": "USER_GUIDE.md", "anchor": "Початковий залишок", "admin_only": False},
    {"title": _("Рухи товарів"), "filename": "USER_GUIDE.md", "anchor": "Рухи товарів", "admin_only": False},
]


def render_markdown_document(filename):
    document_path = settings.BASE_DIR / "docs" / filename
    if not document_path.exists():
        return format_html("<p class='text-muted'>{}</p>", _("Документ ще не додано."))
    text = document_path.read_text(encoding="utf-8")
    return mark_safe(linebreaks(urlize(text)))


class HelpView(LoginRequiredMixin, TemplateView):
    template_name = "core/management/help.html"
    management_mode = False

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        sections = HELP_SECTIONS if self.management_mode else [HELP_SECTIONS[1]]
        context.update(
            {
                "management_mode": self.management_mode,
                "help_sections": [
                    {
                        **section,
                        "content": render_markdown_document(section["filename"]),
                    }
                    for section in sections
                ],
            }
        )
        return context


class ManagementHelpView(GroupRequiredMixin, HelpView):
    group_names = MANAGEMENT_GROUPS
    management_mode = True


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
