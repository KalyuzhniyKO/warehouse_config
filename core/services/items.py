"""Backward-compatible item lookup helpers."""

from core.services.barcodes import resolve_item_barcode


def find_item_by_barcode(value):
    """Return an active item matching *value* by barcode or internal code."""
    return resolve_item_barcode(value)
