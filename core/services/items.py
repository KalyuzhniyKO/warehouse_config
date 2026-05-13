"""Item lookup helpers."""

from django.db.models import Q

from core.models import Item


def find_item_by_barcode(value):
    """Return an active item matching *value* by barcode or internal code."""
    value = (value or "").strip()
    if not value:
        return None
    return (
        Item.objects.select_related("barcode", "unit")
        .filter(is_active=True)
        .filter(Q(barcode__barcode=value) | Q(internal_code=value))
        .first()
    )
