"""Inventory count service operations."""

from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from core.models import InventoryCount, InventoryCountLine, StockBalance
from core.services.stock import normalize_decimal_qty

INVENTORY_NUMBER_PREFIX = "INV-"
INVENTORY_NUMBER_PADDING = 10


def generate_inventory_number():
    """Generate the next inventory count number inside a transaction when possible."""
    queryset = InventoryCount.objects.order_by("-number")
    if transaction.get_connection().in_atomic_block:
        queryset = queryset.select_for_update()
    last_inventory = queryset.first()
    next_number = 1
    if last_inventory:
        try:
            next_number = int(last_inventory.number.removeprefix(INVENTORY_NUMBER_PREFIX)) + 1
        except ValueError:
            next_number = last_inventory.pk + 1
    return f"{INVENTORY_NUMBER_PREFIX}{next_number:0{INVENTORY_NUMBER_PADDING}d}"


def _create_inventory_count_header(*, warehouse, location=None, user=None, comment=""):
    for _ in range(3):
        number = generate_inventory_number()
        try:
            return InventoryCount.objects.create(
                number=number,
                warehouse=warehouse,
                location=location,
                status=InventoryCount.Status.IN_PROGRESS,
                started_at=timezone.now(),
                created_by=user,
                comment=comment,
            )
        except IntegrityError:
            continue
    raise IntegrityError("Could not generate a unique inventory count number.")


def create_inventory_count(*, warehouse, location=None, user=None, comment=""):
    """Create an in-progress inventory count from current stock balances."""
    with transaction.atomic():
        inventory_count = _create_inventory_count_header(
            warehouse=warehouse,
            location=location,
            user=user,
            comment=comment,
        )
        balances = StockBalance.objects.filter(location__warehouse=warehouse).select_related(
            "item__barcode", "location"
        )
        if location is not None:
            balances = balances.filter(location=location)

        lines = [
            InventoryCountLine(
                inventory_count=inventory_count,
                item=balance.item,
                location=balance.location,
                barcode=balance.item.barcode.barcode if balance.item.barcode_id else "",
                expected_qty=balance.qty,
                actual_qty=None,
                difference_qty=Decimal("0.000"),
            )
            for balance in balances
        ]
        InventoryCountLine.objects.bulk_create(lines)
    return inventory_count


def update_inventory_line_actual_qty(*, line, actual_qty, user=None, comment=None):
    """Update a count line's actual quantity without mutating stock balances."""
    line.actual_qty = normalize_decimal_qty(actual_qty)
    line.difference_qty = line.actual_qty - line.expected_qty
    line.counted_at = timezone.now()
    line.counted_by = user
    update_fields = [
        "actual_qty",
        "difference_qty",
        "counted_at",
        "counted_by",
        "updated_at",
    ]
    if comment is not None:
        line.comment = comment
        update_fields.append("comment")
    line.save(update_fields=update_fields)
    return line
