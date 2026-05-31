from django import template
from django.utils.translation import gettext as _

from core.permissions import ROLE_DESCRIPTIONS, ROLE_DISPLAY_NAMES

register = template.Library()


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
