from django import forms
from django.utils.translation import gettext_lazy as _

from core.models import Item, Location, StockMovement, Warehouse


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
    issue_reason = forms.ChoiceField(
        label=_("Тип видачі"),
        choices=[("", _("Усі типи видачі"))] + list(StockMovement.IssueReason.choices),
        required=False,
    )
    department = forms.CharField(label=_("Цех / підрозділ"), required=False)
    document_number = forms.CharField(label=_("Номер документа"), required=False)
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
