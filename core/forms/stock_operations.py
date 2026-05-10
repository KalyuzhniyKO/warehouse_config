from decimal import Decimal

from django import forms
from django.utils.translation import gettext_lazy as _

from core.forms.base import ARCHIVED_CHOICE_ERROR, normalize_text
from core.models import (
    Item,
    Location,
    Recipient,
    StockMovement,
    SystemSettings,
    Warehouse,
)
from core.services.locations import get_default_location_for_warehouse


class LocationsModeMixin:
    locations_disabled_message = _(
        "Локації вимкнено. Операція буде виконана по складу."
    )

    def setup_locations_mode(self):
        self.use_locations = SystemSettings.get_solo().use_locations

    def hide_location_field_when_disabled(self, field_name="location"):
        if not self.use_locations:
            self.fields.pop(field_name, None)

    def set_default_location_when_disabled(
        self, cleaned_data, warehouse_field="warehouse", location_field="location"
    ):
        if not self.use_locations:
            warehouse = cleaned_data.get(warehouse_field)
            if warehouse:
                cleaned_data[location_field] = get_default_location_for_warehouse(
                    warehouse
                )
        return cleaned_data


class StockOperationForm(LocationsModeMixin, forms.Form):
    item = forms.ModelChoiceField(label=_("Номенклатура"), queryset=Item.objects.none())
    warehouse = forms.ModelChoiceField(
        label=_("Склад"), queryset=Warehouse.objects.none()
    )
    location = forms.ModelChoiceField(
        label=_("Локація"), queryset=Location.objects.none()
    )
    qty = forms.DecimalField(
        label=_("Кількість"), min_value=0, max_digits=18, decimal_places=3
    )
    comment = forms.CharField(
        label=_("Коментар"), required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    occurred_at = forms.DateTimeField(
        label=_("Дата операції"),
        required=True,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setup_locations_mode()
        self.fields["item"].queryset = Item.objects.filter(
            is_active=True
        ).select_related("unit")
        self.fields["warehouse"].queryset = Warehouse.objects.filter(is_active=True)
        if "location" in self.fields:
            self.fields["location"].queryset = Location.objects.filter(
                is_active=True, warehouse__is_active=True
            ).select_related("warehouse")
        self.hide_location_field_when_disabled()
        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-select")
            elif isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-check-input")
            else:
                field.widget.attrs.setdefault("class", "form-control")

    def clean_location(self):
        location = self.cleaned_data.get("location")
        if location and (not location.is_active or not location.warehouse.is_active):
            raise forms.ValidationError(ARCHIVED_CHOICE_ERROR)
        return location

    def clean(self):
        cleaned_data = super().clean()
        self.set_default_location_when_disabled(cleaned_data)
        warehouse = cleaned_data.get("warehouse")
        location = cleaned_data.get("location")
        if warehouse and location and location.warehouse_id != warehouse.pk:
            self.add_error("location", _("Локація має належати вибраному складу."))
        return cleaned_data


class StockReceiveForm(StockOperationForm):
    print_label = forms.BooleanField(
        label=_("Надрукувати етикетку після збереження"), required=False
    )


class StockIssueForm(StockOperationForm):
    issue_reason = forms.ChoiceField(
        label=_("Тип видачі"), choices=StockMovement.IssueReason.choices
    )
    department = forms.CharField(label=_("Цех / підрозділ"), required=False)
    recipient = forms.ModelChoiceField(
        label=_("Отримувач / відповідальний"),
        queryset=Recipient.objects.none(),
        required=False,
    )
    document_number = forms.CharField(label=_("Номер документа"), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["recipient"].queryset = Recipient.objects.filter(is_active=True)
        self.fields["issue_reason"].initial = StockMovement.IssueReason.OTHER
        self.order_fields(
            [
                "item",
                "warehouse",
                "location",
                "qty",
                "issue_reason",
                "department",
                "recipient",
                "document_number",
                "comment",
                "occurred_at",
            ]
        )

    def clean_department(self):
        return normalize_text(self.cleaned_data.get("department"))

    def clean_document_number(self):
        return normalize_text(self.cleaned_data.get("document_number"))


class StockWriteOffForm(StockOperationForm):
    qty = forms.DecimalField(
        label=_("Кількість"),
        min_value=Decimal("0.001"),
        max_digits=18,
        decimal_places=3,
    )
    writeoff_reason = forms.ChoiceField(
        label=_("Причина списання"),
        choices=[
            ("repair", _("Використано для ремонту")),
            ("damaged", _("Зіпсовано")),
            ("lost", _("Втрачено")),
            ("defect", _("Брак")),
            ("other", _("Інше")),
        ],
    )
    document_number = forms.CharField(label=_("Номер документа"), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["writeoff_reason"].initial = "other"
        self.order_fields(
            [
                "item",
                "warehouse",
                "location",
                "qty",
                "writeoff_reason",
                "document_number",
                "comment",
                "occurred_at",
            ]
        )

    def clean_document_number(self):
        return normalize_text(self.cleaned_data.get("document_number"))


class StockTransferForm(LocationsModeMixin, forms.Form):
    item = forms.ModelChoiceField(label=_("Номенклатура"), queryset=Item.objects.none())
    source_warehouse = forms.ModelChoiceField(
        label=_("Склад-відправник"), queryset=Warehouse.objects.none()
    )
    source_location = forms.ModelChoiceField(
        label=_("Локація-відправник"), queryset=Location.objects.none()
    )
    destination_warehouse = forms.ModelChoiceField(
        label=_("Склад-отримувач"), queryset=Warehouse.objects.none()
    )
    destination_location = forms.ModelChoiceField(
        label=_("Локація-отримувач"), queryset=Location.objects.none()
    )
    qty = forms.DecimalField(
        label=_("Кількість"),
        min_value=Decimal("0.001"),
        max_digits=18,
        decimal_places=3,
    )
    comment = forms.CharField(
        label=_("Коментар"), required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    occurred_at = forms.DateTimeField(
        label=_("Дата операції"),
        required=True,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setup_locations_mode()
        self.fields["item"].queryset = Item.objects.filter(
            is_active=True
        ).select_related("unit")
        self.fields["source_warehouse"].queryset = Warehouse.objects.filter(
            is_active=True
        )
        self.fields["destination_warehouse"].queryset = Warehouse.objects.filter(
            is_active=True
        )
        location_queryset = Location.objects.filter(
            is_active=True, warehouse__is_active=True
        ).select_related("warehouse")
        self.fields["source_location"].queryset = location_queryset
        self.fields["destination_location"].queryset = location_queryset
        if not self.use_locations:
            self.fields.pop("source_location", None)
            self.fields.pop("destination_location", None)
        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-select")
            else:
                field.widget.attrs.setdefault("class", "form-control")

    def clean(self):
        cleaned_data = super().clean()
        source_warehouse = cleaned_data.get("source_warehouse")
        destination_warehouse = cleaned_data.get("destination_warehouse")
        if not self.use_locations:
            if (
                source_warehouse
                and destination_warehouse
                and source_warehouse == destination_warehouse
            ):
                raise forms.ValidationError(
                    _("Неможливо перемістити товар у той самий склад.")
                )
            if source_warehouse:
                cleaned_data["source_location"] = get_default_location_for_warehouse(
                    source_warehouse
                )
            if destination_warehouse:
                cleaned_data["destination_location"] = (
                    get_default_location_for_warehouse(destination_warehouse)
                )

        source_location = cleaned_data.get("source_location")
        destination_location = cleaned_data.get("destination_location")

        if (
            source_warehouse
            and source_location
            and source_location.warehouse_id != source_warehouse.pk
        ):
            self.add_error(
                "source_location", _("Локація має належати вибраному складу.")
            )
        if (
            destination_warehouse
            and destination_location
            and destination_location.warehouse_id != destination_warehouse.pk
        ):
            self.add_error(
                "destination_location", _("Локація має належати вибраному складу.")
            )
        if (
            source_location
            and destination_location
            and source_location == destination_location
        ):
            self.add_error(
                "destination_location",
                _("Неможливо перемістити товар у ту саму локацію."),
            )
        return cleaned_data


class InitialBalanceForm(StockOperationForm):
    pass
