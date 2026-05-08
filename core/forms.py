from django import forms
from django.utils.translation import gettext_lazy as _

from .models import (
    Category,
    Item,
    Location,
    Recipient,
    LabelTemplate,
    Printer,
    StockBalance,
    StockMovement,
    Unit,
    Warehouse,
)

ARCHIVED_CHOICE_ERROR = _("Не можна вибрати архівний запис.")


def active_queryset(model, include=None, **filters):
    queryset = model.objects.filter(is_active=True, **filters)
    if include is not None and getattr(include, "pk", None):
        queryset = model.objects.filter(pk=include.pk) | queryset
    return queryset.distinct()


def set_active_model_choice(form, field_name, queryset):
    field = form.fields[field_name]
    field.queryset = queryset
    field.error_messages["invalid_choice"] = ARCHIVED_CHOICE_ERROR


def current_related(instance, field_name):
    if instance and getattr(instance, "pk", None):
        return getattr(instance, field_name, None)
    return None


def is_current_relation(form, field_name, obj):
    current = current_related(form.instance, field_name)
    return bool(
        getattr(form, "include_current_relations", False)
        and obj
        and current
        and obj.pk == current.pk
    )


DUPLICATE_MESSAGES = {
    "category": _("Категорія з такою назвою вже існує."),
    "unit_name": _("Одиниця виміру з такою назвою вже існує."),
    "unit_symbol": _("Одиниця виміру з таким позначенням вже існує."),
    "recipient": _("Отримувач з такою назвою вже існує."),
    "warehouse": _("Склад з такою назвою вже існує."),
    "location": _("Локація з такою назвою вже існує на цьому складі."),
    "item_code": _("Номенклатура з таким внутрішнім кодом вже існує."),
}


def normalize_text(value):
    return (value or "").strip()


def normalized_duplicate_exists(queryset, instance, field_name, value):
    normalized = normalize_text(value).casefold()
    if instance and instance.pk:
        queryset = queryset.exclude(pk=instance.pk)
    for obj in queryset.filter(is_active=True):
        if normalize_text(getattr(obj, field_name)).casefold() == normalized:
            return True
    return False


class BootstrapModelForm(forms.ModelForm):
    """Model form base class with Bootstrap-friendly widgets."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(widget, forms.Select):
                widget.attrs.setdefault("class", "form-select")
            elif isinstance(widget, forms.Textarea):
                widget.attrs.setdefault("class", "form-control")
                widget.attrs.setdefault("rows", 3)
            else:
                widget.attrs.setdefault("class", "form-control")

    def clean_normalized_char(self, field_name):
        value = normalize_text(self.cleaned_data.get(field_name))
        self.cleaned_data[field_name] = value
        return value


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


class StockBalanceFilterForm(forms.Form):
    warehouse = forms.ModelChoiceField(
        label=_("Склад"),
        queryset=Warehouse.objects.filter(is_active=True),
        required=False,
    )
    location = forms.ModelChoiceField(
        label=_("Локація"),
        queryset=Location.objects.filter(
            is_active=True, warehouse__is_active=True
        ).select_related("warehouse"),
        required=False,
    )
    item = forms.ModelChoiceField(
        label=_("Номенклатура"),
        queryset=Item.objects.filter(is_active=True),
        required=False,
    )
    q = forms.CharField(
        label=_("Пошук"),
        required=False,
        widget=forms.TextInput(
            attrs={"placeholder": _("Назва, внутрішній код або штрихкод")}
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-select")
            else:
                field.widget.attrs.setdefault("class", "form-control")


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


class AnalyticsFilterForm(forms.Form):
    date_from = forms.DateField(
        label=_("Період від"),
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    date_to = forms.DateField(
        label=_("Період до"),
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    warehouse = forms.ModelChoiceField(
        label=_("Склад"),
        queryset=Warehouse.objects.filter(is_active=True),
        required=False,
    )
    location = forms.ModelChoiceField(
        label=_("Локація"),
        queryset=Location.objects.filter(
            is_active=True, warehouse__is_active=True
        ).select_related("warehouse"),
        required=False,
    )
    category = forms.ModelChoiceField(
        label=_("Категорія"),
        queryset=Category.objects.filter(is_active=True),
        required=False,
    )
    item = forms.ModelChoiceField(
        label=_("Номенклатура"),
        queryset=Item.objects.filter(is_active=True),
        required=False,
    )
    movement_type = forms.ChoiceField(
        label=_("Тип операції"),
        choices=[("", _("Усі операції"))] + list(StockMovement.MovementType.choices),
        required=False,
    )
    recipient = forms.ModelChoiceField(
        label=_("Отримувач"),
        queryset=Recipient.objects.filter(is_active=True),
        required=False,
    )
    q = forms.CharField(
        label=_("Пошук"),
        required=False,
        widget=forms.TextInput(
            attrs={"placeholder": _("Назва, internal_code або barcode")}
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-select")
            else:
                field.widget.attrs.setdefault("class", "form-control")


class StockOperationForm(forms.Form):
    item = forms.ModelChoiceField(label=_("Номенклатура"), queryset=Item.objects.none())
    warehouse = forms.ModelChoiceField(label=_("Склад"), queryset=Warehouse.objects.none())
    location = forms.ModelChoiceField(label=_("Локація"), queryset=Location.objects.none())
    qty = forms.DecimalField(label=_("Кількість"), min_value=0, max_digits=18, decimal_places=3)
    comment = forms.CharField(
        label=_("Коментар"), required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    occurred_at = forms.DateTimeField(
        label=_("Дата операції"),
        required=True,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["item"].queryset = Item.objects.filter(is_active=True).select_related("unit")
        self.fields["warehouse"].queryset = Warehouse.objects.filter(is_active=True)
        self.fields["location"].queryset = Location.objects.filter(
            is_active=True, warehouse__is_active=True
        ).select_related("warehouse")
        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-select")
            elif isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-check-input")
            else:
                field.widget.attrs.setdefault("class", "form-control")

    def clean_location(self):
        location = self.cleaned_data.get("location")
        if location and (not location.is_active or not location.warehouse.is_active):
            raise forms.ValidationError(ARCHIVED_CHOICE_ERROR)
        return location

    def clean(self):
        cleaned_data = super().clean()
        warehouse = cleaned_data.get("warehouse")
        location = cleaned_data.get("location")
        if warehouse and location and location.warehouse_id != warehouse.pk:
            self.add_error("location", _("Локація має належати вибраному складу."))
        return cleaned_data


class StockReceiveForm(StockOperationForm):
    print_label = forms.BooleanField(
        label=_("Надрукувати етикетку після збереження"), required=False
    )


class InitialBalanceForm(StockOperationForm):
    pass


class StockMovementFilterForm(forms.Form):
    movement_type = forms.ChoiceField(
        label=_("Тип операції"),
        choices=[("", _("Усі операції"))] + list(StockMovement.MovementType.choices),
        required=False,
    )
    item = forms.ModelChoiceField(label=_("Номенклатура"), queryset=Item.objects.filter(is_active=True), required=False)
    warehouse = forms.ModelChoiceField(label=_("Склад"), queryset=Warehouse.objects.filter(is_active=True), required=False)
    location = forms.ModelChoiceField(
        label=_("Локація"),
        queryset=Location.objects.filter(is_active=True, warehouse__is_active=True).select_related("warehouse"),
        required=False,
    )
    date_from = forms.DateField(label=_("Дата від"), required=False, widget=forms.DateInput(attrs={"type": "date"}))
    date_to = forms.DateField(label=_("Дата до"), required=False, widget=forms.DateInput(attrs={"type": "date"}))
    q = forms.CharField(
        label=_("Пошук"),
        required=False,
        widget=forms.TextInput(attrs={"placeholder": _("Назва, internal_code або barcode")}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-select")
            else:
                field.widget.attrs.setdefault("class", "form-control")


class PrinterForm(BootstrapModelForm):
    class Meta:
        model = Printer
        fields = ["name", "system_name", "description", "is_default", "is_active"]
        labels = {
            "name": _("Назва"),
            "system_name": _("Системна назва"),
            "description": _("Опис"),
            "is_default": _("За замовчуванням"),
            "is_active": _("Активний"),
        }


class LabelTemplateForm(BootstrapModelForm):
    class Meta:
        model = LabelTemplate
        fields = [
            "name",
            "width_mm",
            "height_mm",
            "show_item_name",
            "show_internal_code",
            "show_barcode_text",
            "barcode_type",
            "is_default",
            "is_active",
        ]
        labels = {
            "name": _("Назва"),
            "width_mm": _("Ширина, мм"),
            "height_mm": _("Висота, мм"),
            "show_item_name": _("Показувати назву товару"),
            "show_internal_code": _("Показувати внутрішній код"),
            "show_barcode_text": _("Показувати текст штрихкоду"),
            "barcode_type": _("Тип штрихкоду"),
            "is_default": _("За замовчуванням"),
            "is_active": _("Активний"),
        }


class PrintLabelForm(forms.Form):
    printer = forms.ModelChoiceField(label=_("Принтер"), queryset=Printer.objects.none())
    label_template = forms.ModelChoiceField(label=_("Шаблон"), queryset=LabelTemplate.objects.none())
    copies = forms.IntegerField(label=_("Кількість копій"), min_value=1, initial=1)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["printer"].queryset = Printer.objects.filter(is_active=True).order_by("-is_default", "name")
        self.fields["label_template"].queryset = LabelTemplate.objects.filter(is_active=True).order_by("-is_default", "name")
        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-select")
            else:
                field.widget.attrs.setdefault("class", "form-control")
