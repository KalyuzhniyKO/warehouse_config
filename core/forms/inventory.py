from django import forms
from django.utils.translation import gettext_lazy as _

from core.forms.base import ARCHIVED_CHOICE_ERROR, BootstrapModelForm
from core.models import InventoryCountLine, Item, Location, Warehouse


class InventoryCountCreateForm(forms.Form):
    warehouse = forms.ModelChoiceField(label=_("Склад"), queryset=Warehouse.objects.none())
    location = forms.ModelChoiceField(
        label=_("Локація"),
        queryset=Location.objects.none(),
        required=False,
    )
    comment = forms.CharField(
        label=_("Коментар"), required=False, widget=forms.Textarea(attrs={"rows": 3})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["warehouse"].queryset = Warehouse.objects.filter(is_active=True)
        self.fields["location"].queryset = Location.objects.filter(
            is_active=True, warehouse__is_active=True
        ).select_related("warehouse")
        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-select")
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


class InventoryCountLineForm(BootstrapModelForm):
    actual_qty = forms.DecimalField(
        label=_("Фактична кількість"),
        max_digits=18,
        decimal_places=3,
        required=False,
    )

    class Meta:
        model = InventoryCountLine
        fields = ["actual_qty", "comment"]
        labels = {
            "actual_qty": _("Фактична кількість"),
            "comment": _("Коментар"),
        }
        widgets = {"comment": forms.Textarea(attrs={"rows": 1})}
