"""Transactional stock balance operations.

All stock mutations must go through this module so balances are updated under
row-level locks and every change is represented by a StockMovement record.
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db import IntegrityError, transaction

from core.models import StockBalance, StockMovement

QTY_QUANT = Decimal("0.001")


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
):
    return StockMovement.objects.create(
        movement_type=movement_type,
        item=item,
        qty=qty,
        source_location=source_location,
        destination_location=destination_location,
        recipient=recipient,
        comment=comment,
    )


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


def create_initial_balance(*, item, location, qty, comment=""):
    """Create an initial balance movement and increase stock at a location."""
    qty = validate_positive_qty(qty)
    with transaction.atomic():
        balance = get_or_create_balance_locked(item, location)
        _increase_balance(balance, qty)
        movement = _create_movement(
            movement_type=StockMovement.MovementType.INITIAL_BALANCE,
            item=item,
            qty=qty,
            destination_location=location,
            comment=comment,
        )
    return movement


def receive_stock(*, item, location, qty, comment=""):
    """Receive stock into a location."""
    qty = validate_positive_qty(qty)
    with transaction.atomic():
        balance = get_or_create_balance_locked(item, location)
        _increase_balance(balance, qty)
        movement = _create_movement(
            movement_type=StockMovement.MovementType.IN,
            item=item,
            qty=qty,
            destination_location=location,
            comment=comment,
        )
    return movement


def issue_stock(*, item, location, qty, recipient, comment=""):
    """Issue stock from a location to a required recipient."""
    if recipient is None:
        raise MissingRecipientError("Recipient is required for stock issue.")
    qty = validate_positive_qty(qty)
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
        )
    return movement


def return_stock(*, item, location, qty, recipient=None, comment=""):
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
            comment=comment,
        )
    return movement


def writeoff_stock(*, item, location, qty, comment=""):
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
        )
    return movement


def transfer_stock(*, item, source_location, target_location, qty, comment=""):
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
        )
    return movement


def adjust_stock(*, item, location, target_qty, comment=""):
    """Set a balance to *target_qty* and create an adjustment movement."""
    target_qty = normalize_decimal_qty(target_qty)
    if target_qty < 0:
        raise InvalidQuantityError("Target quantity cannot be negative.")

    with transaction.atomic():
        balance = get_or_create_balance_locked(item, location)
        current_qty = normalize_decimal_qty(balance.qty)
        difference = normalize_decimal_qty(target_qty - current_qty)
        if difference > 0:
            _increase_balance(balance, difference)
        elif difference < 0:
            _decrease_balance(balance, abs(difference))
        movement = _create_movement(
            movement_type=StockMovement.MovementType.ADJUSTMENT,
            item=item,
            qty=abs(difference),
            source_location=location if difference < 0 else None,
            destination_location=location if difference >= 0 else None,
            comment=comment,
        )
    return movement
