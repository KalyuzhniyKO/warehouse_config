"""Transactional stock balance operations.

All stock mutations must go through this module so balances are updated under
row-level locks and every change is represented by a StockMovement record.
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import Location, StockBalance, StockMovement
from core.services.audit import log_action
from core.services.barcodes import ensure_item_barcode

QTY_QUANT = Decimal("0.001")


CANCELLATION_NEGATIVE_BALANCE_ERROR = _(
    "Неможливо анулювати рух, бо на складі вже недостатньо залишку для зворотної операції."
)


def can_cancel_stock_movement(user, movement):
    return bool(getattr(user, "is_authenticated", False) and user.is_superuser)


def find_best_stock_balance_for_issue(item):
    """Return the active positive balance with the largest quantity for *item*."""
    if item is None:
        return None
    return (
        StockBalance.objects.filter(item=item, is_active=True, qty__gt=0)
        .select_related("location", "location__warehouse")
        .order_by("-qty", "location__warehouse__name", "location__name", "pk")
        .first()
    )


def find_default_stock_return_location():
    """Return the default active stock location for self-service returns."""
    locations = Location.objects.filter(
        is_active=True, warehouse__is_active=True
    ).select_related("warehouse")
    preferred_names = {
        "основна локація",
        "основная локация",
        "main location",
        "default location",
    }
    preferred_location = (
        locations.filter(name__in=preferred_names)
        .order_by("warehouse__name", "name", "pk")
        .first()
    )
    if preferred_location is not None:
        return preferred_location
    for preferred_name in preferred_names:
        preferred_location = (
            locations.filter(name__iexact=preferred_name)
            .order_by("warehouse__name", "name", "pk")
            .first()
        )
        if preferred_location is not None:
            return preferred_location
    return locations.order_by("warehouse__name", "name", "pk").first()


class StockServiceError(ValueError):
    """Base exception for stock service validation errors."""


class InvalidQuantityError(StockServiceError):
    """Raised when a quantity is invalid for the requested operation."""


class InsufficientStockError(StockServiceError):
    """Raised when an operation would make a stock balance negative."""


class SameLocationTransferError(StockServiceError):
    """Raised when a transfer uses the same source and target location."""


class MissingRecipientError(StockServiceError):
    """Raised when an issue operation does not specify a recipient."""


def normalize_decimal_qty(qty):
    """Return *qty* as a Decimal rounded to the model's 3 decimal places."""
    try:
        decimal_qty = qty if isinstance(qty, Decimal) else Decimal(str(qty))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise InvalidQuantityError("Quantity must be a decimal number.") from exc

    if not decimal_qty.is_finite():
        raise InvalidQuantityError("Quantity must be a finite decimal number.")

    return decimal_qty.quantize(QTY_QUANT, rounding=ROUND_HALF_UP)


def validate_positive_qty(qty):
    """Normalize and validate that *qty* is greater than zero."""
    decimal_qty = normalize_decimal_qty(qty)
    if decimal_qty <= 0:
        raise InvalidQuantityError("Quantity must be greater than zero.")
    return decimal_qty


def get_or_create_balance_locked(item, location):
    """Return a StockBalance row locked for update, creating it when needed.

    This helper must be called inside ``transaction.atomic()`` so the
    ``select_for_update()`` lock is held until the operation commits.
    """
    if not transaction.get_connection().in_atomic_block:
        raise StockServiceError("Stock balance locks require an active transaction.")

    queryset = StockBalance.objects.select_for_update()
    try:
        return queryset.get(item=item, location=location)
    except StockBalance.DoesNotExist:
        try:
            return StockBalance.objects.create(
                item=item, location=location, qty=Decimal("0.000")
            )
        except IntegrityError:
            return queryset.get(item=item, location=location)


def _create_movement(
    *,
    movement_type,
    item,
    qty,
    source_location=None,
    destination_location=None,
    recipient=None,
    comment="",
    occurred_at=None,
    issue_reason="",
    department="",
    document_number="",
    inventory_count=None,
    performed_by=None,
    request=None,
):
    kwargs = {}
    if occurred_at is not None:
        kwargs["occurred_at"] = occurred_at
    movement = StockMovement.objects.create(
        movement_type=movement_type,
        item=item,
        qty=qty,
        source_location=source_location,
        destination_location=destination_location,
        recipient=recipient,
        comment=comment,
        issue_reason=issue_reason,
        department=department,
        document_number=document_number,
        inventory_count=inventory_count,
        performed_by=performed_by,
        created_by=performed_by,
        **kwargs,
    )
    log_action(
        performed_by,
        "stock_movement.created",
        obj=movement,
        changes={
            "movement_type": movement.movement_type,
            "item_id": movement.item_id,
            "qty": str(movement.qty),
        },
        request=request,
    )
    return movement


def _increase_balance(balance, qty):
    balance.qty = normalize_decimal_qty(balance.qty + qty)
    balance.save(update_fields=["qty", "updated_at"])
    return balance


def _decrease_balance(balance, qty):
    if balance.qty < qty:
        raise InsufficientStockError(
            f"Insufficient stock for {balance.item} at {balance.location}: "
            f"available {balance.qty}, requested {qty}."
        )
    balance.qty = normalize_decimal_qty(balance.qty - qty)
    if balance.qty < 0:
        raise InsufficientStockError("Stock balance cannot become negative.")
    balance.save(update_fields=["qty", "updated_at"])
    return balance


def create_initial_balance(
    *, item, location, qty, comment="", occurred_at=None, performed_by=None, request=None
):
    """Create an initial balance movement and increase stock at a location."""
    qty = validate_positive_qty(qty)
    with transaction.atomic():
        ensure_item_barcode(item)
        balance = get_or_create_balance_locked(item, location)
        _increase_balance(balance, qty)
        movement = _create_movement(
            movement_type=StockMovement.MovementType.INITIAL_BALANCE,
            item=item,
            qty=qty,
            destination_location=location,
            comment=comment,
            occurred_at=occurred_at,
            performed_by=performed_by,
            request=request,
        )
    return movement


def receive_stock(
    *, item, location, qty, comment="", occurred_at=None, performed_by=None, request=None
):
    """Receive stock into a location."""
    qty = validate_positive_qty(qty)
    with transaction.atomic():
        ensure_item_barcode(item)
        balance = get_or_create_balance_locked(item, location)
        _increase_balance(balance, qty)
        movement = _create_movement(
            movement_type=StockMovement.MovementType.IN,
            item=item,
            qty=qty,
            destination_location=location,
            comment=comment,
            occurred_at=occurred_at,
            performed_by=performed_by,
            request=request,
        )
    return movement


def issue_stock(
    *,
    item,
    location,
    qty,
    recipient=None,
    issue_reason=StockMovement.IssueReason.OTHER,
    department="",
    document_number="",
    comment="",
    occurred_at=None,
    performed_by=None,
    request=None,
):
    """Issue stock from a location and record the business reason."""
    qty = validate_positive_qty(qty)
    if recipient is None:
        raise MissingRecipientError(
            _("Для видачі товару потрібно вказати отримувача.")
        )
    with transaction.atomic():
        balance = get_or_create_balance_locked(item, location)
        _decrease_balance(balance, qty)
        movement = _create_movement(
            movement_type=StockMovement.MovementType.OUT,
            item=item,
            qty=qty,
            source_location=location,
            recipient=recipient,
            comment=comment,
            occurred_at=occurred_at,
            issue_reason=issue_reason,
            department=(department or "").strip(),
            document_number=(document_number or "").strip(),
            performed_by=performed_by,
            request=request,
        )
    return movement


def return_stock(
    *,
    item,
    location,
    qty,
    recipient=None,
    department="",
    comment="",
    occurred_at=None,
    performed_by=None,
    request=None,
):
    """Return stock back into a location."""
    qty = validate_positive_qty(qty)
    with transaction.atomic():
        balance = get_or_create_balance_locked(item, location)
        _increase_balance(balance, qty)
        movement = _create_movement(
            movement_type=StockMovement.MovementType.RETURN,
            item=item,
            qty=qty,
            destination_location=location,
            recipient=recipient,
            department=(department or "").strip(),
            comment=comment,
            occurred_at=occurred_at,
            performed_by=performed_by,
            request=request,
        )
    return movement


def writeoff_stock(
    *, item, location, qty, comment="", occurred_at=None, performed_by=None, request=None
):
    """Write off stock from a location."""
    qty = validate_positive_qty(qty)
    with transaction.atomic():
        balance = get_or_create_balance_locked(item, location)
        _decrease_balance(balance, qty)
        movement = _create_movement(
            movement_type=StockMovement.MovementType.WRITEOFF,
            item=item,
            qty=qty,
            source_location=location,
            comment=comment,
            occurred_at=occurred_at,
            performed_by=performed_by,
            request=request,
        )
    return movement


def transfer_stock(
    *,
    item,
    source_location,
    target_location,
    qty,
    comment="",
    occurred_at=None,
    performed_by=None,
    request=None,
):
    """Transfer stock between two different locations in a single transaction."""
    if source_location == target_location:
        raise SameLocationTransferError(
            "Source and target locations must be different."
        )
    qty = validate_positive_qty(qty)
    with transaction.atomic():
        source_balance = get_or_create_balance_locked(item, source_location)
        target_balance = get_or_create_balance_locked(item, target_location)
        _decrease_balance(source_balance, qty)
        _increase_balance(target_balance, qty)
        movement = _create_movement(
            movement_type=StockMovement.MovementType.TRANSFER,
            item=item,
            qty=qty,
            source_location=source_location,
            destination_location=target_location,
            comment=comment,
            occurred_at=occurred_at,
            performed_by=performed_by,
            request=request,
        )
    return movement


def adjust_stock(
    *,
    item,
    location,
    quantity_delta=None,
    warehouse=None,
    user=None,
    comment="",
    occurred_at=None,
    inventory_count=None,
    target_qty=None,
    performed_by=None,
    request=None,
):
    """Adjust a stock balance by delta and create an adjustment movement.

    ``target_qty`` is kept as a compatibility path for existing callers. New
    code should pass ``quantity_delta`` so the movement quantity represents the
    absolute adjustment amount.
    """
    if warehouse is not None and location.warehouse_id != warehouse.pk:
        raise StockServiceError("Location does not belong to the selected warehouse.")

    with transaction.atomic():
        balance = get_or_create_balance_locked(item, location)
        if target_qty is not None:
            target_qty = normalize_decimal_qty(target_qty)
            if target_qty < 0:
                raise InvalidQuantityError("Target quantity cannot be negative.")
            quantity_delta = target_qty - normalize_decimal_qty(balance.qty)
        elif quantity_delta is None:
            raise InvalidQuantityError("Quantity delta is required.")

        quantity_delta = normalize_decimal_qty(quantity_delta)
        if quantity_delta > 0:
            _increase_balance(balance, quantity_delta)
        elif quantity_delta < 0:
            _decrease_balance(balance, abs(quantity_delta))

        movement = _create_movement(
            movement_type=StockMovement.MovementType.ADJUSTMENT,
            item=item,
            qty=abs(quantity_delta),
            source_location=location if quantity_delta < 0 else None,
            destination_location=location if quantity_delta >= 0 else None,
            comment=comment,
            occurred_at=occurred_at,
            inventory_count=inventory_count,
            performed_by=performed_by or user,
            request=request,
        )
    return movement


def _format_location(location):
    if location is None:
        return None
    return str(location)


def _apply_cancellation_delta(*, item, location, qty_delta):
    if location is None or qty_delta == 0:
        return None
    balance = get_or_create_balance_locked(item, location)
    if qty_delta > 0:
        return _increase_balance(balance, qty_delta)
    try:
        return _decrease_balance(balance, abs(qty_delta))
    except InsufficientStockError as exc:
        raise InsufficientStockError(CANCELLATION_NEGATIVE_BALANCE_ERROR) from exc


def _cancellation_deltas(movement):
    qty = validate_positive_qty(movement.qty)
    movement_type = movement.movement_type
    if movement_type in {
        StockMovement.MovementType.IN,
        StockMovement.MovementType.INITIAL_BALANCE,
        StockMovement.MovementType.RETURN,
    }:
        return [(movement.destination_location, -qty)]
    if movement_type in {
        StockMovement.MovementType.OUT,
        StockMovement.MovementType.WRITEOFF,
    }:
        return [(movement.source_location, qty)]
    if movement_type == StockMovement.MovementType.TRANSFER:
        return [(movement.source_location, qty), (movement.destination_location, -qty)]
    if movement_type == StockMovement.MovementType.ADJUSTMENT:
        deltas = []
        if movement.source_location_id:
            deltas.append((movement.source_location, qty))
        if movement.destination_location_id:
            deltas.append((movement.destination_location, -qty))
        return deltas
    raise StockServiceError(_("Неможливо анулювати рух"))


def cancel_stock_movement(*, movement, cancelled_by, reason, request=None):
    reason = (reason or "").strip()
    if not reason:
        raise StockServiceError(_("Причина анулювання обов'язкова."))
    if not can_cancel_stock_movement(cancelled_by, movement):
        raise StockServiceError(_("Неможливо анулювати рух"))

    with transaction.atomic():
        movement = (
            StockMovement.objects.select_for_update()
            .select_related(
                "item",
                "source_location",
                "source_location__warehouse",
                "destination_location",
                "destination_location__warehouse",
            )
            .get(pk=movement.pk)
        )
        if movement.is_cancelled:
            raise StockServiceError(_("Неможливо анулювати рух: рух уже анульовано."))
        if movement.reversal_of_id:
            raise StockServiceError(_("Неможливо анулювати рух анулювання."))

        deltas = _cancellation_deltas(movement)
        if not deltas:
            raise StockServiceError(_("Неможливо анулювати рух"))

        # Apply balance changes with row-level locks before creating the audit/history rows.
        for location, qty_delta in deltas:
            _apply_cancellation_delta(
                item=movement.item, location=location, qty_delta=qty_delta
            )

        cancellation_source = None
        cancellation_destination = None
        for location, qty_delta in deltas:
            if qty_delta < 0 and cancellation_source is None:
                cancellation_source = location
            elif qty_delta > 0 and cancellation_destination is None:
                cancellation_destination = location
        if cancellation_source is None and cancellation_destination is None:
            cancellation_destination = movement.destination_location or movement.source_location

        cancellation_movement = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.ADJUSTMENT,
            item=movement.item,
            qty=movement.qty,
            source_location=cancellation_source,
            destination_location=cancellation_destination,
            recipient=movement.recipient,
            issue_reason="",
            department=movement.department,
            document_number=movement.document_number,
            performed_by=cancelled_by,
            created_by=cancelled_by,
            comment=_("Анулювання руху #%(movement_id)s. Причина: %(reason)s")
            % {"movement_id": movement.pk, "reason": reason},
            reversal_of=movement,
        )

        movement.is_cancelled = True
        movement.cancelled_at = timezone.now()
        movement.cancelled_by = cancelled_by
        movement.cancellation_reason = reason
        movement.cancellation_movement = cancellation_movement
        movement.save(
            update_fields=[
                "is_cancelled",
                "cancelled_at",
                "cancelled_by",
                "cancellation_reason",
                "cancellation_movement",
                "updated_at",
            ]
        )

        log_action(
            cancelled_by,
            "stock_movement.cancelled",
            obj=movement,
            changes={
                "original_movement_id": movement.pk,
                "cancellation_movement_id": cancellation_movement.pk,
                "reason": reason,
                "cancelled_by": getattr(cancelled_by, "pk", None),
                "item_id": movement.item_id,
                "qty": str(movement.qty),
                "source_location": _format_location(movement.source_location),
                "destination_location": _format_location(movement.destination_location),
            },
            request=request,
        )
    return cancellation_movement
