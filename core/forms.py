from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Category, Item, Location, Recipient, Unit, Warehouse


class BootstrapModelForm(forms.ModelForm):
    """Model form base class with Bootstrap-friendly widgets."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(widget, forms.Textarea):
                widget.attrs.setdefault("class", "form-control")
                widget.attrs.setdefault("rows", 3)
            else:
                widget.attrs.setdefault("class", "form-control")


class UnitForm(BootstrapModelForm):
    class Meta:
        model = Unit
        fields = ["name", "symbol", "is_active"]


class CategoryForm(BootstrapModelForm):
    class Meta:
        model = Category
        fields = ["name", "parent", "is_active"]


class RecipientForm(BootstrapModelForm):
    class Meta:
        model = Recipient
        fields = ["name", "contact_name", "phone", "email", "notes", "is_active"]


class ItemForm(BootstrapModelForm):
    class Meta:
        model = Item
        fields = ["name", "internal_code", "category", "unit", "description", "is_active"]


class WarehouseForm(BootstrapModelForm):
    class Meta:
        model = Warehouse
        fields = ["name", "address", "is_active"]


class LocationForm(BootstrapModelForm):
    class Meta:
        model = Location
        fields = ["warehouse", "name", "location_type", "is_active"]


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
        widget=forms.TextInput(
            attrs={"placeholder": _("Назва, внутрішній код або штрихкод")}
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
