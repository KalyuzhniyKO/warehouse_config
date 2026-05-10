from django import forms
from django.utils.translation import gettext_lazy as _

from core.forms.base import BootstrapModelForm
from core.models import LabelTemplate, Printer


class PrinterForm(BootstrapModelForm):
    class Meta:
        model = Printer
        fields = ["name", "system_name", "description", "is_default", "is_active"]
        labels = {
            "name": _("Назва"),
            "system_name": _("Системна назва"),
            "description": _("Опис"),
            "is_default": _("За замовчуванням"),
            "is_active": _("Активний"),
        }


class LabelTemplateForm(BootstrapModelForm):
    class Meta:
        model = LabelTemplate
        fields = [
            "name",
            "width_mm",
            "height_mm",
            "show_item_name",
            "show_internal_code",
            "show_barcode_text",
            "barcode_type",
            "is_default",
            "is_active",
        ]
        labels = {
            "name": _("Назва"),
            "width_mm": _("Ширина, мм"),
            "height_mm": _("Висота, мм"),
            "show_item_name": _("Показувати назву товару"),
            "show_internal_code": _("Показувати внутрішній код"),
            "show_barcode_text": _("Показувати текст штрихкоду"),
            "barcode_type": _("Тип штрихкоду"),
            "is_default": _("За замовчуванням"),
            "is_active": _("Активний"),
        }


class PrintLabelForm(forms.Form):
    printer = forms.ModelChoiceField(label=_("Принтер"), queryset=Printer.objects.none())
    label_template = forms.ModelChoiceField(label=_("Шаблон"), queryset=LabelTemplate.objects.none())
    copies = forms.IntegerField(label=_("Кількість копій"), min_value=1, initial=1)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["printer"].queryset = Printer.objects.filter(is_active=True).order_by("-is_default", "name")
        self.fields["label_template"].queryset = LabelTemplate.objects.filter(is_active=True).order_by("-is_default", "name")
        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault("class", "form-select")
            else:
                field.widget.attrs.setdefault("class", "form-control")
