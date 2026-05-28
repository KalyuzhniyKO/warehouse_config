from django import template

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
        return "Superuser"
    return display


@register.filter
def first_letter(value):
    value = str(value or "").strip()
    return value[:1] if value else "?"
