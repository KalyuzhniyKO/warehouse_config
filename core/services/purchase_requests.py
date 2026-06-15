from decimal import Decimal

from django.db.models import Sum
from django.utils.translation import gettext_lazy as _

from core.models import PurchaseRequest, StockMovement
from core.permissions import STOCK_EDIT_GROUPS, can_manage_purchase_requests, user_in_groups


RECEIVABLE_PURCHASE_REQUEST_STATUSES = {
    PurchaseRequest.Status.APPROVED,
    PurchaseRequest.Status.ORDERED,
    PurchaseRequest.Status.PARTIALLY_RECEIVED,
}

PURCHASE_REQUEST_NOT_RECEIVABLE_ERROR = _(
    "Вибрана заявка на закупівлю недоступна для оприбуткування."
)
PURCHASE_REQUEST_QTY_EXCEEDED_ERROR = _(
    "Кількість перевищує залишок за заявкою на закупівлю."
)


def purchase_requests_available_for_receiving(user):
    queryset = PurchaseRequest.objects.filter(
        status__in=RECEIVABLE_PURCHASE_REQUEST_STATUSES
    ).select_related("requested_by")
    if can_manage_purchase_requests(user):
        return queryset
    return queryset.filter(requested_by=user)


def can_receive_against_purchase_request(user, purchase_request):
    if not user_in_groups(user, STOCK_EDIT_GROUPS):
        return False
    return purchase_requests_available_for_receiving(user).filter(
        pk=purchase_request.pk
    ).exists()


def get_received_purchase_request_qty(purchase_request):
    return purchase_request.linked_receive_movements.filter(
        movement_type=StockMovement.MovementType.IN,
        is_cancelled=False,
        reversal_of__isnull=True,
    ).aggregate(total=Sum("qty"))["total"] or Decimal("0")


def sync_purchase_request_receiving_status(purchase_request):
    received_qty = get_received_purchase_request_qty(purchase_request)
    if purchase_request.status == PurchaseRequest.Status.CANCELLED:
        return received_qty
    update_fields = []
    # Preserve the business state to restore if all linked receipts are cancelled.
    if (
        not purchase_request.receiving_base_status
        and purchase_request.status
        in {PurchaseRequest.Status.APPROVED, PurchaseRequest.Status.ORDERED}
    ):
        purchase_request.receiving_base_status = purchase_request.status
        update_fields.append("receiving_base_status")
    if received_qty >= purchase_request.requested_qty:
        status = PurchaseRequest.Status.RECEIVED
    elif received_qty > 0:
        status = PurchaseRequest.Status.PARTIALLY_RECEIVED
    else:
        status = (
            purchase_request.receiving_base_status or PurchaseRequest.Status.APPROVED
        )
    if purchase_request.status != status:
        purchase_request.status = status
        update_fields.append("status")
    if update_fields:
        purchase_request.save(update_fields=[*update_fields, "updated_at"])
    return received_qty
