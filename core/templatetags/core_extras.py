from decimal import Decimal, InvalidOperation

from django import template
from django.utils import formats
from django.utils.translation import gettext as _

from core.permissions import ROLE_DESCRIPTIONS, ROLE_DISPLAY_NAMES

register = template.Library()


AUDIT_ACTION_LABELS = {
    "auth.login": _("Вхід у систему"),
    "auth.logout": _("Вихід із системи"),
    "auth.login_failed": _("Невдала спроба входу"),
    "stock_movement.created": _("Створено складську операцію"),
    "stock_movement.cancelled": _("Анульовано складську операцію"),
    "warehouse_access.created": _("Додано доступ до складу"),
    "warehouse_access.updated": _("Змінено доступ до складу"),
    "warehouse_access.deleted": _("Видалено доступ до складу"),
    "user.created": _("Створено користувача"),
    "user.updated": _("Змінено користувача"),
    "user.deleted": _("Видалено користувача"),
}


AUDIT_CHANGE_LABELS = {
    "actor_id": _("Користувач ID"),
    "item_id": _("Товар ID"),
    "movement_type": _("Тип операції"),
    "qty": _("Кількість"),
    "warehouse": _("Склад"),
    "target_user": _("Користувач"),
    "groups": _("Ролі"),
    "is_active": _("Активний"),
    "can_delegate": _("Може делегувати"),
}


@register.filter
def attr(obj, name):
    display_method = getattr(obj, f"get_{name}_display", None)
    if callable(display_method):
        return display_method()
    return getattr(obj, name, "")


@register.filter
def in_group(user, group_name):
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    return user.groups.filter(name=group_name).exists()


@register.filter
def display_name(user):
    full_name_method = getattr(user, "get_full_name", None)
    full_name = full_name_method() if callable(full_name_method) else ""
    first_name = getattr(user, "first_name", "") or ""
    username_method = getattr(user, "get_username", None)
    username = username_method() if callable(username_method) else getattr(user, "username", "")
    display = (full_name or first_name or username or "").strip()
    if display.lower() == "root":
        return _("Адміністратор")
    return display


@register.filter
def first_letter(value):
    value = str(value or "").strip()
    return value[:1] if value else "?"


@register.filter
def role_display_name(group):
    name = getattr(group, "name", group)
    return ROLE_DISPLAY_NAMES.get(name, name)


@register.filter
def role_description(group):
    name = getattr(group, "name", group)
    return ROLE_DESCRIPTIONS.get(name, "")


@register.filter
def audit_action_label(action):
    return AUDIT_ACTION_LABELS.get(action, action)


@register.filter
def audit_object_label(value):
    if str(value or "").strip().lower() == "root":
        return _("Адміністратор")
    return value


@register.filter
def qty(value):
    if value in (None, ""):
        return ""
    try:
        decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return value
    normalized = decimal_value.normalize()
    if normalized == normalized.to_integral():
        decimal_places = 0
    else:
        decimal_places = min(abs(normalized.as_tuple().exponent), 3)
    return formats.number_format(decimal_value, decimal_pos=decimal_places)


@register.filter
def audit_changes_summary(changes):
    if not isinstance(changes, dict) or not changes:
        return []
    rows = []
    for key, value in changes.items():
        label = AUDIT_CHANGE_LABELS.get(key, key.replace("_", " ").capitalize())
        if isinstance(value, (list, tuple, set)):
            value = ", ".join(str(part) for part in value)
        elif isinstance(value, dict):
            value = "; ".join(
                f"{nested_key}: {nested_value}"
                for nested_key, nested_value in value.items()
            )
        elif isinstance(value, bool):
            value = _("Так") if value else _("Ні")
        rows.append((label, value))
    return rows
