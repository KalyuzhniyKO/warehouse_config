from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.db.models.functions import Lower, Trim
from django.utils.translation import gettext_lazy as _

from core.models import Item, PurchaseRequest, StockMovement, Unit
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
PURCHASE_REQUEST_ITEM_NAME_REQUIRED_ERROR = _(
    "У заявці на закупівлю не вказано назву товару."
)


def purchase_requests_available_for_receiving(user):
    queryset = PurchaseRequest.objects.filter(
        status__in=RECEIVABLE_PURCHASE_REQUEST_STATUSES,
        approval_status=PurchaseRequest.ApprovalStatus.APPROVED,
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


def normalize_purchase_request_item_name(value):
    return " ".join((value or "").strip().split()).casefold()


def resolve_purchase_request_unit(purchase_request):
    unit_name = (purchase_request.unit or "").strip()
    if not unit_name:
        unit_name = str(_("шт"))
    normalized_unit_name = unit_name.casefold()
    existing_unit = (
        Unit.objects.filter(is_active=True)
        .annotate(
            normalized_symbol=Lower(Trim("symbol")),
            normalized_name=Lower(Trim("name")),
        )
        .filter(normalized_symbol=normalized_unit_name)
        .first()
    )
    if existing_unit is not None:
        return existing_unit
    existing_unit = (
        Unit.objects.filter(is_active=True)
        .annotate(normalized_name=Lower(Trim("name")))
        .filter(normalized_name=normalized_unit_name)
        .first()
    )
    if existing_unit is not None:
        return existing_unit
    return Unit.objects.create(name=unit_name, symbol=unit_name)


def find_item_for_purchase_request(purchase_request):
    if purchase_request.item_id:
        return purchase_request.item
    normalized_name = normalize_purchase_request_item_name(purchase_request.title)
    if not normalized_name:
        return None
    for item in (
        Item.objects.filter(is_active=True).select_related("unit").order_by("pk")
    ):
        if normalize_purchase_request_item_name(item.name) == normalized_name:
            return item
    return None


def resolve_or_create_item_for_purchase_request(purchase_request):
    item_name = " ".join((purchase_request.title or "").strip().split())
    normalized_name = normalize_purchase_request_item_name(item_name)
    if not normalized_name:
        raise ValueError(PURCHASE_REQUEST_ITEM_NAME_REQUIRED_ERROR)

    if purchase_request.item_id:
        return purchase_request.item, False

    with transaction.atomic():
        item = find_item_for_purchase_request(purchase_request)
        if item is not None:
            PurchaseRequest.objects.filter(
                pk=purchase_request.pk, item__isnull=True
            ).update(item=item)
            purchase_request.item = item
            return item, False

        unit = resolve_purchase_request_unit(purchase_request)
        item = Item(name=item_name, unit=unit)
        item.save(generate_barcode=False)
        PurchaseRequest.objects.filter(pk=purchase_request.pk).update(item=item)
        purchase_request.item = item
        return item, True


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
