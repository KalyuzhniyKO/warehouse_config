"""Inventory count service operations."""

from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import InventoryCount, InventoryCountLine, StockBalance, StockMovement
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
        balances = StockBalance.objects.filter(warehouse=warehouse, is_active=True).select_related(
            "item__barcode", "warehouse", "location"
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


def _movement_warehouse_delta(movement, warehouse):
    qty = normalize_decimal_qty(movement.qty)
    delta = Decimal("0.000")
    if movement.resolved_source_warehouse == warehouse:
        delta -= qty
    if movement.resolved_destination_warehouse == warehouse:
        delta += qty
    return normalize_decimal_qty(delta)


def _get_inventory_line_movements(line):
    if line.counted_at is None:
        return []
    inventory_count = line.inventory_count
    started_at = inventory_count.started_at
    counted_at = line.counted_at
    warehouse = inventory_count.warehouse
    return list(
        StockMovement.objects.filter(
            item=line.item,
            reversal_of__isnull=True,
        )
        .filter(
            Q(source_warehouse=warehouse)
            | Q(destination_warehouse=warehouse)
            | Q(source_location__warehouse=warehouse)
            | Q(destination_location__warehouse=warehouse)
        )
        .filter(
            Q(occurred_at__gte=started_at, occurred_at__lte=counted_at)
            | Q(cancelled_at__gte=started_at, cancelled_at__lte=counted_at)
        )
        .select_related(
            "source_warehouse",
            "destination_warehouse",
            "source_location__warehouse",
            "destination_location__warehouse",
        )
    )


def _calculate_inventory_line_movement_delta(line, movements):
    inventory_count = line.inventory_count
    started_at = inventory_count.started_at
    counted_at = line.counted_at
    warehouse = inventory_count.warehouse
    movement_delta = Decimal("0.000")
    for movement in movements:
        delta = _movement_warehouse_delta(movement, warehouse)
        occurred_during_count = started_at <= movement.occurred_at <= counted_at
        cancelled_during_count = (
            movement.cancelled_at is not None
            and started_at <= movement.cancelled_at <= counted_at
        )
        if occurred_during_count and not cancelled_during_count:
            movement_delta += delta
        elif cancelled_during_count and movement.occurred_at < started_at:
            movement_delta -= delta
    return normalize_decimal_qty(movement_delta)


def get_inventory_line_movement_delta(line):
    """Return the net warehouse movement from inventory start until counting."""
    return _calculate_inventory_line_movement_delta(
        line, _get_inventory_line_movements(line)
    )


def get_inventory_line_expected_qty(line):
    """Return snapshot quantity plus live warehouse movements until counted_at."""
    return normalize_decimal_qty(
        line.expected_qty + get_inventory_line_movement_delta(line)
    )


def reconcile_inventory_line(line):
    """Attach reconciliation values used by inventory UI and exports."""
    movements = _get_inventory_line_movements(line)
    line.snapshot_qty = line.expected_qty
    line.movement_delta = _calculate_inventory_line_movement_delta(line, movements)
    line.expected_qty_at_count_time = normalize_decimal_qty(
        line.snapshot_qty + line.movement_delta
    )
    line.variance_qty = (
        normalize_decimal_qty(line.actual_qty - line.expected_qty_at_count_time)
        if line.actual_qty is not None
        else Decimal("0.000")
    )
    line.has_movements_during_count = bool(movements)
    return line


def update_inventory_line_actual_qty(*, line, actual_qty, user=None, comment=None):
    """Update a count line's actual quantity without mutating stock balances."""
    line.actual_qty = normalize_decimal_qty(actual_qty)
    line.counted_at = timezone.now()
    line.counted_by = user
    reconcile_inventory_line(line)
    line.difference_qty = line.variance_qty
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
            "inventory_count__warehouse", "item", "location", "location__warehouse"
        ).order_by("pk")
        for line in lines:
            if line.actual_qty is None:
                continue
            reconcile_inventory_line(line)
            difference_qty = line.variance_qty
            if line.difference_qty != difference_qty:
                line.difference_qty = difference_qty
                line.save(update_fields=["difference_qty", "updated_at"])
            if difference_qty == 0:
                continue
            adjust_stock(
                item=line.item,
                warehouse=locked_inventory_count.warehouse,
                location=line.location,
                quantity_delta=difference_qty,
                user=user,
                performed_by=user,
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
