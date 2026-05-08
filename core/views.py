import csv
import json

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.mixins import LoginRequiredMixin
from django.forms.models import model_to_dict
from django.db.models import Q
from django.http import HttpResponse, HttpResponseRedirect
from django.urls import reverse, reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, ListView, TemplateView, UpdateView, View

from .forms import (
    AnalyticsFilterForm,
    CategoryForm,
    ItemForm,
    LocationForm,
    RecipientForm,
    StockBalanceFilterForm,
    UnitForm,
    WarehouseForm,
)
from .models import Category, Item, Location, Recipient, StockBalance, StockMovement, Unit, Warehouse
from .permissions import (
    ANALYTICS_GROUPS,
    DIRECTORY_EDIT_GROUPS,
    USER_MANAGEMENT_GROUPS,
    GroupRequiredMixin,
    user_in_groups,
)
from .services import analytics as analytics_service


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


class DirectoryListView(LoginRequiredMixin, DirectoryConfigMixin, ActiveDirectoryQuerysetMixin, ListView):
    template_name = "core/directory_list.html"
    context_object_name = "objects"
    paginate_by = 50

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        status = self.request.GET.get("status", "active")
        context["current_status"] = status if status in {"active", "archived", "all"} else "active"
        context["search_query"] = self.request.GET.get("q", "").strip()
        return context


class DirectoryCreateView(LoginRequiredMixin, GroupRequiredMixin, DirectoryConfigMixin, CreateView):
    group_names = DIRECTORY_EDIT_GROUPS
    template_name = "core/directory_form.html"

    def form_valid(self, form):
        messages.success(self.request, _("Запис успішно створено."))
        return super().form_valid(form)


class DirectoryUpdateView(LoginRequiredMixin, GroupRequiredMixin, DirectoryConfigMixin, UpdateView):
    group_names = DIRECTORY_EDIT_GROUPS
    template_name = "core/directory_form.html"

    def form_valid(self, form):
        messages.success(self.request, _("Запис успішно оновлено."))
        return super().form_valid(form)


class DirectoryArchiveView(LoginRequiredMixin, GroupRequiredMixin, DirectoryConfigMixin, View):
    group_names = DIRECTORY_EDIT_GROUPS
    def get_blocking_message(self, obj):
        if isinstance(obj, Category):
            if obj.children.filter(is_active=True).exists():
                return _("Категорію не можна архівувати, бо вона має активні дочірні категорії.")
            if obj.items.filter(is_active=True).exists():
                return _("Категорію не можна архівувати, бо вона використовується в активній номенклатурі.")
        elif isinstance(obj, Unit) and obj.items.filter(is_active=True).exists():
            return _("Одиницю виміру не можна архівувати, бо вона використовується в активній номенклатурі.")
        elif isinstance(obj, Warehouse) and obj.locations.filter(is_active=True).exists():
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


class DirectoryRestoreView(LoginRequiredMixin, GroupRequiredMixin, DirectoryConfigMixin, View):
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
            message = first_errors[0] if first_errors else _("Запис не можна відновити.")
            messages.error(request, message)
        return HttpResponseRedirect(reverse(self.list_url_name))


class StockBalanceListView(LoginRequiredMixin, ListView):
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
            .filter(item__is_active=True, location__is_active=True, location__warehouse__is_active=True)
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
        "columns": (("name", _("Назва")), ("contact_name", _("Контакт")), ("phone", _("Телефон"))),
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
        "columns": (("name", _("Назва")), ("internal_code", _("Внутрішній код")), ("category", _("Категорія")), ("unit", _("Одиниця"))),
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
        "columns": (("name", _("Назва")), ("address", _("Адреса"))),
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
        "columns": (("warehouse", _("Склад")), ("name", _("Назва")), ("location_type", _("Тип"))),
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


class ManagementDashboardView(LoginRequiredMixin, TemplateView):
    template_name = "core/management/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "can_manage_users": user_in_groups(self.request.user, USER_MANAGEMENT_GROUPS),
                "can_manage_directories": user_in_groups(self.request.user, DIRECTORY_EDIT_GROUPS),
                "can_view_analytics": user_in_groups(self.request.user, ANALYTICS_GROUPS),
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
            {"title": _("Номенклатура"), "count": Item.objects.count(), "url": reverse("item_list")},
            {"title": _("Категорії"), "count": Category.objects.count(), "url": reverse("category_list")},
            {"title": _("Одиниці виміру"), "count": Unit.objects.count(), "url": reverse("unit_list")},
            {"title": _("Склади"), "count": Warehouse.objects.count(), "url": reverse("warehouse_list")},
            {"title": _("Локації"), "count": Location.objects.count(), "url": reverse("location_list")},
            {"title": _("Отримувачі"), "count": Recipient.objects.count(), "url": reverse("recipient_list")},
        ]
        return context


class ManagementUsersView(LoginRequiredMixin, GroupRequiredMixin, TemplateView):
    group_names = USER_MANAGEMENT_GROUPS
    template_name = "core/management/users.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["users"] = get_user_model().objects.prefetch_related("groups").order_by("username")
        context["groups"] = Group.objects.order_by("name")
        return context


class ManagementSettingsView(LoginRequiredMixin, GroupRequiredMixin, TemplateView):
    group_names = USER_MANAGEMENT_GROUPS
    template_name = "core/management/settings.html"


class HelpView(LoginRequiredMixin, TemplateView):
    template_name = "core/management/help.html"


def clean_analytics_filters(form):
    if form.is_valid():
        return {key: value for key, value in form.cleaned_data.items() if value not in (None, "")}
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
                        "writeoff": [float(row["writeoff_qty"] or 0) for row in movements_by_day],
                    }
                ),
                "type_chart_json": json.dumps(
                    {
                        "labels": [str(StockMovement.MovementType(row["movement_type"]).label) for row in movements_by_type],
                        "values": [float(row["total_qty"] or 0) for row in movements_by_type],
                    }
                ),
                "warehouse_chart_json": json.dumps(
                    {
                        "labels": [row["location__warehouse__name"] or "—" for row in stock_summary["by_warehouse"]],
                        "values": [float(row["total_qty"] or 0) for row in stock_summary["by_warehouse"]],
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


class AnalyticsCSVExportView(LoginRequiredMixin, GroupRequiredMixin, View):
    group_names = ANALYTICS_GROUPS

    def get(self, request, *args, **kwargs):
        form = AnalyticsFilterForm(request.GET or None)
        filters = clean_analytics_filters(form)
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="warehouse-analytics.csv"'
        response.write("\ufeff")
        writer = csv.writer(response)
        writer.writerow([_("Дата"), _("Тип операції"), _("Номенклатура"), _("Кількість"), _("Склад"), _("Локація"), _("Отримувач")])
        for movement in analytics_service.filter_movements(filters).order_by("occurred_at", "id"):
            location = movement.destination_location or movement.source_location
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
            return HttpResponse(_("XLSX експорт недоступний: openpyxl не встановлено."), status=501)
        form = AnalyticsFilterForm(request.GET or None)
        filters = clean_analytics_filters(form)
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Аналітика"
        sheet.append(["Дата", "Тип операції", "Номенклатура", "Кількість", "Склад", "Локація", "Отримувач"])
        for movement in analytics_service.filter_movements(filters).order_by("occurred_at", "id"):
            location = movement.destination_location or movement.source_location
            sheet.append([
                movement.occurred_at.strftime("%Y-%m-%d %H:%M"),
                movement.get_movement_type_display(),
                movement.item.name,
                float(movement.qty),
                location.warehouse.name if location else "",
                location.name if location else "",
                movement.recipient.name if movement.recipient else "",
            ])
        response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response["Content-Disposition"] = 'attachment; filename="warehouse-analytics.xlsx"'
        workbook.save(response)
        return response
