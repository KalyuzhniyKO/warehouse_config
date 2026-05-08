from django import template

register = template.Library()


@register.filter
def attr(obj, name):
    display_method = getattr(obj, f"get_{name}_display", None)
    if callable(display_method):
        return display_method()
    return getattr(obj, name, "")
