from django import forms
from django.utils.translation import gettext_lazy as _

from core.forms.base import BootstrapModelForm
from django.forms import inlineformset_factory, BaseInlineFormSet

from core.models import LabelTemplate, LabelTemplateElement, Printer
from core.services.printers import list_system_printers


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
        help_texts = {}


    def clean_system_name(self):
        system_name = (self.cleaned_data.get("system_name") or "").strip()
        if not system_name:
            return system_name

        try:
            system_names = {
                printer["system_name"] for printer in list_system_printers()
            }
        except Exception:
            return system_name

        if system_name not in system_names:
            raise forms.ValidationError(
                _(
                    "Принтер із системною назвою '%(system_name)s' не знайдено в CUPS. Перевірте назву або синхронізуйте принтери."
                )
                % {"system_name": system_name}
            )
        return system_name


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
            "margin_top_mm",
            "margin_right_mm",
            "margin_bottom_mm",
            "margin_left_mm",
            "item_name_font_size",
            "internal_code_font_size",
            "barcode_text_font_size",
            "barcode_height_mm",
            "barcode_bar_width_mm",
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
            "margin_top_mm": _("Верхній відступ, мм"),
            "margin_right_mm": _("Правий відступ, мм"),
            "margin_bottom_mm": _("Нижній відступ, мм"),
            "margin_left_mm": _("Лівий відступ, мм"),
            "item_name_font_size": _("Розмір шрифту назви"),
            "internal_code_font_size": _("Розмір шрифту внутрішнього коду"),
            "barcode_text_font_size": _("Розмір шрифту тексту штрихкоду"),
            "barcode_height_mm": _("Висота штрихкоду, мм"),
            "barcode_bar_width_mm": _("Товщина лінії штрихкоду, мм"),
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


class LabelTemplateElementForm(BootstrapModelForm):
    class Meta:
        model = LabelTemplateElement
        fields = ["id", "element_type", "text", "x_mm", "y_mm", "width_mm", "height_mm", "font_size", "is_visible", "sort_order"]
        widgets = {
            "element_type": forms.HiddenInput(),
            "sort_order": forms.HiddenInput(),
        }


class LabelTemplateElementBaseFormSet(BaseInlineFormSet):
    FIXED_TYPES = {
        LabelTemplateElement.ElementType.ITEM_NAME,
        LabelTemplateElement.ElementType.INTERNAL_CODE,
        LabelTemplateElement.ElementType.BARCODE,
        LabelTemplateElement.ElementType.BARCODE_TEXT,
    }

    def clean(self):
        super().clean()
        for form in self.forms:
            if not hasattr(form, "cleaned_data") or not form.cleaned_data or form.cleaned_data.get("DELETE") is not True:
                continue
            if form.cleaned_data.get("element_type") in self.FIXED_TYPES:
                form.cleaned_data["DELETE"] = False


LabelTemplateElementFormSet = inlineformset_factory(
    LabelTemplate,
    LabelTemplateElement,
    form=LabelTemplateElementForm,
    extra=0,
    can_delete=True,
    formset=LabelTemplateElementBaseFormSet,
)
