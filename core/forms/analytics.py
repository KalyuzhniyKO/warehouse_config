from django import forms
from django.utils.translation import gettext_lazy as _

from core.models import Location, StockMovement, Warehouse


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
        super().__init__(*args, **kwargs)
        self.initial.setdefault("period", "30d")
        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-select")
            else:
                field.widget.attrs.setdefault("class", "form-control")
