from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Category, Item, Location, Recipient, StockMovement, Unit, Warehouse


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
        labels = {"name": _("Назва"), "symbol": _("Позначення"), "is_active": _("Активний")}
        help_texts = {"symbol": _("Коротке позначення одиниці, наприклад: шт, кг, м.")}

    def clean_name(self):
        name = self.clean_normalized_char("name")
        if normalized_duplicate_exists(Unit.objects.all(), self.instance, "name", name):
            raise forms.ValidationError(DUPLICATE_MESSAGES["unit_name"])
        return name

    def clean_symbol(self):
        symbol = self.clean_normalized_char("symbol")
        if normalized_duplicate_exists(Unit.objects.all(), self.instance, "symbol", symbol):
            raise forms.ValidationError(DUPLICATE_MESSAGES["unit_symbol"])
        return symbol


class CategoryForm(BootstrapModelForm):
    class Meta:
        model = Category
        fields = ["name", "parent", "is_active"]
        labels = {"name": _("Назва"), "parent": _("Батьківська категорія"), "is_active": _("Активний")}
        help_texts = {"parent": _("Залиште порожнім для категорії верхнього рівня.")}

    def clean_name(self):
        return self.clean_normalized_char("name")

    def clean(self):
        cleaned_data = super().clean()
        name = cleaned_data.get("name")
        parent = cleaned_data.get("parent")
        if name:
            queryset = Category.objects.filter(parent__isnull=True) if parent is None else Category.objects.filter(parent=parent)
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
        if normalized_duplicate_exists(Recipient.objects.all(), self.instance, "name", name):
            raise forms.ValidationError(DUPLICATE_MESSAGES["recipient"])
        return name


class ItemForm(BootstrapModelForm):
    class Meta:
        model = Item
        fields = ["name", "internal_code", "category", "unit", "description", "is_active"]
        labels = {
            "name": _("Назва"),
            "internal_code": _("Внутрішній код"),
            "category": _("Категорія"),
            "unit": _("Одиниця виміру"),
            "description": _("Опис"),
            "is_active": _("Активний"),
        }
        help_texts = {"internal_code": _("Необов'язковий унікальний код у вашій системі обліку.")}

    def clean_name(self):
        return self.clean_normalized_char("name")

    def clean_internal_code(self):
        code = normalize_text(self.cleaned_data.get("internal_code"))
        if not code:
            return None
        if normalized_duplicate_exists(Item.objects.exclude(internal_code__isnull=True).exclude(internal_code=""), self.instance, "internal_code", code):
            raise forms.ValidationError(DUPLICATE_MESSAGES["item_code"])
        return code


class WarehouseForm(BootstrapModelForm):
    class Meta:
        model = Warehouse
        fields = ["name", "address", "is_active"]
        labels = {"name": _("Назва"), "address": _("Адреса"), "is_active": _("Активний")}
        help_texts = {"address": _("Фактична адреса або короткий опис місця розташування складу.")}

    def clean_name(self):
        name = self.clean_normalized_char("name")
        if normalized_duplicate_exists(Warehouse.objects.all(), self.instance, "name", name):
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

    def clean_name(self):
        return self.clean_normalized_char("name")

    def clean(self):
        cleaned_data = super().clean()
        name = cleaned_data.get("name")
        warehouse = cleaned_data.get("warehouse")
        if name and warehouse and normalized_duplicate_exists(
            Location.objects.filter(warehouse=warehouse), self.instance, "name", name
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
        queryset=Location.objects.filter(is_active=True).select_related("warehouse"),
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
        widget=forms.TextInput(attrs={"placeholder": _("Назва, внутрішній код або штрихкод")}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-select")
            else:
                field.widget.attrs.setdefault("class", "form-control")


class AnalyticsFilterForm(forms.Form):
    date_from = forms.DateField(
        label=_("Період від"), required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    date_to = forms.DateField(
        label=_("Період до"), required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    warehouse = forms.ModelChoiceField(label=_("Склад"), queryset=Warehouse.objects.filter(is_active=True), required=False)
    location = forms.ModelChoiceField(
        label=_("Локація"), queryset=Location.objects.filter(is_active=True).select_related("warehouse"), required=False
    )
    category = forms.ModelChoiceField(label=_("Категорія"), queryset=Category.objects.filter(is_active=True), required=False)
    item = forms.ModelChoiceField(label=_("Номенклатура"), queryset=Item.objects.filter(is_active=True), required=False)
    movement_type = forms.ChoiceField(
        label=_("Тип операції"), choices=[("", _("Усі операції"))] + list(StockMovement.MovementType.choices), required=False
    )
    recipient = forms.ModelChoiceField(label=_("Отримувач"), queryset=Recipient.objects.filter(is_active=True), required=False)
    q = forms.CharField(
        label=_("Пошук"), required=False, widget=forms.TextInput(attrs={"placeholder": _("Назва, internal_code або barcode")})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-select")
            else:
                field.widget.attrs.setdefault("class", "form-control")
