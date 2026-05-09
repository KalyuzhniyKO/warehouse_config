"""Inventory count service operations."""

from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import InventoryCount, InventoryCountLine, StockBalance
from core.services.stock import adjust_stock, normalize_decimal_qty

INVENTORY_NUMBER_PREFIX = "INV-"
INVENTORY_NUMBER_PADDING = 10


class InventoryServiceError(ValueError):
    """Base exception for inventory count service validation errors."""


class InventoryAlreadyCompletedError(InventoryServiceError):
    """Raised when a completed inventory count is completed again."""


class InventoryCancelledError(InventoryServiceError):
    """Raised when a cancelled inventory count is completed."""


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


def _raise_for_non_completable_status(inventory_count):
    if inventory_count.status == InventoryCount.Status.COMPLETED:
        raise InventoryAlreadyCompletedError(_("Інвентаризацію вже завершено."))
    if inventory_count.status == InventoryCount.Status.CANCELLED:
        raise InventoryCancelledError(
            _("Неможливо завершити скасовану інвентаризацію.")
        )
    raise InventoryServiceError(
        _("Only inventory counts in progress can be completed.")
    )


def complete_inventory_count(*, inventory_count, user=None):
    """Complete an inventory count and adjust stock balances to actual quantities."""
    with transaction.atomic():
        locked_inventory_count = (
            InventoryCount.objects.select_for_update()
            .select_related("warehouse")
            .get(pk=inventory_count.pk)
        )
        if locked_inventory_count.status != InventoryCount.Status.IN_PROGRESS:
            _raise_for_non_completable_status(locked_inventory_count)

        lines = locked_inventory_count.lines.select_related(
            "item", "location", "location__warehouse"
        ).order_by("pk")
        for line in lines:
            actual_qty = line.actual_qty
            if actual_qty is None:
                actual_qty = line.expected_qty
            difference_qty = normalize_decimal_qty(actual_qty - line.expected_qty)
            if difference_qty == 0:
                continue
            adjust_stock(
                item=line.item,
                warehouse=locked_inventory_count.warehouse,
                location=line.location,
                quantity_delta=difference_qty,
                user=user,
                comment=_("Коригування за інвентаризацією"),
                inventory_count=locked_inventory_count,
            )

        locked_inventory_count.status = InventoryCount.Status.COMPLETED
        locked_inventory_count.completed_at = timezone.now()
        locked_inventory_count.approved_by = user
        locked_inventory_count.save(
            update_fields=["status", "completed_at", "approved_by", "updated_at"]
        )
    return locked_inventory_count
