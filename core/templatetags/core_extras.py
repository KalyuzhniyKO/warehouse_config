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
