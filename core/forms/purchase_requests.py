from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from core.forms.base import BootstrapModelForm
from core.forms.base import normalize_text
from core.forms.units import units_ordered_by_item_usage
from core.models import Item, PurchaseRequest


class PurchaseRequestForm(BootstrapModelForm):
    requested_item = forms.CharField(label=_("Назва товару"))
    unit = forms.ChoiceField(label=_("Одиниця виміру"))

    class Meta:
        model = PurchaseRequest
        fields = [
            "requested_item",
            "requested_qty",
            "unit",
            "need_description",
            "product_url",
            "order_type",
        ]
        widgets = {
            "requested_qty": forms.NumberInput(attrs={"min": "0.001", "step": "0.001"}),
            "need_description": forms.TextInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["requested_item"].widget.attrs["list"] = "purchase-item-options"
        self.fields["unit"].choices = [
            (unit.symbol, unit.symbol)
            for unit in units_ordered_by_item_usage()
        ]
        self.fields["unit"].widget.attrs["class"] = "form-select"

    def clean_requested_item(self):
        return normalize_text(self.cleaned_data.get("requested_item"))

    def clean_unit(self):
        return normalize_text(self.cleaned_data.get("unit"))

    def save(self, commit=True):
        purchase_request = super().save(commit=False)
        purchase_request.title = self.cleaned_data["requested_item"]
        purchase_request.item = (
            Item.objects.filter(
                is_active=True,
                name__iexact=purchase_request.title,
            ).first()
        )
        if commit:
            purchase_request.save()
            self.save_m2m()
        return purchase_request


class PurchaseRequestEditForm(BootstrapModelForm):
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


class PurchaseRequestManagerForm(PurchaseRequestEditForm):
    class Meta(PurchaseRequestEditForm.Meta):
        fields = [
            *PurchaseRequestEditForm.Meta.fields,
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
    quantity_from = forms.DecimalField(
        label=_("Кількість від"),
        required=False,
        min_value=0,
        max_digits=18,
        decimal_places=3,
        widget=forms.NumberInput(attrs={"min": "0", "step": "0.001"}),
    )
    quantity_to = forms.DecimalField(
        label=_("Кількість до"),
        required=False,
        min_value=0,
        max_digits=18,
        decimal_places=3,
        widget=forms.NumberInput(attrs={"min": "0", "step": "0.001"}),
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
            field.widget.attrs.setdefault("form", "purchase-filter-form")
            if isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-select form-select-sm")
            else:
                field.widget.attrs.setdefault("class", "form-control form-control-sm")
