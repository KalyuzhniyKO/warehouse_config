from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils.translation import gettext_lazy as _

from core.forms.base import BootstrapModelForm
from core.models import SystemSettings, UserWarehouseAccess
from core.permissions import ROLE_DISPLAY_NAMES, STOREKEEPER_GROUP, WAREHOUSE_ADMIN_GROUP
from core.services.audit import log_action
from core.services.warehouse_access import get_delegatable_warehouses

WAREHOUSE_ROLE_GROUPS = (WAREHOUSE_ADMIN_GROUP, STOREKEEPER_GROUP)
WAREHOUSE_ACCESS_PREFIX = "warehouse_access_"
WAREHOUSE_DELEGATE_PREFIX = "warehouse_delegate_"


def warehouse_role_queryset():
    return Group.objects.filter(name__in=WAREHOUSE_ROLE_GROUPS).order_by("name")


class WarehouseRoleChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return ROLE_DISPLAY_NAMES.get(obj.name, obj.name)


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
        self.delegatable_warehouses = self.get_delegatable_warehouses()
        self.add_warehouse_access_fields()
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

    def get_delegatable_warehouses(self):
        instance = getattr(self, "instance", None)
        if (
            instance
            and instance.pk
            and instance.is_superuser
            and not getattr(self.request_user, "is_superuser", False)
        ):
            return []
        return list(get_delegatable_warehouses(self.request_user))

    def add_warehouse_access_fields(self):
        instance = getattr(self, "instance", None)
        if instance and instance.pk and instance.is_superuser:
            return
        current_access = {}
        if instance and instance.pk:
            current_access = {
                access.warehouse_id: access
                for access in instance.warehouse_accesses.select_related("warehouse")
            }
        for warehouse in self.delegatable_warehouses:
            access = current_access.get(warehouse.pk)
            has_access_name = self.warehouse_access_field_name(warehouse)
            can_delegate_name = self.warehouse_delegate_field_name(warehouse)
            self.fields[has_access_name] = forms.BooleanField(
                label=warehouse.name,
                required=False,
                initial=bool(access and access.is_active),
            )
            self.fields[can_delegate_name] = forms.BooleanField(
                label=_("Може делегувати доступ"),
                required=False,
                initial=bool(access and access.is_active and access.can_delegate),
            )

    def warehouse_access_field_name(self, warehouse):
        return f"{WAREHOUSE_ACCESS_PREFIX}{warehouse.pk}"

    def warehouse_delegate_field_name(self, warehouse):
        return f"{WAREHOUSE_DELEGATE_PREFIX}{warehouse.pk}"

    def warehouse_access_rows(self):
        for warehouse in self.delegatable_warehouses:
            yield {
                "warehouse": warehouse,
                "has_access": self[self.warehouse_access_field_name(warehouse)],
                "can_delegate": self[self.warehouse_delegate_field_name(warehouse)],
            }

    def has_warehouse_access_rows(self):
        return bool(self.delegatable_warehouses)

    def posted_warehouse_ids(self):
        ids = set()
        for key in self.data.keys():
            for prefix in (WAREHOUSE_ACCESS_PREFIX, WAREHOUSE_DELEGATE_PREFIX):
                if key.startswith(prefix):
                    try:
                        ids.add(int(key.removeprefix(prefix)))
                    except ValueError:
                        continue
        return ids

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
        if instance and instance.pk and instance.is_superuser and self.posted_warehouse_ids():
            if self.request_user and not self.request_user.is_superuser:
                raise forms.ValidationError(
                    _("Ви не можете надати доступ до цього складу.")
                )
        if self.request_user and not self.request_user.is_superuser:
            allowed_warehouse_ids = {warehouse.pk for warehouse in self.delegatable_warehouses}
            if self.posted_warehouse_ids() - allowed_warehouse_ids:
                raise forms.ValidationError(
                    _("Ви не можете надати доступ до цього складу.")
                )
        for warehouse in self.delegatable_warehouses:
            has_access = cleaned_data.get(self.warehouse_access_field_name(warehouse))
            can_delegate = cleaned_data.get(self.warehouse_delegate_field_name(warehouse))
            if can_delegate and not has_access:
                self.add_error(
                    self.warehouse_delegate_field_name(warehouse),
                    _("Користувач не має доступу до цього складу."),
                )
        return cleaned_data

    def build_warehouse_access_changes(self, *, target_user, warehouse, can_delegate):
        actor = self.request_user
        return {
            "target_user_id": target_user.pk,
            "target_user": target_user.get_username(),
            "warehouse_id": warehouse.pk,
            "warehouse": str(warehouse),
            "can_delegate": bool(can_delegate),
            "actor_id": getattr(actor, "pk", None),
        }

    def save_warehouse_accesses(self, user):
        if not user.pk or user.is_superuser:
            return
        actor = self.request_user
        for warehouse in self.delegatable_warehouses:
            has_access = bool(
                self.cleaned_data.get(self.warehouse_access_field_name(warehouse))
            )
            can_delegate = bool(
                self.cleaned_data.get(self.warehouse_delegate_field_name(warehouse))
            )
            access = UserWarehouseAccess.objects.filter(
                user=user, warehouse=warehouse
            ).first()
            if has_access:
                if access is None:
                    access = UserWarehouseAccess.objects.create(
                        user=user,
                        warehouse=warehouse,
                        can_delegate=can_delegate,
                        created_by=actor,
                    )
                    log_action(
                        actor,
                        "warehouse_access.created",
                        obj=access,
                        changes=self.build_warehouse_access_changes(
                            target_user=user,
                            warehouse=warehouse,
                            can_delegate=can_delegate,
                        ),
                    )
                elif not access.is_active:
                    access.is_active = True
                    access.can_delegate = can_delegate
                    access.created_by = actor
                    access.save(
                        update_fields=[
                            "is_active",
                            "can_delegate",
                            "created_by",
                            "updated_at",
                        ]
                    )
                    log_action(
                        actor,
                        "warehouse_access.created",
                        obj=access,
                        changes=self.build_warehouse_access_changes(
                            target_user=user,
                            warehouse=warehouse,
                            can_delegate=can_delegate,
                        ),
                    )
                elif access.can_delegate != can_delegate:
                    previous_can_delegate = access.can_delegate
                    access.can_delegate = can_delegate
                    access.save(update_fields=["can_delegate", "updated_at"])
                    changes = self.build_warehouse_access_changes(
                        target_user=user,
                        warehouse=warehouse,
                        can_delegate=can_delegate,
                    )
                    changes["previous_can_delegate"] = previous_can_delegate
                    log_action(
                        actor,
                        "warehouse_access.updated",
                        obj=access,
                        changes=changes,
                    )
            elif access is not None and access.is_active:
                previous_can_delegate = access.can_delegate
                access.is_active = False
                access.can_delegate = False
                access.save(update_fields=["is_active", "can_delegate", "updated_at"])
                changes = self.build_warehouse_access_changes(
                    target_user=user,
                    warehouse=warehouse,
                    can_delegate=previous_can_delegate,
                )
                log_action(
                    actor,
                    "warehouse_access.removed",
                    obj=access,
                    changes=changes,
                )


class ManagementUserCreateForm(ManagementUserFormMixin, forms.ModelForm):
    password1 = forms.CharField(label=_("Пароль"), widget=forms.PasswordInput)
    password2 = forms.CharField(
        label=_("Підтвердження пароля"), widget=forms.PasswordInput
    )
    groups = WarehouseRoleChoiceField(
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
            self.save_warehouse_accesses(user)
        return user


class ManagementUserUpdateForm(ManagementUserFormMixin, forms.ModelForm):
    groups = WarehouseRoleChoiceField(
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
                self.save_warehouse_accesses(user)
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
