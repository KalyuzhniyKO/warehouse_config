from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import Item, Location, Recipient, StockBalance, StockMovement, Warehouse

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
    elif period == "custom":
        date_from = params.get("date_from") or None
        date_to = params.get("date_to") or None
    return {"period": period, "date_from": date_from, "date_to": date_to}


def filter_movements(filters):
    qs = StockMovement.objects.select_related("item", "source_location", "destination_location", "recipient")
    if filters.get("date_from"):
        qs = qs.filter(occurred_at__date__gte=filters["date_from"])
    if filters.get("date_to"):
        qs = qs.filter(occurred_at__date__lte=filters["date_to"])
    if filters.get("warehouse"):
        qs = qs.filter(Q(source_location__warehouse=filters["warehouse"]) | Q(destination_location__warehouse=filters["warehouse"]))
    if filters.get("location"):
        qs = qs.filter(Q(source_location=filters["location"]) | Q(destination_location=filters["location"]))
    if filters.get("movement_type"):
        qs = qs.filter(movement_type=filters["movement_type"])
    return qs


def filter_balances(filters):
    qs = StockBalance.objects.select_related("item", "location", "location__warehouse")
    if filters.get("warehouse"):
        qs = qs.filter(location__warehouse=filters["warehouse"])
    if filters.get("location"):
        qs = qs.filter(location=filters["location"])
    return qs


def get_analytics_summary(filters):
    mv = filter_movements(filters)
    agg = mv.aggregate(
        operations_count=Count("id"),
        receive_qty=Sum("qty", filter=Q(movement_type__in=IN_TYPES)),
        issue_qty=Sum("qty", filter=Q(movement_type__in=ISSUE_TYPES)),
        return_qty=Sum("qty", filter=Q(movement_type__in=RETURN_TYPES)),
        writeoff_qty=Sum("qty", filter=Q(movement_type__in=WRITEOFF_TYPES)),
    )
    balances = filter_balances(filters)
    return {
        "total_items": Item.objects.count(),
        "active_items": Item.objects.filter(is_active=True).count(),
        "positions_with_stock": balances.filter(qty__gt=0).count(),
        "zero_stock_items": balances.filter(qty=0).values("item_id").distinct().count(),
        "operations_count": agg["operations_count"] or 0,
        "receive_qty": decimal_zero(agg["receive_qty"]),
        "issue_qty": decimal_zero(agg["issue_qty"]),
        "return_qty": decimal_zero(agg["return_qty"]),
        "writeoff_qty": decimal_zero(agg["writeoff_qty"]),
        "low_stock_configured": False,
    }


def get_daily_movement(filters):
    return list(filter_movements(filters).annotate(day=TruncDate("occurred_at")).values("day").annotate(
        operations=Count("id"),
        receive_qty=Sum("qty", filter=Q(movement_type__in=IN_TYPES)),
        issue_qty=Sum("qty", filter=Q(movement_type__in=ISSUE_TYPES)),
        return_qty=Sum("qty", filter=Q(movement_type__in=RETURN_TYPES)),
        writeoff_qty=Sum("qty", filter=Q(movement_type__in=WRITEOFF_TYPES)),
    ).order_by("day"))


def get_top_issued_items(filters):
    return list(filter_movements(filters).filter(movement_type__in=ISSUE_TYPES).values("item__name", "item__internal_code", "item__barcode__barcode").annotate(total_qty=Sum("qty"), operations=Count("id")).order_by("-total_qty", "item__name")[:10])


def get_top_usage_places(filters):
    return list(filter_movements(filters).filter(movement_type__in=ISSUE_TYPES).values("department").annotate(total_qty=Sum("qty"), operations=Count("id")).order_by("-total_qty", "department")[:10])


def get_top_recipients(filters):
    return list(filter_movements(filters).filter(recipient__isnull=False).values("recipient__name").annotate(total_qty=Sum("qty"), operations=Count("id")).order_by("-total_qty", "recipient__name")[:10])


def get_inactive_stock_items(filters):
    movement_item_ids = filter_movements(filters).values_list("item_id", flat=True).distinct()
    return list(filter_balances(filters).filter(qty__gt=0).exclude(item_id__in=movement_item_ids).values("item__name", "item__internal_code", "qty").order_by("item__name")[:20])


def get_recent_movements(filters):
    return filter_movements(filters).select_related("item", "recipient").order_by("-occurred_at", "-id")[:10]


def get_previous_period(filters):
    date_from = filters.get("date_from")
    date_to = filters.get("date_to")
    if not date_from or not date_to:
        return {"date_from": None, "date_to": None}
    span_days = (date_to - date_from).days + 1
    prev_to = date_from - timedelta(days=1)
    prev_from = prev_to - timedelta(days=span_days - 1)
    previous_filters = dict(filters)
    previous_filters["date_from"] = prev_from
    previous_filters["date_to"] = prev_to
    return previous_filters


def get_kpi_delta(current_value, previous_value):
    current = current_value or 0
    previous = previous_value or 0
    if previous == 0:
        if current == 0:
            return {"trend": "neutral", "label": _("без змін"), "percent": None}
        return {"trend": "positive", "label": _("нові дані"), "percent": None}
    delta_percent = ((current - previous) / previous) * 100
    if delta_percent > 0:
        return {"trend": "positive", "label": f"+{delta_percent:.0f}%", "percent": delta_percent}
    if delta_percent < 0:
        return {"trend": "negative", "label": f"{delta_percent:.0f}%", "percent": delta_percent}
    return {"trend": "neutral", "label": _("без змін"), "percent": 0}


def get_operation_mix(filters):
    rows = filter_movements(filters).values("movement_type").annotate(total=Count("id"))
    data = {k: 0 for k in ["receive", "issue", "return", "write_off", "transfer", "inventory"]}
    mapping = {
        StockMovement.MovementType.IN: "receive",
        StockMovement.MovementType.INITIAL_BALANCE: "receive",
        StockMovement.MovementType.OUT: "issue",
        StockMovement.MovementType.RETURN: "return",
        StockMovement.MovementType.WRITEOFF: "write_off",
        StockMovement.MovementType.TRANSFER: "transfer",
        StockMovement.MovementType.ADJUSTMENT: "inventory",
    }
    for row in rows:
        key = mapping.get(row["movement_type"])
        if key:
            data[key] += row["total"]
    total = sum(data.values())
    return [{"key": k, "total": v, "percent": (v/total*100) if total else 0} for k,v in data.items()]
