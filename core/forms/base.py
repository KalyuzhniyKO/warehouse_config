from django import forms
from django.utils.translation import gettext_lazy as _


ARCHIVED_CHOICE_ERROR = _("Не можна вибрати архівний запис.")


def active_queryset(model, include=None, **filters):
    queryset = model.objects.filter(is_active=True, **filters)
    if include is not None and getattr(include, "pk", None):
        queryset = model.objects.filter(pk=include.pk) | queryset
    return queryset.distinct()


def set_active_model_choice(form, field_name, queryset):
    field = form.fields[field_name]
    field.queryset = queryset
    field.error_messages["invalid_choice"] = ARCHIVED_CHOICE_ERROR


def current_related(instance, field_name):
    if instance and getattr(instance, "pk", None):
        return getattr(instance, field_name, None)
    return None


def is_current_relation(form, field_name, obj):
    current = current_related(form.instance, field_name)
    return bool(
        getattr(form, "include_current_relations", False)
        and obj
        and current
        and obj.pk == current.pk
    )


DUPLICATE_MESSAGES = {
    "category": _("Категорія з такою назвою вже існує."),
    "unit_name": _("Одиниця виміру з такою назвою вже існує."),
    "unit_symbol": _("Одиниця виміру з таким позначенням вже існує."),
    "recipient": _("Отримувач з такою назвою вже існує."),
    "warehouse": _("Склад з такою назвою вже існує."),
    "location": _("Локація з такою назвою вже існує на цьому складі."),
    "item_code": _("Номенклатура з таким внутрішнім кодом вже існує."),
}


def normalize_text(value):
    return (value or "").strip()


def normalized_duplicate_exists(queryset, instance, field_name, value):
    normalized = normalize_text(value).casefold()
    if instance and instance.pk:
        queryset = queryset.exclude(pk=instance.pk)
    for obj in queryset.filter(is_active=True):
        if normalize_text(getattr(obj, field_name)).casefold() == normalized:
            return True
    return False


class BootstrapModelForm(forms.ModelForm):
    """Model form base class with Bootstrap-friendly widgets."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(widget, forms.Select):
                widget.attrs.setdefault("class", "form-select")
            elif isinstance(widget, forms.Textarea):
                widget.attrs.setdefault("class", "form-control")
                widget.attrs.setdefault("rows", 3)
            else:
                widget.attrs.setdefault("class", "form-control")

    def clean_normalized_char(self, field_name):
        value = normalize_text(self.cleaned_data.get(field_name))
        self.cleaned_data[field_name] = value
        return value
