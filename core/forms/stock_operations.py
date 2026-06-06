from decimal import Decimal

from django import forms
from django.utils.translation import gettext_lazy as _

from core.forms.base import ARCHIVED_CHOICE_ERROR, normalize_text
from core.models import (
    Item,
    Location,
    Recipient,
    StockBalance,
    StockMovement,
    SystemSettings,
    UsagePlace,
    Warehouse,
)
from core.services.locations import get_default_location_for_warehouse
from core.services.stock import (
    RETURN_QUANTITY_EXCEEDED_ERROR,
    get_available_return_qty,
)
from core.services.warehouse_access import get_accessible_warehouses


def active_warehouses_for_form_user(user):
    if user is None:
        return Warehouse.objects.filter(is_active=True)
    return get_accessible_warehouses(user)


class LocationsModeMixin:
    locations_disabled_message = _("Локація використовується автоматично")
    warehouse_auto_message = _("Склад призначається автоматично")

    def setup_locations_mode(self):
        settings = SystemSettings.get_solo()
        self.use_locations = bool(
            settings.use_locations
            and (
                self.request_user is None
                or getattr(self.request_user, "is_superuser", False)
            )
        )

    def hide_location_field_when_disabled(self, field_name="location"):
        if not self.use_locations:
            self.fields.pop(field_name, None)

    def set_default_location_when_disabled(
        self, cleaned_data, warehouse_field="warehouse", location_field="location"
    ):
        if not self.use_locations or location_field not in self.fields:
            warehouse = cleaned_data.get(warehouse_field)
            if warehouse:
                cleaned_data[location_field] = get_default_location_for_warehouse(warehouse)
        return cleaned_data

    def set_best_stock_location_when_disabled(
        self, cleaned_data, warehouse_field="warehouse", location_field="location"
    ):
        if self.use_locations and location_field in self.fields:
            return cleaned_data
        item = cleaned_data.get("item")
        warehouse = cleaned_data.get(warehouse_field)
        if not warehouse:
            return cleaned_data
        balance = None
        if item is not None:
            balance = (
                StockBalance.objects.filter(
                    item=item,
                    warehouse=warehouse,
                    is_active=True,
                    qty__gt=0,
                )
                .select_related("location", "warehouse")
                .order_by("-qty", "pk")
                .first()
            )
        cleaned_data[location_field] = (
            balance.location
            if balance is not None and balance.location_id
            else get_default_location_for_warehouse(warehouse)
        )
        return cleaned_data

    def setup_single_warehouse_mode(
        self, accessible_warehouses, field_name="warehouse"
    ):
        self.single_accessible_warehouse = None
        if self.request_user is None or getattr(
            self.request_user, "is_superuser", False
        ):
            return
        warehouses = list(accessible_warehouses[:2])
        if len(warehouses) == 1:
            self.single_accessible_warehouse = warehouses[0]
            self.initial[field_name] = self.single_accessible_warehouse
            self.fields.pop(field_name, None)

    def set_single_warehouse_when_hidden(self, cleaned_data, field_name="warehouse"):
        if (
            field_name not in self.fields
            and self.single_accessible_warehouse is not None
        ):
            cleaned_data[field_name] = self.single_accessible_warehouse
        return cleaned_data


class StockOperationForm(LocationsModeMixin, forms.Form):
    item = forms.ModelChoiceField(label=_("Номенклатура"), queryset=Item.objects.none())
    warehouse = forms.ModelChoiceField(
        label=_("Склад"), queryset=Warehouse.objects.none()
    )
    location = forms.ModelChoiceField(
        label=_("Локація"), queryset=Location.objects.none(), required=False
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
        self.request_user = kwargs.pop("user", kwargs.pop("request_user", None))
        super().__init__(*args, **kwargs)
        self.setup_locations_mode()
        accessible_warehouses = active_warehouses_for_form_user(self.request_user)
        self.fields["item"].queryset = Item.objects.filter(
            is_active=True
        ).select_related("unit")
        self.fields["warehouse"].queryset = accessible_warehouses
        self.setup_single_warehouse_mode(accessible_warehouses)
        if "location" in self.fields:
            self.fields["location"].queryset = Location.objects.filter(
                is_active=True,
                warehouse__is_active=True,
                warehouse__in=accessible_warehouses,
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
        self.set_single_warehouse_when_hidden(cleaned_data)
        self.set_default_location_when_disabled(cleaned_data)
        warehouse = cleaned_data.get("warehouse")
        location = cleaned_data.get("location")
        if warehouse and location is None:
            location = get_default_location_for_warehouse(warehouse)
            cleaned_data["location"] = location
        if warehouse and location and location.warehouse_id != warehouse.pk:
            self.add_error("location", _("Локація має належати вибраному складу."))
        return cleaned_data


class StockReceiveForm(StockOperationForm):
    print_label = forms.BooleanField(
        label=_("Надрукувати етикетку після збереження"), required=False
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name in ["item", "comment", "occurred_at", "print_label"]:
            if field_name in self.fields:
                self.fields[field_name].widget = forms.HiddenInput()
        for field_name in ["warehouse", "location"]:
            if field_name in self.fields:
                self.fields[field_name].widget.attrs[
                    "class"
                ] = "form-select form-select-lg"
        self.fields["qty"].widget.attrs.update(
            {
                "class": "form-control form-control-lg text-center",
                "min": "1",
                "step": "1",
                "inputmode": "numeric",
                "pattern": "[0-9]*",
            }
        )
        self.order_fields(
            [
                "item",
                "warehouse",
                "location",
                "qty",
                "comment",
                "occurred_at",
                "print_label",
            ]
        )


class StockReturnForm(StockOperationForm):
    def clean(self):
        cleaned_data = super().clean()
        warehouse = cleaned_data.get("warehouse")
        if warehouse:
            cleaned_data["location"] = get_default_location_for_warehouse(warehouse)
        item = cleaned_data.get("item")
        recipient = cleaned_data.get("recipient")
        qty = cleaned_data.get("qty")
        if item and recipient:
            available_qty = get_available_return_qty(item, recipient)
            self.fields["qty"].help_text = _("Доступно до повернення: %(qty)s") % {
                "qty": available_qty
            }
            if qty is not None and (available_qty <= 0 or qty > available_qty):
                self.add_error("qty", RETURN_QUANTITY_EXCEEDED_ERROR)
        return cleaned_data

    recipient = forms.ModelChoiceField(
        label=_("Хто повертає"),
        queryset=Recipient.objects.none(),
        required=True,
        empty_label=_("Виберіть працівника"),
    )
    department = forms.ModelChoiceField(
        label=_("Місце використання"),
        queryset=UsagePlace.objects.none(),
        required=True,
        empty_label=_("Виберіть місце використання"),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        usage_places = UsagePlace.objects.filter(is_active=True).order_by("name")
        self.fields["department"].queryset = usage_places
        self.fields["recipient"].queryset = Recipient.objects.filter(
            is_active=True
        ).order_by("name")
        for field_name in ["item", "location", "comment", "occurred_at"]:
            if field_name in self.fields:
                self.fields[field_name].widget = forms.HiddenInput()
        self.fields["qty"].widget.attrs.update(
            {
                "class": "form-control form-control-lg text-center",
                "min": "1",
                "step": "1",
                "inputmode": "numeric",
                "pattern": "[0-9]*",
            }
        )
        self.fields["recipient"].widget.attrs["class"] = "form-select form-select-lg"
        self.fields["department"].widget.attrs["class"] = "form-select form-select-lg"

    def clean_department(self):
        usage_place = self.cleaned_data.get("department")
        return usage_place.name if usage_place else ""


class StockReceiveForm(StockReceiveForm):
    def clean(self):
        cleaned_data = super().clean()
        warehouse = cleaned_data.get("warehouse")
        if warehouse:
            cleaned_data["location"] = get_default_location_for_warehouse(warehouse)
        return cleaned_data


class StockIssueForm(StockOperationForm):
    issue_reason = forms.ChoiceField(
        label=_("Тип видачі"), choices=StockMovement.IssueReason.choices
    )
    department = forms.ModelChoiceField(
        label=_("Цех / місце використання"),
        queryset=UsagePlace.objects.none(),
        required=True,
        empty_label=_("Оберіть цех або місце використання"),
        error_messages={
            "required": _("Оберіть цех або місце використання."),
        },
    )
    recipient = forms.ModelChoiceField(
        label=_("Хто взяв товар"),
        queryset=Recipient.objects.none(),
        required=True,
        error_messages={
            "required": _("Оберіть, хто бере товар."),
        },
    )
    document_number = forms.CharField(label=_("Номер документа"), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        usage_places = UsagePlace.objects.filter(is_active=True).order_by("name")
        self.fields["department"].queryset = usage_places
        if not usage_places.exists():
            self.fields["department"].error_messages["required"] = _(
                "Налаштуйте хоча б одне активне місце використання."
            )
        self.fields["recipient"].queryset = Recipient.objects.filter(is_active=True)
        self.fields["issue_reason"].initial = StockMovement.IssueReason.OTHER
        self.fields["issue_reason"].required = False
        self.fields["document_number"].required = False
        self.fields["comment"].required = False
        for field_name in [
            "item",
            "location",
            "issue_reason",
            "document_number",
            "comment",
            "occurred_at",
        ]:
            if field_name in self.fields:
                self.fields[field_name].widget = forms.HiddenInput()
        self.fields["qty"].widget.attrs.update(
            {
                "class": "form-control form-control-lg text-center",
                "min": "1",
                "step": "1",
                "inputmode": "numeric",
                "pattern": "[0-9]*",
            }
        )
        self.fields["department"].widget.attrs["class"] = "form-select form-select-lg"
        self.fields["recipient"].widget.attrs["class"] = "form-select form-select-lg"
        self.order_fields(
            [
                "item",
                "warehouse",
                "location",
                "qty",
                "issue_reason",
                "recipient",
                "department",
                "document_number",
                "comment",
                "occurred_at",
            ]
        )

    def clean_department(self):
        usage_place = self.cleaned_data.get("department")
        if usage_place:
            return usage_place.name
        return ""

    def clean_document_number(self):
        return normalize_text(self.cleaned_data.get("document_number"))

    def clean(self):
        cleaned_data = super().clean()
        self.set_best_stock_location_when_disabled(cleaned_data)
        return cleaned_data


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

    def clean(self):
        cleaned_data = super().clean()
        self.set_best_stock_location_when_disabled(cleaned_data)
        return cleaned_data


class StockTransferForm(LocationsModeMixin, forms.Form):
    item = forms.ModelChoiceField(label=_("Номенклатура"), queryset=Item.objects.none())
    source_warehouse = forms.ModelChoiceField(
        label=_("Склад-відправник"), queryset=Warehouse.objects.none()
    )
    source_location = forms.ModelChoiceField(
        label=_("Локація-відправник"), queryset=Location.objects.none(), required=False
    )
    destination_warehouse = forms.ModelChoiceField(
        label=_("Склад-отримувач"), queryset=Warehouse.objects.none()
    )
    destination_location = forms.ModelChoiceField(
        label=_("Локація-отримувач"), queryset=Location.objects.none(), required=False
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
        self.request_user = kwargs.pop("user", kwargs.pop("request_user", None))
        super().__init__(*args, **kwargs)
        self.setup_locations_mode()
        accessible_warehouses = active_warehouses_for_form_user(self.request_user)
        self.fields["item"].queryset = Item.objects.filter(
            is_active=True
        ).select_related("unit")
        self.fields["source_warehouse"].queryset = accessible_warehouses
        self.fields["destination_warehouse"].queryset = accessible_warehouses
        location_queryset = Location.objects.filter(
            is_active=True,
            warehouse__is_active=True,
            warehouse__in=accessible_warehouses,
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
        source_location = cleaned_data.get("source_location")
        destination_location = cleaned_data.get("destination_location")

        if (
            not self.use_locations
            and source_warehouse
            and destination_warehouse
            and source_warehouse == destination_warehouse
        ):
            raise forms.ValidationError(_("Неможливо перемістити товар у той самий склад."))
        if source_warehouse and source_location is None:
            item = cleaned_data.get("item")
            balance = None
            if item is not None:
                balance = (
                    StockBalance.objects.filter(
                        item=item, warehouse=source_warehouse, is_active=True, qty__gt=0
                    )
                    .select_related("location")
                    .order_by("-qty", "pk")
                    .first()
                )
            cleaned_data["source_location"] = (
                balance.location
                if balance is not None and balance.location_id
                else get_default_location_for_warehouse(source_warehouse)
            )
        if destination_warehouse and destination_location is None:
            cleaned_data["destination_location"] = get_default_location_for_warehouse(destination_warehouse)
        source_location = cleaned_data.get("source_location")
        destination_location = cleaned_data.get("destination_location")

        if (
            source_warehouse
            and destination_warehouse
            and source_warehouse == destination_warehouse
            and not (source_location and destination_location)
        ):
            raise forms.ValidationError(_("Неможливо перемістити товар у той самий склад."))


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
            "source_location" not in self.fields
            and "destination_location" not in self.fields
            and source_warehouse
            and destination_warehouse
            and source_warehouse == destination_warehouse
        ):
            raise forms.ValidationError(_("Неможливо перемістити товар у той самий склад."))
        if (
            source_location
            and destination_location
            and source_location == destination_location
        ):
            self.add_error(
                "destination_location" if "destination_location" in self.fields else None,
                _("Неможливо перемістити товар у ту саму локацію."),
            )
        return cleaned_data


class InitialBalanceForm(StockOperationForm):
    pass


class StockMovementCancellationForm(forms.Form):
    reason = forms.CharField(
        label=_("Причина анулювання"),
        required=True,
        widget=forms.Textarea(attrs={"rows": 4, "class": "form-control"}),
        error_messages={"required": _("Причина анулювання обов'язкова.")},
    )

    def clean_reason(self):
        reason = normalize_text(self.cleaned_data.get("reason"))
        if not reason:
            raise forms.ValidationError(_("Причина анулювання обов'язкова."))
        return reason
