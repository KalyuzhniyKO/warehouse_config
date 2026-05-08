from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.forms.models import model_to_dict
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.urls import reverse, reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, ListView, TemplateView, UpdateView, View

from .forms import (
    CategoryForm,
    ItemForm,
    LocationForm,
    RecipientForm,
    StockBalanceFilterForm,
    UnitForm,
    WarehouseForm,
)
from .models import Category, Item, Location, Recipient, StockBalance, Unit, Warehouse


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


class DirectoryCreateView(LoginRequiredMixin, DirectoryConfigMixin, CreateView):
    template_name = "core/directory_form.html"

    def form_valid(self, form):
        messages.success(self.request, _("Запис успішно створено."))
        return super().form_valid(form)


class DirectoryUpdateView(LoginRequiredMixin, DirectoryConfigMixin, UpdateView):
    template_name = "core/directory_form.html"

    def form_valid(self, form):
        messages.success(self.request, _("Запис успішно оновлено."))
        return super().form_valid(form)


class DirectoryArchiveView(LoginRequiredMixin, DirectoryConfigMixin, View):
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


class DirectoryRestoreView(LoginRequiredMixin, DirectoryConfigMixin, View):
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
