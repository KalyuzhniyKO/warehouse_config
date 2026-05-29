from django import forms
from django.utils.translation import gettext_lazy as _

from core.models import Item, Location, Recipient, StockMovement, Warehouse
from core.services.warehouse_access import (
    get_accessible_warehouses,
    get_single_accessible_warehouse_or_none,
)


def active_warehouses_for_form_user(user):
    if user is None:
        return Warehouse.objects.filter(is_active=True)
    return get_accessible_warehouses(user)


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
        self.request_user = kwargs.pop("user", kwargs.pop("request_user", None))
        super().__init__(*args, **kwargs)
        accessible_warehouses = active_warehouses_for_form_user(self.request_user)
        self.fields["warehouse"].queryset = accessible_warehouses
        self.fields["location"].queryset = Location.objects.filter(
            is_active=True,
            warehouse__is_active=True,
            warehouse__in=accessible_warehouses,
        ).select_related("warehouse")
        if not self.is_bound and "warehouse" not in self.initial:
            single_warehouse = get_single_accessible_warehouse_or_none(
                self.request_user
            )
            if single_warehouse is not None:
                self.initial["warehouse"] = single_warehouse
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
    item_id = forms.IntegerField(required=False, widget=forms.HiddenInput())
    recipient = forms.ModelChoiceField(label=_("Отримувач"), queryset=Recipient.objects.filter(is_active=True), required=False)
    recipient_id = forms.IntegerField(required=False, widget=forms.HiddenInput())
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
    usage_place_id = forms.CharField(label=_("Цех / місце використання"), required=False)
    no_document = forms.BooleanField(label=_("Без документа"), required=False)
    missing_recipient = forms.BooleanField(label=_("Без отримувача"), required=False)
    missing_usage_place = forms.BooleanField(label=_("Без цеху"), required=False)
    missing_destination = forms.BooleanField(label=_("Без місця призначення"), required=False)
    invalid_qty = forms.BooleanField(label=_("Некоректна кількість"), required=False)
    document_number = forms.CharField(label=_("Номер документа"), required=False)
    q = forms.CharField(
        label=_("Пошук"),
        required=False,
        widget=forms.TextInput(attrs={"placeholder": _("Назва, internal_code або barcode")}),
    )

    def __init__(self, *args, **kwargs):
        self.request_user = kwargs.pop("user", kwargs.pop("request_user", None))
        super().__init__(*args, **kwargs)
        accessible_warehouses = active_warehouses_for_form_user(self.request_user)
        self.fields["warehouse"].queryset = accessible_warehouses
        self.fields["location"].queryset = Location.objects.filter(
            is_active=True,
            warehouse__is_active=True,
            warehouse__in=accessible_warehouses,
        ).select_related("warehouse")
        if not self.is_bound and "warehouse" not in self.initial:
            single_warehouse = get_single_accessible_warehouse_or_none(
                self.request_user
            )
            if single_warehouse is not None:
                self.initial["warehouse"] = single_warehouse
        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-select")
            else:
                field.widget.attrs.setdefault("class", "form-control")
