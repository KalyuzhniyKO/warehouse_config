from django import forms
from django.utils.translation import gettext_lazy as _

from core.forms.base import (
    ARCHIVED_CHOICE_ERROR,
    DUPLICATE_MESSAGES,
    BootstrapModelForm,
    active_queryset,
    current_related,
    is_current_relation,
    normalize_text,
    normalized_duplicate_exists,
    set_active_model_choice,
)
from core.models import (
    Category,
    Item,
    Location,
    Recipient,
    StockBalance,
    StockMovement,
    Unit,
    Warehouse,
)


class UnitForm(BootstrapModelForm):
    class Meta:
        model = Unit
        fields = ["name", "symbol", "is_active"]
        labels = {
            "name": _("Назва"),
            "symbol": _("Позначення"),
            "is_active": _("Активний"),
        }
        help_texts = {"symbol": _("Коротке позначення одиниці, наприклад: шт, кг, м.")}

    def clean_name(self):
        name = self.clean_normalized_char("name")
        if normalized_duplicate_exists(Unit.objects.all(), self.instance, "name", name):
            raise forms.ValidationError(DUPLICATE_MESSAGES["unit_name"])
        return name

    def clean_symbol(self):
        symbol = self.clean_normalized_char("symbol")
        if normalized_duplicate_exists(
            Unit.objects.all(), self.instance, "symbol", symbol
        ):
            raise forms.ValidationError(DUPLICATE_MESSAGES["unit_symbol"])
        return symbol


class CategoryForm(BootstrapModelForm):
    class Meta:
        model = Category
        fields = ["name", "parent", "is_active"]
        labels = {
            "name": _("Назва"),
            "parent": _("Батьківська категорія"),
            "is_active": _("Активний"),
        }
        help_texts = {"parent": _("Залиште порожнім для категорії верхнього рівня.")}

    def __init__(self, *args, include_current_relations=False, **kwargs):
        self.include_current_relations = include_current_relations
        super().__init__(*args, **kwargs)
        include = (
            current_related(self.instance, "parent")
            if include_current_relations
            else None
        )
        queryset = active_queryset(Category, include=include)
        if self.instance and self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        set_active_model_choice(self, "parent", queryset)

    def clean_name(self):
        return self.clean_normalized_char("name")

    def clean(self):
        cleaned_data = super().clean()
        name = cleaned_data.get("name")
        parent = cleaned_data.get("parent")
        if (
            parent
            and not parent.is_active
            and not is_current_relation(self, "parent", parent)
        ):
            self.add_error("parent", ARCHIVED_CHOICE_ERROR)
        if (
            parent
            and self.instance
            and self.instance.pk
            and parent.pk == self.instance.pk
        ):
            self.add_error(
                "parent", _("Категорія не може бути батьківською для самої себе.")
            )
        if name:
            queryset = (
                Category.objects.filter(parent__isnull=True)
                if parent is None
                else Category.objects.filter(parent=parent)
            )
            if normalized_duplicate_exists(queryset, self.instance, "name", name):
                self.add_error("name", DUPLICATE_MESSAGES["category"])
        return cleaned_data


class RecipientForm(BootstrapModelForm):
    class Meta:
        model = Recipient
        fields = ["name", "contact_name", "phone", "email", "notes", "is_active"]
        labels = {
            "name": _("Назва"),
            "contact_name": _("Контактна особа"),
            "phone": _("Телефон"),
            "email": _("Email"),
            "notes": _("Примітки"),
            "is_active": _("Активний"),
        }
        help_texts = {"notes": _("Додаткова інформація про отримувача.")}

    def clean_name(self):
        name = self.clean_normalized_char("name")
        if normalized_duplicate_exists(
            Recipient.objects.all(), self.instance, "name", name
        ):
            raise forms.ValidationError(DUPLICATE_MESSAGES["recipient"])
        return name


class ItemForm(BootstrapModelForm):
    class Meta:
        model = Item
        fields = [
            "name",
            "internal_code",
            "category",
            "unit",
            "description",
            "is_active",
        ]
        labels = {
            "name": _("Назва"),
            "internal_code": _("Внутрішній код"),
            "category": _("Категорія"),
            "unit": _("Одиниця виміру"),
            "description": _("Опис"),
            "is_active": _("Активний"),
        }
        help_texts = {
            "internal_code": _("Необов'язковий унікальний код у вашій системі обліку.")
        }

    def __init__(self, *args, include_current_relations=False, **kwargs):
        self.include_current_relations = include_current_relations
        super().__init__(*args, **kwargs)
        category = (
            current_related(self.instance, "category")
            if include_current_relations
            else None
        )
        unit = (
            current_related(self.instance, "unit")
            if include_current_relations
            else None
        )
        set_active_model_choice(
            self, "category", active_queryset(Category, include=category)
        )
        set_active_model_choice(self, "unit", active_queryset(Unit, include=unit))

    def clean_category(self):
        category = self.cleaned_data.get("category")
        if (
            category
            and not category.is_active
            and not is_current_relation(self, "category", category)
        ):
            raise forms.ValidationError(ARCHIVED_CHOICE_ERROR)
        return category

    def clean_unit(self):
        unit = self.cleaned_data.get("unit")
        if unit and not unit.is_active and not is_current_relation(self, "unit", unit):
            raise forms.ValidationError(ARCHIVED_CHOICE_ERROR)
        return unit

    def clean_name(self):
        return self.clean_normalized_char("name")

    def clean_internal_code(self):
        code = normalize_text(self.cleaned_data.get("internal_code"))
        if not code:
            return None
        if normalized_duplicate_exists(
            Item.objects.exclude(internal_code__isnull=True).exclude(internal_code=""),
            self.instance,
            "internal_code",
            code,
        ):
            raise forms.ValidationError(DUPLICATE_MESSAGES["item_code"])
        return code


class WarehouseForm(BootstrapModelForm):
    class Meta:
        model = Warehouse
        fields = ["name", "address", "is_active"]
        labels = {
            "name": _("Назва"),
            "address": _("Адреса"),
            "is_active": _("Активний"),
        }
        help_texts = {
            "address": _("Фактична адреса або короткий опис місця розташування складу.")
        }

    def clean_name(self):
        name = self.clean_normalized_char("name")
        if normalized_duplicate_exists(
            Warehouse.objects.all(), self.instance, "name", name
        ):
            raise forms.ValidationError(DUPLICATE_MESSAGES["warehouse"])
        return name


class LocationForm(BootstrapModelForm):
    class Meta:
        model = Location
        fields = ["warehouse", "name", "location_type", "is_active"]
        labels = {
            "warehouse": _("Склад"),
            "name": _("Назва"),
            "location_type": _("Тип локації"),
            "is_active": _("Активний"),
        }
        help_texts = {"name": _("Наприклад: A-01, Ряд 2, Комірка 5.")}

    def __init__(self, *args, include_current_relations=False, **kwargs):
        self.include_current_relations = include_current_relations
        super().__init__(*args, **kwargs)
        warehouse = (
            current_related(self.instance, "warehouse")
            if include_current_relations
            else None
        )
        set_active_model_choice(
            self, "warehouse", active_queryset(Warehouse, include=warehouse)
        )

    def clean_warehouse(self):
        warehouse = self.cleaned_data.get("warehouse")
        if (
            warehouse
            and not warehouse.is_active
            and not is_current_relation(self, "warehouse", warehouse)
        ):
            raise forms.ValidationError(ARCHIVED_CHOICE_ERROR)
        return warehouse

    def clean_name(self):
        return self.clean_normalized_char("name")

    def clean(self):
        cleaned_data = super().clean()
        name = cleaned_data.get("name")
        warehouse = cleaned_data.get("warehouse")
        if (
            name
            and warehouse
            and normalized_duplicate_exists(
                Location.objects.filter(warehouse=warehouse),
                self.instance,
                "name",
                name,
            )
        ):
            self.add_error("name", DUPLICATE_MESSAGES["location"])
        return cleaned_data


class StockBalanceAdminForm(BootstrapModelForm):
    class Meta:
        model = StockBalance
        fields = "__all__"

    def __init__(self, *args, include_current_relations=False, **kwargs):
        self.include_current_relations = include_current_relations
        super().__init__(*args, **kwargs)
        item = (
            current_related(self.instance, "item")
            if include_current_relations
            else None
        )
        location = (
            current_related(self.instance, "location")
            if include_current_relations
            else None
        )
        set_active_model_choice(self, "item", active_queryset(Item, include=item))
        set_active_model_choice(
            self,
            "location",
            active_queryset(Location, include=location, warehouse__is_active=True),
        )


class StockMovementAdminForm(BootstrapModelForm):
    class Meta:
        model = StockMovement
        fields = "__all__"

    def __init__(self, *args, include_current_relations=False, **kwargs):
        self.include_current_relations = include_current_relations
        super().__init__(*args, **kwargs)
        item = (
            current_related(self.instance, "item")
            if include_current_relations
            else None
        )
        source_location = (
            current_related(self.instance, "source_location")
            if include_current_relations
            else None
        )
        destination_location = (
            current_related(self.instance, "destination_location")
            if include_current_relations
            else None
        )
        recipient = (
            current_related(self.instance, "recipient")
            if include_current_relations
            else None
        )
        active_locations = active_queryset(Location, warehouse__is_active=True)
        set_active_model_choice(self, "item", active_queryset(Item, include=item))
        set_active_model_choice(
            self,
            "source_location",
            (
                active_queryset(
                    Location, include=source_location, warehouse__is_active=True
                )
                if source_location
                else active_locations
            ),
        )
        set_active_model_choice(
            self,
            "destination_location",
            (
                active_queryset(
                    Location, include=destination_location, warehouse__is_active=True
                )
                if destination_location
                else active_locations
            ),
        )
        set_active_model_choice(
            self, "recipient", active_queryset(Recipient, include=recipient)
        )
