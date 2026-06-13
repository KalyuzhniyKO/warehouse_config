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
    UserWarehouseAccess,
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
from ..services.audit import log_action
from ..services.inventory import (
    InventoryServiceError,
    complete_inventory_count,
    create_inventory_count,
    update_inventory_line_actual_qty,
)
from ..services.labels import download_item_label_pdf, get_default_label_template, print_item_label
from ..services.warehouse_access import (
    get_accessible_warehouses,
    restrict_stock_movement_queryset_for_user,
    restrict_warehouse_queryset_for_user,
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
        if self.model is Warehouse:
            queryset = restrict_warehouse_queryset_for_user(self.request.user, queryset)
        elif self.model is Location:
            queryset = queryset.filter(
                warehouse__in=get_accessible_warehouses(self.request.user)
            )
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


class ItemDetailView(LoginRequiredMixin, TemplateView):
    template_name = "core/item_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        item = get_object_or_404(
            Item.objects.select_related("barcode", "category", "unit"),
            pk=self.kwargs["pk"],
        )
        accessible_warehouses = get_accessible_warehouses(self.request.user)
        balances = StockBalance.objects.filter(
            item=item,
            is_active=True,
            warehouse__in=accessible_warehouses,
        )
        movements = (
            restrict_stock_movement_queryset_for_user(
                self.request.user,
                StockMovement.objects.filter(
                    item=item,
                    is_cancelled=False,
                    reversal_of__isnull=True,
                ),
            )
            .select_related(
                "source_warehouse",
                "destination_warehouse",
                "source_location__warehouse",
                "destination_location__warehouse",
                "recipient",
            )
            .order_by("-occurred_at", "-id")
        )
        stock_by_warehouse = list(
            balances.values("warehouse__name")
            .annotate(total_qty=Sum("qty"))
            .order_by("warehouse__name")
        )
        context.update(
            {
                "item": item,
                "total_stock": balances.aggregate(total=Sum("qty"))["total"] or 0,
                "stock_by_warehouse": stock_by_warehouse,
                "last_receive": movements.filter(
                    movement_type=StockMovement.MovementType.IN
                ).first(),
                "last_issue": movements.filter(
                    movement_type=StockMovement.MovementType.OUT
                ).first(),
                "recent_movements": movements[:20],
            }
        )
        return context


class DirectoryCreateView(
    LoginRequiredMixin, GroupRequiredMixin, DirectoryConfigMixin, CreateView
):
    group_names = DIRECTORY_EDIT_GROUPS
    template_name = "core/directory_form.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if self.model is Location:
            kwargs["request_user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        if isinstance(self.object, Warehouse) and not self.request.user.is_superuser:
            access, created = UserWarehouseAccess.objects.get_or_create(
                user=self.request.user,
                warehouse=self.object,
                defaults={
                    "can_delegate": True,
                    "is_active": True,
                    "created_by": self.request.user,
                },
            )
            if created:
                log_action(
                    self.request.user,
                    "warehouse_access.created",
                    obj=access,
                    changes={
                        "target_user_id": self.request.user.pk,
                        "target_user": self.request.user.get_username(),
                        "warehouse_id": self.object.pk,
                        "warehouse": str(self.object),
                        "can_delegate": True,
                        "actor_id": self.request.user.pk,
                    },
                )
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

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.model is Warehouse:
            return restrict_warehouse_queryset_for_user(self.request.user, queryset)
        if self.model is Location:
            return queryset.filter(
                warehouse__in=get_accessible_warehouses(self.request.user)
            )
        return queryset

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if self.model is Location:
            kwargs["request_user"] = self.request.user
        return kwargs

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
        queryset = self.model.objects.all()
        if self.model is Warehouse:
            queryset = restrict_warehouse_queryset_for_user(request.user, queryset)
        elif self.model is Location:
            queryset = queryset.filter(
                warehouse__in=get_accessible_warehouses(request.user)
            )
        obj = get_object_or_404(queryset, pk=kwargs["pk"])
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
        queryset = self.model.objects.all()
        if self.model is Warehouse:
            queryset = restrict_warehouse_queryset_for_user(request.user, queryset)
        elif self.model is Location:
            queryset = queryset.filter(
                warehouse__in=get_accessible_warehouses(request.user)
            )
        obj = get_object_or_404(queryset, pk=kwargs["pk"])
        data = model_to_dict(obj, fields=self.form_class.Meta.fields)
        data["is_active"] = True
        form_kwargs = {"data": data, "instance": obj}
        if self.model is Location:
            form_kwargs["request_user"] = request.user
        form = self.form_class(**form_kwargs)
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
        "list_title": _("Працівники / отримувачі"),
        "create_title": _("Створити працівника / отримувача"),
        "update_title": _("Редагувати працівника / отримувача"),
        "archive_title": _("Архівувати працівника / отримувача"),
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
        "list_title": _("Товари / матеріали"),
        "create_title": _("Створити товар / матеріал"),
        "update_title": _("Редагувати товар / матеріал"),
        "archive_title": _("Архівувати товар / матеріал"),
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
        "search_fields": ("name", "internal_code", "barcode__barcode"),
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
