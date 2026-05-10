from django import forms
from django.utils.translation import gettext_lazy as _

from core.models import Category, Item, Location, Recipient, StockMovement, Warehouse


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
