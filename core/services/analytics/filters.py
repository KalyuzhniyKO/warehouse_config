from datetime import timedelta
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from core.models import Item, StockBalance, StockMovement

IN_TYPES = {StockMovement.MovementType.IN, StockMovement.MovementType.INITIAL_BALANCE}
ISSUE_TYPES = {StockMovement.MovementType.OUT}
RETURN_TYPES = {StockMovement.MovementType.RETURN}
WRITEOFF_TYPES = {StockMovement.MovementType.WRITEOFF}


def decimal_zero(v):
    return v or Decimal("0.000")


def get_analytics_filters(params):
    today = timezone.localdate()
    period = params.get("period") or "30d"
    date_from = None
    date_to = None
    if period == "today":
        date_from = date_to = today
    elif period == "7d":
        date_from, date_to = today - timedelta(days=6), today
    elif period == "30d":
        date_from, date_to = today - timedelta(days=29), today
    elif period == "month":
        date_from, date_to = today.replace(day=1), today
    elif period == "prev_month":
        first_day = today.replace(day=1)
        date_to = first_day - timedelta(days=1)
        date_from = date_to.replace(day=1)
    elif period == "custom":
        date_from = params.get("date_from") or None
        date_to = params.get("date_to") or None
    return {"period": period, "date_from": date_from, "date_to": date_to}


def build_analytics_filter_query(filters):
    data = {}
    for k in ["date_from", "date_to", "warehouse", "location", "movement_type"]:
        val = filters.get(k)
        if not val:
            continue
        data[k] = str(getattr(val, "pk", val))
    return data


def filter_movements(filters):
    qs = StockMovement.objects.select_related(
        "item",
        "source_location",
        "source_warehouse",
                "source_location__warehouse",
        "destination_location",
        "destination_warehouse",
                "destination_location__warehouse",
        "recipient",
    ).filter(is_cancelled=False, reversal_of__isnull=True)
    accessible_warehouses = filters.get("accessible_warehouses")
    if accessible_warehouses is not None:
        qs = qs.filter(
            Q(source_warehouse__in=accessible_warehouses)
            | Q(destination_warehouse__in=accessible_warehouses)
            | Q(source_location__warehouse__in=accessible_warehouses)
            | Q(destination_location__warehouse__in=accessible_warehouses)
        )
    if filters.get("date_from"):
        qs = qs.filter(occurred_at__date__gte=filters["date_from"])
    if filters.get("date_to"):
        qs = qs.filter(occurred_at__date__lte=filters["date_to"])
    if filters.get("warehouse"):
        qs = qs.filter(
            Q(source_warehouse=filters["warehouse"])
            | Q(destination_warehouse=filters["warehouse"])
            | Q(source_location__warehouse=filters["warehouse"])
            | Q(destination_location__warehouse=filters["warehouse"])
        )
    if filters.get("location"):
        qs = qs.filter(
            Q(source_location=filters["location"])
            | Q(destination_location=filters["location"])
        )
    if filters.get("movement_type"):
        qs = qs.filter(movement_type=filters["movement_type"])
    return qs


def filter_balances(filters):
    qs = StockBalance.objects.select_related("item", "warehouse", "location")
    accessible_warehouses = filters.get("accessible_warehouses")
    if accessible_warehouses is not None:
        qs = qs.filter(warehouse__in=accessible_warehouses)
    if filters.get("warehouse"):
        qs = qs.filter(warehouse=filters["warehouse"])
    if filters.get("location"):
        qs = qs.filter(location=filters["location"])
    return qs


def filter_items(filters):
    balance_item_ids = filter_balances(filters).values("item_id")
    movement_item_ids = filter_movements(filters).values("item_id")
    return Item.objects.filter(
        Q(id__in=balance_item_ids) | Q(id__in=movement_item_ids)
    ).distinct()
