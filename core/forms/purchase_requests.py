from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from core.forms.base import BootstrapModelForm
from core.models import PurchaseRequest


class PurchaseRequestForm(BootstrapModelForm):
    class Meta:
        model = PurchaseRequest
        fields = [
            "request_date",
            "title",
            "need_description",
            "requested_qty",
            "unit",
            "unit_price_uah",
            "order_type",
            "product_url",
            "comment",
        ]
        widgets = {
            "request_date": forms.DateInput(attrs={"type": "date"}),
            "requested_qty": forms.NumberInput(attrs={"min": "0.001", "step": "0.001"}),
            "unit_price_uah": forms.NumberInput(attrs={"min": "0", "step": "0.01"}),
        }


class PurchaseRequestManagerForm(PurchaseRequestForm):
    class Meta(PurchaseRequestForm.Meta):
        fields = [
            *PurchaseRequestForm.Meta.fields,
            "approval_status",
            "payment_status",
            "delivery_status",
        ]


class PurchaseRequestFilterForm(forms.Form):
    order_type = forms.ChoiceField(
        label=_("Тип замовлення"),
        choices=[("", _("Усі типи замовлень"))] + list(PurchaseRequest.OrderType.choices),
        required=False,
    )
    approval_status = forms.ChoiceField(
        label=_("Статус погодження"),
        choices=[("", _("Усі статуси погодження"))]
        + list(PurchaseRequest.ApprovalStatus.choices),
        required=False,
    )
    payment_status = forms.ChoiceField(
        label=_("Статус оплати"),
        choices=[("", _("Усі статуси оплати"))]
        + list(PurchaseRequest.PaymentStatus.choices),
        required=False,
    )
    delivery_status = forms.ChoiceField(
        label=_("Статус доставки"),
        choices=[("", _("Усі статуси доставки"))]
        + list(PurchaseRequest.DeliveryStatus.choices),
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
            attrs={"placeholder": _("Назва, опис потреби або посилання")}
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
