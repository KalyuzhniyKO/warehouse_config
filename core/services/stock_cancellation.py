"""Stock movement cancellation service.

This module owns cancellation eligibility, reversal balance deltas, reversal
movement creation, and the cancellation audit entry. Public functions are
re-exported from ``core.services.stock`` for backwards compatibility.
"""

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import StockMovement
from core.permissions import can_cancel_movement
from core.services.audit import log_action

CANCELLATION_NEGATIVE_BALANCE_ERROR = _(
    "Неможливо анулювати рух, бо на складі вже недостатньо залишку для зворотної операції."
)


def can_cancel_stock_movement(user, movement):
    return can_cancel_movement(user, movement)


def _stock_service():
    """Import lower-level stock helpers lazily to avoid module import cycles."""
    from core.services import stock as stock_service  # noqa: PLC0415

    return stock_service


def _format_location(location):
    if location is None:
        return None
    return str(location)


def _apply_cancellation_delta(*, item, warehouse, location, qty_delta):
    stock_service = _stock_service()

    if warehouse is None or qty_delta == 0:
        return None
    if location is not None:
        try:
            balance = stock_service.StockBalance.objects.select_for_update().get(
                item=item, location=location
            )
        except stock_service.StockBalance.DoesNotExist:
            balance = stock_service.get_or_create_balance_locked(
                item, warehouse=warehouse, location=location
            )
    else:
        balance = stock_service.get_or_create_balance_locked(
            item, warehouse=warehouse, location=location
        )
    if qty_delta > 0:
        return stock_service._increase_balance(balance, qty_delta)
    try:
        return stock_service._decrease_balance(balance, abs(qty_delta))
    except stock_service.InsufficientStockError as exc:
        raise stock_service.InsufficientStockError(
            CANCELLATION_NEGATIVE_BALANCE_ERROR
        ) from exc


def _cancellation_deltas(movement):
    stock_service = _stock_service()

    qty = stock_service.validate_positive_qty(movement.qty)
    movement_type = movement.movement_type
    if movement_type in {
        StockMovement.MovementType.IN,
        StockMovement.MovementType.INITIAL_BALANCE,
        StockMovement.MovementType.RETURN,
    }:
        return [(movement.resolved_destination_warehouse, movement.destination_location, -qty)]
    if movement_type in {
        StockMovement.MovementType.OUT,
        StockMovement.MovementType.WRITEOFF,
    }:
        return [(movement.resolved_source_warehouse, movement.source_location, qty)]
    if movement_type == StockMovement.MovementType.TRANSFER:
        return [(movement.resolved_source_warehouse, movement.source_location, qty), (movement.resolved_destination_warehouse, movement.destination_location, -qty)]
    if movement_type == StockMovement.MovementType.ADJUSTMENT:
        deltas = []
        if movement.source_location_id or movement.source_warehouse_id:
            deltas.append((movement.resolved_source_warehouse, movement.source_location, qty))
        if movement.destination_location_id or movement.destination_warehouse_id:
            deltas.append((movement.resolved_destination_warehouse, movement.destination_location, -qty))
        return deltas
    raise stock_service.StockServiceError(_("Неможливо анулювати рух"))


def _cancellation_locations(deltas, movement):
    cancellation_source_warehouse = None
    cancellation_destination_warehouse = None
    cancellation_source = None
    cancellation_destination = None
    for warehouse, location, qty_delta in deltas:
        if qty_delta < 0 and cancellation_source_warehouse is None:
            cancellation_source_warehouse = warehouse
            cancellation_source = location
        elif qty_delta > 0 and cancellation_destination_warehouse is None:
            cancellation_destination_warehouse = warehouse
            cancellation_destination = location
    if cancellation_source_warehouse is None and cancellation_destination_warehouse is None:
        cancellation_destination_warehouse = (
            movement.resolved_destination_warehouse or movement.resolved_source_warehouse
        )
        cancellation_destination = movement.destination_location or movement.source_location
    return (
        cancellation_source_warehouse,
        cancellation_source,
        cancellation_destination_warehouse,
        cancellation_destination,
    )


def _create_cancellation_movement(*, movement, deltas, cancelled_by, reason):
    (
        cancellation_source_warehouse,
        cancellation_source,
        cancellation_destination_warehouse,
        cancellation_destination,
    ) = _cancellation_locations(deltas, movement)
    return StockMovement.objects.create(
        movement_type=StockMovement.MovementType.ADJUSTMENT,
        item=movement.item,
        qty=movement.qty,
        source_warehouse=cancellation_source_warehouse,
        destination_warehouse=cancellation_destination_warehouse,
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


def cancel_stock_movement(*, movement, cancelled_by, reason, request=None):
    stock_service = _stock_service()

    reason = (reason or "").strip()
    if not reason:
        raise stock_service.StockServiceError(_("Причина анулювання обов'язкова."))
    if not can_cancel_stock_movement(cancelled_by, movement):
        raise stock_service.StockServiceError(_("Неможливо анулювати рух"))

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
            raise stock_service.StockServiceError(
                _("Неможливо анулювати рух: рух уже анульовано.")
            )
        if movement.reversal_of_id:
            raise stock_service.StockServiceError(
                _("Неможливо анулювати рух анулювання.")
            )

        deltas = _cancellation_deltas(movement)
        if not deltas:
            raise stock_service.StockServiceError(_("Неможливо анулювати рух"))

        # Apply balance changes with row-level locks before creating the audit/history rows.
        for warehouse, location, qty_delta in deltas:
            _apply_cancellation_delta(
                item=movement.item, warehouse=warehouse, location=location, qty_delta=qty_delta
            )

        cancellation_movement = _create_cancellation_movement(
            movement=movement,
            deltas=deltas,
            cancelled_by=cancelled_by,
            reason=reason,
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
        if movement.purchase_request_id:
            from core.models import PurchaseRequest  # noqa: PLC0415
            from core.services.purchase_requests import (  # noqa: PLC0415
                restore_purchase_request_if_receiving_reopened,
                sync_purchase_request_receiving_status,
            )

            purchase_request = PurchaseRequest.objects.select_for_update().get(
                pk=movement.purchase_request_id
            )
            sync_purchase_request_receiving_status(purchase_request)
            restore_purchase_request_if_receiving_reopened(purchase_request)

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
