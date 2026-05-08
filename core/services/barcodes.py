"""Transactional barcode generation helpers."""

from django.db import IntegrityError, transaction

from core.models import BarcodeRegistry, BarcodeSequence, Item, Location, Warehouse

BARCODE_PADDING = 10


def _normalize_prefix(prefix):
    return str(prefix).strip().upper()


def generate_barcode(prefix):
    """Generate and reserve a globally unique barcode for *prefix*."""
    prefix = _normalize_prefix(prefix)
    with transaction.atomic():
        sequence, _ = BarcodeSequence.objects.select_for_update().get_or_create(
            prefix=prefix,
            defaults={"next_number": 1, "padding": BARCODE_PADDING},
        )
        if sequence.padding != BARCODE_PADDING:
            sequence.padding = BARCODE_PADDING
            sequence.save(update_fields=["padding", "updated_at"])

        while True:
            barcode = f"{prefix}{sequence.next_number:0{BARCODE_PADDING}d}"
            sequence.next_number += 1
            sequence.save(update_fields=["next_number", "updated_at"])
            if not BarcodeRegistry.objects.filter(barcode=barcode).exists():
                return barcode


def create_barcode_registry(prefix, description=""):
    """Create a BarcodeRegistry row using the next number for *prefix*."""
    prefix = _normalize_prefix(prefix)
    description = (description or "").strip()
    while True:
        barcode = generate_barcode(prefix)
        try:
            with transaction.atomic():
                return BarcodeRegistry.objects.create(
                    prefix=prefix,
                    barcode=barcode,
                    description=description,
                )
        except IntegrityError:
            continue


def ensure_item_barcode(item):
    """Ensure *item* has an ITM barcode and return it."""
    if item.barcode_id:
        return item.barcode
    barcode = create_barcode_registry(
        BarcodeRegistry.Prefix.ITEM, description=getattr(item, "name", "")
    )
    Item.objects.filter(pk=item.pk, barcode__isnull=True).update(barcode=barcode)
    item.barcode = barcode
    item.barcode_id = barcode.pk
    return barcode


def ensure_warehouse_barcode(warehouse):
    """Ensure *warehouse* has a WH barcode and return it."""
    if warehouse.barcode_id:
        return warehouse.barcode
    barcode = create_barcode_registry(
        BarcodeRegistry.Prefix.WAREHOUSE, description=getattr(warehouse, "name", "")
    )
    Warehouse.objects.filter(pk=warehouse.pk, barcode__isnull=True).update(barcode=barcode)
    warehouse.barcode = barcode
    warehouse.barcode_id = barcode.pk
    return barcode


def ensure_location_barcode(location):
    """Ensure *location* has a LOC/RCK barcode matching its type and return it."""
    if location.barcode_id:
        return location.barcode
    prefix = (
        BarcodeRegistry.Prefix.RACK
        if location.location_type == Location.LocationType.RACK
        else BarcodeRegistry.Prefix.LOCATION
    )
    barcode = create_barcode_registry(prefix, description=getattr(location, "name", ""))
    Location.objects.filter(pk=location.pk, barcode__isnull=True).update(barcode=barcode)
    location.barcode = barcode
    location.barcode_id = barcode.pk
    return barcode
