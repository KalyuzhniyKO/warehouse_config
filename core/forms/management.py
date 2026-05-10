from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils.translation import gettext_lazy as _

from core.forms.base import BootstrapModelForm
from core.models import SystemSettings
from core.permissions import AUDITOR_GROUP, STOREKEEPER_GROUP, WAREHOUSE_ADMIN_GROUP

WAREHOUSE_ROLE_GROUPS = (WAREHOUSE_ADMIN_GROUP, STOREKEEPER_GROUP, AUDITOR_GROUP)


def warehouse_role_queryset():
    return Group.objects.filter(name__in=WAREHOUSE_ROLE_GROUPS).order_by("name")


class SystemSettingsForm(BootstrapModelForm):
    class Meta:
        model = SystemSettings
        fields = ["use_locations"]
        help_texts = {
            "use_locations": _(
                "Якщо вимкнено, у наступному етапі складські операції будуть "
                "працювати без вибору локацій."
            ),
        }


class ManagementUserFormMixin:
    def __init__(self, *args, **kwargs):
        self.request_user = kwargs.pop("request_user", None)
        super().__init__(*args, **kwargs)
        self.fields["groups"].queryset = warehouse_role_queryset()
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(widget, forms.CheckboxSelectMultiple):
                widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(widget, forms.Select):
                widget.attrs.setdefault("class", "form-select")
            else:
                widget.attrs.setdefault("class", "form-control")

    def clean_groups(self):
        groups = self.cleaned_data.get("groups")
        allowed_ids = set(warehouse_role_queryset().values_list("id", flat=True))
        if groups and any(group.id not in allowed_ids for group in groups):
            raise forms.ValidationError(_("Можна вибирати тільки складські ролі."))
        return groups

    def clean(self):
        cleaned_data = super().clean()
        instance = getattr(self, "instance", None)
        if (
            instance
            and instance.pk
            and self.request_user
            and instance.pk == self.request_user.pk
            and cleaned_data.get("is_active") is False
        ):
            self.add_error("is_active", _("Не можна деактивувати самого себе."))
        if instance and instance.pk and instance.is_superuser:
            submitted_groups = set(cleaned_data.get("groups") or [])
            current_groups = set(instance.groups.all())
            if submitted_groups != current_groups:
                self.add_error(
                    "groups",
                    _("Групи superuser не можна змінювати через цей UI."),
                )
            if cleaned_data.get("is_active") is False:
                self.add_error(
                    "is_active",
                    _("Superuser не можна деактивувати через цей UI."),
                )
        return cleaned_data


class ManagementUserCreateForm(ManagementUserFormMixin, forms.ModelForm):
    password1 = forms.CharField(label=_("Пароль"), widget=forms.PasswordInput)
    password2 = forms.CharField(
        label=_("Підтвердження пароля"), widget=forms.PasswordInput
    )
    groups = forms.ModelMultipleChoiceField(
        label=_("Ролі"),
        queryset=Group.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = get_user_model()
        fields = [
            "username",
            "first_name",
            "last_name",
            "email",
            "password1",
            "password2",
            "groups",
            "is_active",
        ]
        labels = {
            "username": _("Логін"),
            "first_name": _("Ім'я"),
            "last_name": _("Прізвище"),
            "email": _("Email"),
            "is_active": _("Активний"),
        }

    def clean_username(self):
        username = (self.cleaned_data.get("username") or "").strip()
        if get_user_model().objects.filter(username__iexact=username).exists():
            raise forms.ValidationError(_("Користувач з таким логіном вже існує."))
        return username

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", _("Паролі не співпадають."))
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_staff = False
        user.is_superuser = False
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
            self.save_m2m()
        return user


class ManagementUserUpdateForm(ManagementUserFormMixin, forms.ModelForm):
    groups = forms.ModelMultipleChoiceField(
        label=_("Ролі"),
        queryset=Group.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = get_user_model()
        fields = ["first_name", "last_name", "email", "groups", "is_active"]
        labels = {
            "first_name": _("Ім'я"),
            "last_name": _("Прізвище"),
            "email": _("Email"),
            "is_active": _("Активний"),
        }

    def save(self, commit=True):
        user = super().save(commit=False)
        if not user.is_superuser:
            user.is_staff = False
        if commit:
            user.save()
            if not user.is_superuser:
                self.save_m2m()
        return user


class ManagementUserPasswordForm(forms.Form):
    password1 = forms.CharField(label=_("Новий пароль"), widget=forms.PasswordInput)
    password2 = forms.CharField(
        label=_("Підтвердження пароля"), widget=forms.PasswordInput
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user")
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", _("Паролі не співпадають."))
        return cleaned_data

    def save(self):
        self.user.set_password(self.cleaned_data["password1"])
        self.user.save(update_fields=["password"])
        return self.user
