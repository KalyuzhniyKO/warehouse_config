from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from core.forms.base import BootstrapModelForm
from core.models import PurchaseRequest


class PurchaseRequestForm(BootstrapModelForm):
    class Meta:
        model = PurchaseRequest
        fields = [
            "title",
            "description",
            "requested_qty",
            "unit",
            "estimated_unit_price",
            "currency",
            "supplier_name",
            "supplier_url",
            "comment",
        ]
        widgets = {
            "requested_qty": forms.NumberInput(attrs={"min": "0.001", "step": "0.001"}),
            "estimated_unit_price": forms.NumberInput(attrs={"min": "0", "step": "0.01"}),
        }


class PurchaseRequestFilterForm(forms.Form):
    status = forms.ChoiceField(
        label=_("Статус"),
        choices=[("", _("Усі статуси"))] + list(PurchaseRequest.Status.choices),
        required=False,
    )
    requested_by = forms.ModelChoiceField(
        label=_("Заявник"),
        queryset=get_user_model().objects.none(),
        required=False,
    )
    date_from = forms.DateField(
        label=_("Дата від"),
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    date_to = forms.DateField(
        label=_("Дата до"),
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    q = forms.CharField(
        label=_("Пошук"),
        required=False,
        widget=forms.TextInput(
            attrs={"placeholder": _("Назва, товар або постачальник")}
        ),
    )

    def __init__(self, *args, **kwargs):
        users = kwargs.pop("users", get_user_model().objects.none())
        super().__init__(*args, **kwargs)
        self.fields["requested_by"].queryset = users
        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-select")
            else:
                field.widget.attrs.setdefault("class", "form-control")
