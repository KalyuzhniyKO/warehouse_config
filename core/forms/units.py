from django.db.models import Count, Q

from core.forms.base import active_queryset
from core.models import Unit


def units_ordered_by_item_usage(include=None):
    return (
        active_queryset(Unit, include=include)
        .annotate(active_item_count=Count("items", filter=Q(items__is_active=True)))
        .order_by("-active_item_count", "name", "symbol", "pk")
    )
