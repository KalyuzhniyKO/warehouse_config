from django import forms
from django.utils.translation import gettext_lazy as _

from core.models import Location, StockMovement, Warehouse
from core.services.warehouse_access import (
    get_accessible_warehouses,
    get_single_accessible_warehouse_or_none,
)


def active_warehouses_for_form_user(user):
    if user is None:
        return Warehouse.objects.filter(is_active=True)
    return get_accessible_warehouses(user)


class AnalyticsFilterForm(forms.Form):
    period = forms.ChoiceField(
        label=_("Період"),
        choices=[
            ("today", _("Сьогодні")),
            ("7d", _("7 днів")),
            ("30d", _("30 днів")),
            ("month", _("Поточний місяць")),
            ("custom", _("Довільний")),
        ],
        required=False,
    )
    date_from = forms.DateField(label=_("Дата від"), required=False, widget=forms.DateInput(attrs={"type": "date"}))
    date_to = forms.DateField(label=_("Дата до"), required=False, widget=forms.DateInput(attrs={"type": "date"}))
    warehouse = forms.ModelChoiceField(label=_("Склад"), queryset=Warehouse.objects.filter(is_active=True), required=False)
    location = forms.ModelChoiceField(label=_("Цех / місце використання"), queryset=Location.objects.filter(is_active=True).select_related("warehouse"), required=False)
    movement_type = forms.ChoiceField(label=_("Тип операції"), choices=[("", _("Усі операції"))] + list(StockMovement.MovementType.choices), required=False)

    def __init__(self, *args, **kwargs):
        self.request_user = kwargs.pop("user", kwargs.pop("request_user", None))
        super().__init__(*args, **kwargs)
        self.initial.setdefault("period", "30d")
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
