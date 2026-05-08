from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate

from core.models import Category, Item, Location, Recipient, StockBalance, StockMovement, Warehouse

IN_TYPES = {StockMovement.MovementType.IN, StockMovement.MovementType.INITIAL_BALANCE, StockMovement.MovementType.RETURN}
OUT_TYPES = {StockMovement.MovementType.OUT}
WRITEOFF_TYPES = {StockMovement.MovementType.WRITEOFF}
TRANSFER_TYPES = {StockMovement.MovementType.TRANSFER}


def decimal_zero(value):
    return value or Decimal("0.000")


def filter_movements(filters):
    queryset = StockMovement.objects.select_related(
        "item",
        "item__category",
        "source_location",
        "source_location__warehouse",
        "destination_location",
        "destination_location__warehouse",
        "recipient",
    )
    if filters.get("date_from"):
        queryset = queryset.filter(occurred_at__date__gte=filters["date_from"])
    if filters.get("date_to"):
        queryset = queryset.filter(occurred_at__date__lte=filters["date_to"])
    if filters.get("warehouse"):
        warehouse = filters["warehouse"]
        queryset = queryset.filter(Q(source_location__warehouse=warehouse) | Q(destination_location__warehouse=warehouse))
    if filters.get("location"):
        location = filters["location"]
        queryset = queryset.filter(Q(source_location=location) | Q(destination_location=location))
    if filters.get("category"):
        queryset = queryset.filter(item__category=filters["category"])
    if filters.get("item"):
        queryset = queryset.filter(item=filters["item"])
    if filters.get("movement_type"):
        queryset = queryset.filter(movement_type=filters["movement_type"])
    if filters.get("recipient"):
        queryset = queryset.filter(recipient=filters["recipient"])
    if filters.get("q"):
        query = filters["q"]
        queryset = queryset.filter(
            Q(item__name__icontains=query)
            | Q(item__internal_code__icontains=query)
            | Q(item__barcode__barcode__icontains=query)
        )
    return queryset


def filter_balances(filters):
    queryset = StockBalance.objects.select_related("item", "item__category", "location", "location__warehouse")
    if filters.get("warehouse"):
        queryset = queryset.filter(location__warehouse=filters["warehouse"])
    if filters.get("location"):
        queryset = queryset.filter(location=filters["location"])
    if filters.get("category"):
        queryset = queryset.filter(item__category=filters["category"])
    if filters.get("item"):
        queryset = queryset.filter(item=filters["item"])
    if filters.get("q"):
        query = filters["q"]
        queryset = queryset.filter(
            Q(item__name__icontains=query)
            | Q(item__internal_code__icontains=query)
            | Q(item__barcode__barcode__icontains=query)
        )
    return queryset


def get_movement_summary(filters):
    movements = filter_movements(filters)
    aggregate = movements.aggregate(
        total_in=Sum("qty", filter=Q(movement_type__in=IN_TYPES)),
        total_out=Sum("qty", filter=Q(movement_type__in=OUT_TYPES)),
        total_writeoff=Sum("qty", filter=Q(movement_type__in=WRITEOFF_TYPES)),
        total_returns=Sum("qty", filter=Q(movement_type=StockMovement.MovementType.RETURN)),
        total_transfers=Sum("qty", filter=Q(movement_type__in=TRANSFER_TYPES)),
        unique_items=Count("item", distinct=True),
    )
    return {key: decimal_zero(value) if key.startswith("total_") else value for key, value in aggregate.items()}


def get_top_items_by_out(filters):
    return list(
        filter_movements(filters)
        .filter(movement_type=StockMovement.MovementType.OUT)
        .values("item__name", "item__internal_code")
        .annotate(total_qty=Sum("qty"))
        .order_by("-total_qty", "item__name")[:10]
    )


def get_top_items_by_in(filters):
    return list(
        filter_movements(filters)
        .filter(movement_type__in=IN_TYPES)
        .values("item__name", "item__internal_code")
        .annotate(total_qty=Sum("qty"))
        .order_by("-total_qty", "item__name")[:10]
    )


def get_top_recipients(filters):
    return list(
        filter_movements(filters)
        .filter(recipient__isnull=False)
        .values("recipient__name")
        .annotate(total_qty=Sum("qty"), movements_count=Count("id"))
        .order_by("-total_qty", "recipient__name")[:10]
    )


def get_stock_summary(filters):
    balances = filter_balances(filters)
    return {
        "positive_positions": balances.filter(qty__gt=0).count(),
        "zero_positions": balances.filter(qty=0).count(),
        "negative_positions": balances.filter(qty__lt=0).count(),
        "by_warehouse": list(
            balances.values("location__warehouse__name")
            .annotate(total_qty=Sum("qty"), positions=Count("id"))
            .order_by("location__warehouse__name")
        ),
    }


def get_movements_by_day(filters):
    return list(
        filter_movements(filters)
        .annotate(day=TruncDate("occurred_at"))
        .values("day")
        .annotate(
            in_qty=Sum("qty", filter=Q(movement_type__in=IN_TYPES)),
            out_qty=Sum("qty", filter=Q(movement_type=StockMovement.MovementType.OUT)),
            writeoff_qty=Sum("qty", filter=Q(movement_type=StockMovement.MovementType.WRITEOFF)),
        )
        .order_by("day")
    )


def get_movements_by_type(filters):
    return list(
        filter_movements(filters)
        .values("movement_type")
        .annotate(total_qty=Sum("qty"), movements_count=Count("id"))
        .order_by("movement_type")
    )
