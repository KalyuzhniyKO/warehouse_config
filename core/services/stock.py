"""Transactional stock balance operations.

All stock mutations must go through this module so balances are updated under
row-level locks and every change is represented by a StockMovement record.
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from core.models import StockBalance, StockMovement, Warehouse
from core.services.audit import log_action
from core.services.barcodes import ensure_item_barcode
from core.services.warehouse_access import get_accessible_warehouses

QTY_QUANT = Decimal("0.001")


def _warehouse_from_location(location):
    return location.warehouse if location is not None else None


def resolve_warehouse(*, warehouse=None, location=None, field_name="warehouse"):
    """Return the explicit warehouse or derive it from a legacy location."""
    if warehouse is None:
        warehouse = _warehouse_from_location(location)
    if warehouse is None:
        raise StockServiceError(f"{field_name} is required.")
    if location is not None and location.warehouse_id != warehouse.pk:
        raise StockServiceError("Location does not belong to the selected warehouse.")
    return warehouse


def find_best_stock_balance_for_issue(item, user=None):
    """Return the active positive warehouse balance with the largest quantity."""
    if item is None:
        return None
    queryset = StockBalance.objects.filter(item=item, is_active=True, qty__gt=0)
    if user is not None:
        queryset = queryset.filter(warehouse__in=get_accessible_warehouses(user))
    return (
        queryset.select_related("warehouse", "location")
        .order_by("-qty", "warehouse__name", "pk")
        .first()
    )


def find_default_stock_return_warehouse(user=None):
    """Return the default active warehouse for self-service returns."""
    warehouses = Warehouse.objects.filter(is_active=True)
    if user is not None:
        warehouses = warehouses.filter(pk__in=get_accessible_warehouses(user).values("pk"))
    return warehouses.order_by("name", "pk").first()


# Backwards-compatible name for callers that still ask for a return location.
def find_default_stock_return_location(user=None):
    warehouse = find_default_stock_return_warehouse(user)
    if warehouse is None:
        return None
    return warehouse.locations.filter(is_active=True).order_by("name", "pk").first()


class StockServiceError(ValueError):
    """Base exception for stock service validation errors."""


class InvalidQuantityError(StockServiceError):
    """Raised when a quantity is invalid for the requested operation."""


class InsufficientStockError(StockServiceError):
    """Raised when an operation would make a stock balance negative."""


class SameLocationTransferError(StockServiceError):
    """Raised when a transfer uses the same source and target location."""


class SameWarehouseTransferError(StockServiceError):
    """Raised when a warehouse-level transfer uses the same warehouse."""


class MissingRecipientError(StockServiceError):
    """Raised when an issue operation does not specify a recipient."""


class MissingReturnRecipientError(StockServiceError):
    """Raised when a validated return does not specify a recipient."""


class ReturnQuantityExceededError(StockServiceError):
    """Raised when a return exceeds the recipient's issued-not-returned quantity."""


RETURN_RECIPIENT_REQUIRED_ERROR = _("Для повернення товару потрібно вказати отримувача.")
RETURN_QUANTITY_EXCEEDED_ERROR = _(
    "Неможливо повернути більше, ніж було видано цьому отримувачу."
)


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


def _return_eligibility_movements(item, recipient, *, lock=False):
    queryset = StockMovement.objects.filter(
        item=item,
        recipient=recipient,
        is_cancelled=False,
        reversal_of__isnull=True,
    ).filter(
        Q(movement_type=StockMovement.MovementType.OUT)
        | Q(movement_type=StockMovement.MovementType.RETURN)
    )
    if lock:
        queryset = queryset.select_for_update()
    return queryset


def get_available_return_qty(item, recipient, *, lock=False):
    """Return active issued quantity minus active returned quantity."""
    if item is None or recipient is None:
        return Decimal("0.000")
    if lock:
        if not transaction.get_connection().in_atomic_block:
            raise StockServiceError("Return eligibility locks require an active transaction.")
        list(
            _return_eligibility_movements(item, recipient, lock=True).values_list(
                "pk", flat=True
            )
        )
    issued_qty = Decimal("0.000")
    returned_qty = Decimal("0.000")
    for movement in _return_eligibility_movements(item, recipient):
        if movement.movement_type == StockMovement.MovementType.OUT:
            issued_qty += movement.qty
        else:
            returned_qty += movement.qty
    return normalize_decimal_qty(issued_qty - returned_qty)


def get_or_create_balance_locked(item, warehouse=None, location=None):
    """Return a warehouse-level StockBalance row locked for update.

    ``location`` is accepted for compatibility and optional display, but the
    locked balance identity is always item + warehouse.
    """
    if not transaction.get_connection().in_atomic_block:
        raise StockServiceError("Stock balance locks require an active transaction.")

    warehouse = resolve_warehouse(warehouse=warehouse, location=location)
    queryset = StockBalance.objects.select_for_update().filter(is_active=True)
    try:
        return queryset.get(item=item, warehouse=warehouse)
    except StockBalance.DoesNotExist:
        try:
            return StockBalance.objects.create(
                item=item, warehouse=warehouse, location=location, qty=Decimal("0.000")
            )
        except IntegrityError:
            return queryset.get(item=item, warehouse=warehouse)


def _create_movement(
    *,
    movement_type,
    item,
    qty,
    source_warehouse=None,
    destination_warehouse=None,
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
    purchase_request=None,
):
    source_warehouse = resolve_warehouse(
        warehouse=source_warehouse, location=source_location, field_name="source_warehouse"
    ) if source_warehouse is not None or source_location is not None else None
    destination_warehouse = resolve_warehouse(
        warehouse=destination_warehouse,
        location=destination_location,
        field_name="destination_warehouse",
    ) if destination_warehouse is not None or destination_location is not None else None
    kwargs = {}
    if occurred_at is not None:
        kwargs["occurred_at"] = occurred_at
    movement = StockMovement.objects.create(
        movement_type=movement_type,
        item=item,
        qty=qty,
        source_warehouse=source_warehouse,
        destination_warehouse=destination_warehouse,
        source_location=source_location,
        destination_location=destination_location,
        recipient=recipient,
        comment=comment,
        issue_reason=issue_reason,
        department=department,
        document_number=document_number,
        inventory_count=inventory_count,
        purchase_request=purchase_request,
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
            f"Insufficient stock for {balance.item} at {balance.warehouse}: "
            f"available {balance.qty}, requested {qty}."
        )
    balance.qty = normalize_decimal_qty(balance.qty - qty)
    if balance.qty < 0:
        raise InsufficientStockError("Stock balance cannot become negative.")
    balance.save(update_fields=["qty", "updated_at"])
    return balance


def create_initial_balance(
    *, item, warehouse=None, location=None, qty, comment="", occurred_at=None, performed_by=None, request=None
):
    """Create an initial balance movement and increase stock in a warehouse."""
    qty = validate_positive_qty(qty)
    warehouse = resolve_warehouse(warehouse=warehouse, location=location)
    with transaction.atomic():
        ensure_item_barcode(item)
        balance = get_or_create_balance_locked(item, warehouse=warehouse, location=location)
        _increase_balance(balance, qty)
        movement = _create_movement(
            movement_type=StockMovement.MovementType.INITIAL_BALANCE,
            item=item,
            qty=qty,
            destination_warehouse=warehouse,
            destination_location=location,
            comment=comment,
            occurred_at=occurred_at,
            performed_by=performed_by,
            request=request,
        )
    return movement


def receive_stock(
    *,
    item,
    warehouse=None,
    location=None,
    qty,
    comment="",
    occurred_at=None,
    performed_by=None,
    request=None,
    purchase_request=None,
):
    """Receive stock into a warehouse; location is optional."""
    qty = validate_positive_qty(qty)
    warehouse = resolve_warehouse(warehouse=warehouse, location=location)
    with transaction.atomic():
        if purchase_request is not None:
            from core.models import PurchaseRequest  # noqa: PLC0415
            from core.services.purchase_requests import (  # noqa: PLC0415
                PURCHASE_REQUEST_NOT_RECEIVABLE_ERROR,
                PURCHASE_REQUEST_QTY_EXCEEDED_ERROR,
                can_receive_against_purchase_request,
                get_received_purchase_request_qty,
                sync_purchase_request_receiving_status,
            )

            purchase_request = PurchaseRequest.objects.select_for_update().get(
                pk=purchase_request.pk
            )
            if (
                purchase_request.status
                not in {
                    PurchaseRequest.Status.APPROVED,
                    PurchaseRequest.Status.ORDERED,
                    PurchaseRequest.Status.PARTIALLY_RECEIVED,
                }
                or purchase_request.approval_status
                != PurchaseRequest.ApprovalStatus.APPROVED
            ):
                raise StockServiceError(PURCHASE_REQUEST_NOT_RECEIVABLE_ERROR)
            if (
                performed_by is not None
                and not can_receive_against_purchase_request(
                    performed_by, purchase_request
                )
            ):
                raise StockServiceError(PURCHASE_REQUEST_NOT_RECEIVABLE_ERROR)
            remaining_qty = (
                purchase_request.requested_qty
                - get_received_purchase_request_qty(purchase_request)
            )
            if qty > remaining_qty:
                raise StockServiceError(PURCHASE_REQUEST_QTY_EXCEEDED_ERROR)
        ensure_item_barcode(item)
        balance = get_or_create_balance_locked(item, warehouse=warehouse, location=location)
        _increase_balance(balance, qty)
        movement = _create_movement(
            movement_type=StockMovement.MovementType.IN,
            item=item,
            qty=qty,
            destination_warehouse=warehouse,
            destination_location=location,
            comment=comment,
            occurred_at=occurred_at,
            performed_by=performed_by,
            request=request,
            purchase_request=purchase_request,
        )
        if purchase_request is not None:
            sync_purchase_request_receiving_status(purchase_request)
    return movement


def issue_stock(
    *,
    item,
    warehouse=None,
    location=None,
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
    """Issue stock from a warehouse; location is optional."""
    qty = validate_positive_qty(qty)
    warehouse = resolve_warehouse(warehouse=warehouse, location=location)
    if recipient is None:
        raise MissingRecipientError(_("Для видачі товару потрібно вказати отримувача."))
    with transaction.atomic():
        balance = get_or_create_balance_locked(item, warehouse=warehouse, location=location)
        _decrease_balance(balance, qty)
        movement = _create_movement(
            movement_type=StockMovement.MovementType.OUT,
            item=item,
            qty=qty,
            source_warehouse=warehouse,
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
    warehouse=None,
    location=None,
    qty,
    recipient=None,
    department="",
    comment="",
    occurred_at=None,
    performed_by=None,
    request=None,
    allow_unmatched_return=False,
):
    """Return stock back into a warehouse; location is optional."""
    qty = validate_positive_qty(qty)
    warehouse = resolve_warehouse(warehouse=warehouse, location=location)
    if recipient is None and not allow_unmatched_return:
        raise MissingReturnRecipientError(RETURN_RECIPIENT_REQUIRED_ERROR)
    with transaction.atomic():
        if not allow_unmatched_return:
            available_qty = get_available_return_qty(item, recipient, lock=True)
            if available_qty <= 0 or qty > available_qty:
                raise ReturnQuantityExceededError(RETURN_QUANTITY_EXCEEDED_ERROR)
        balance = get_or_create_balance_locked(item, warehouse=warehouse, location=location)
        _increase_balance(balance, qty)
        movement = _create_movement(
            movement_type=StockMovement.MovementType.RETURN,
            item=item,
            qty=qty,
            destination_warehouse=warehouse,
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
    *, item, warehouse=None, location=None, qty, comment="", occurred_at=None, performed_by=None, request=None
):
    """Write off stock from a warehouse; location is optional."""
    qty = validate_positive_qty(qty)
    warehouse = resolve_warehouse(warehouse=warehouse, location=location)
    with transaction.atomic():
        balance = get_or_create_balance_locked(item, warehouse=warehouse, location=location)
        _decrease_balance(balance, qty)
        movement = _create_movement(
            movement_type=StockMovement.MovementType.WRITEOFF,
            item=item,
            qty=qty,
            source_warehouse=warehouse,
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
    source_warehouse=None,
    destination_warehouse=None,
    source_location=None,
    target_location=None,
    destination_location=None,
    qty,
    comment="",
    occurred_at=None,
    performed_by=None,
    request=None,
):
    """Transfer stock between warehouses; locations are optional."""
    if destination_location is None:
        destination_location = target_location
    source_warehouse = resolve_warehouse(
        warehouse=source_warehouse, location=source_location, field_name="source_warehouse"
    )
    destination_warehouse = resolve_warehouse(
        warehouse=destination_warehouse,
        location=destination_location,
        field_name="destination_warehouse",
    )
    same_warehouse_location_transfer = False
    if source_warehouse == destination_warehouse:
        if source_location is not None and destination_location is not None and source_location == destination_location:
            raise SameLocationTransferError("Source and target locations must be different.")
        if source_location is not None and destination_location is not None:
            same_warehouse_location_transfer = True
        else:
            raise SameWarehouseTransferError("Source and target warehouses must be different.")
    qty = validate_positive_qty(qty)
    with transaction.atomic():
        source_balance = get_or_create_balance_locked(item, warehouse=source_warehouse, location=source_location)
        if same_warehouse_location_transfer:
            _decrease_balance(source_balance, qty)
            target_balance, _ = StockBalance.objects.get_or_create(
                item=item,
                warehouse=destination_warehouse,
                location=destination_location,
                defaults={"qty": Decimal("0.000"), "is_active": False},
            )
            _increase_balance(target_balance, qty)
        else:
            target_balance = get_or_create_balance_locked(item, warehouse=destination_warehouse, location=destination_location)
            _decrease_balance(source_balance, qty)
            _increase_balance(target_balance, qty)
        movement = _create_movement(
            movement_type=StockMovement.MovementType.TRANSFER,
            item=item,
            qty=qty,
            source_warehouse=source_warehouse,
            destination_warehouse=destination_warehouse,
            source_location=source_location,
            destination_location=destination_location,
            comment=comment,
            occurred_at=occurred_at,
            performed_by=performed_by,
            request=request,
        )
    return movement


def adjust_stock(
    *,
    item,
    warehouse=None,
    location=None,
    quantity_delta=None,
    user=None,
    comment="",
    occurred_at=None,
    inventory_count=None,
    target_qty=None,
    performed_by=None,
    request=None,
):
    """Adjust a warehouse stock balance by delta and create a movement."""
    warehouse = resolve_warehouse(warehouse=warehouse, location=location)

    with transaction.atomic():
        balance = get_or_create_balance_locked(item, warehouse=warehouse, location=location)
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
            source_warehouse=warehouse if quantity_delta < 0 else None,
            destination_warehouse=warehouse if quantity_delta >= 0 else None,
            source_location=location if quantity_delta < 0 else None,
            destination_location=location if quantity_delta >= 0 else None,
            comment=comment,
            occurred_at=occurred_at,
            inventory_count=inventory_count,
            performed_by=performed_by or user,
            request=request,
        )
    return movement


from core.services.stock_cancellation import (  # noqa: E402
    can_cancel_stock_movement,
    cancel_stock_movement,
)
