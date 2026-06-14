from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.utils.translation import gettext_lazy as _

from core.models import StockBalance, StockMovement

from .filters import (
    IN_TYPES,
    ISSUE_TYPES,
    RETURN_TYPES,
    WRITEOFF_TYPES,
    decimal_zero,
    filter_balances,
    filter_items,
    filter_movements,
)


def get_movement_summary(filters):
    normalized_filters = dict(filters)
    if normalized_filters.get("date_from") or normalized_filters.get("date_to"):
        normalized_filters.setdefault("period", "custom")
    movements = filter_movements(normalized_filters)
    totals = movements.aggregate(
        total_in=Sum("qty", filter=Q(movement_type__in=IN_TYPES)),
        total_out=Sum("qty", filter=Q(movement_type__in=ISSUE_TYPES)),
    )
    return {
        "total_in": decimal_zero(totals["total_in"]),
        "total_out": decimal_zero(totals["total_out"]),
    }


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
    items = filter_items(filters)
    return {
        "total_items": items.count(),
        "active_items": items.filter(is_active=True).count(),
        "positions_with_stock": balances.filter(qty__gt=0).count(),
        "zero_stock_items": balances.filter(qty=0).values("item_id").distinct().count(),
        "no_movement_count": get_no_movement_count(filters),
        "operations_count": agg["operations_count"] or 0,
        "receive_qty": decimal_zero(agg["receive_qty"]),
        "issue_qty": decimal_zero(agg["issue_qty"]),
        "return_qty": decimal_zero(agg["return_qty"]),
        "writeoff_qty": decimal_zero(agg["writeoff_qty"]),
        "low_stock_configured": False,
    }


def get_daily_movement(filters):
    return list(
        filter_movements(filters)
        .annotate(day=TruncDate("occurred_at"))
        .values("day")
        .annotate(
            operations=Count("id"),
            receive_qty=Sum("qty", filter=Q(movement_type__in=IN_TYPES)),
            issue_qty=Sum("qty", filter=Q(movement_type__in=ISSUE_TYPES)),
            return_qty=Sum("qty", filter=Q(movement_type__in=RETURN_TYPES)),
            writeoff_qty=Sum("qty", filter=Q(movement_type__in=WRITEOFF_TYPES)),
        )
        .order_by("day")
    )


def get_top_issued_items(filters):
    return list(
        filter_movements(filters)
        .filter(movement_type__in=ISSUE_TYPES)
        .values("item__id", "item__name", "item__internal_code", "item__barcode__barcode")
        .annotate(total_qty=Sum("qty"), operations=Count("id"))
        .order_by("-total_qty", "item__name")[:10]
    )


def get_top_usage_places(filters):
    return list(
        filter_movements(filters)
        .filter(movement_type__in=ISSUE_TYPES)
        .values("department")
        .annotate(total_qty=Sum("qty"), operations=Count("id"))
        .order_by("-total_qty", "department")[:10]
    )


def get_top_recipients(filters):
    return list(
        filter_movements(filters)
        .filter(recipient__isnull=False)
        .values("recipient__id", "recipient__name")
        .annotate(total_qty=Sum("qty"), operations=Count("id"))
        .order_by("-total_qty", "recipient__name")[:10]
    )


def get_inactive_stock_items(filters):
    movement_item_ids = _any_movement_item_ids(filters)
    return list(
        filter_balances(filters)
        .filter(qty__gt=0)
        .exclude(item_id__in=movement_item_ids)
        .values("item__name", "item__internal_code", "qty")
        .order_by("item__name")[:20]
    )


def get_no_movement_count(filters):
    movement_item_ids = _any_movement_item_ids(filters)
    return (
        filter_balances(filters)
        .filter(qty__gt=0)
        .exclude(item_id__in=movement_item_ids)
        .values("item_id")
        .distinct()
        .count()
    )


def _any_movement_item_ids(filters):
    movement_filters = dict(filters)
    # "No movement" means no movement of any type within the remaining scope.
    movement_filters.pop("movement_type", None)
    return filter_movements(movement_filters).values_list("item_id", flat=True).distinct()


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
    return [{"key": k, "total": v, "percent": (v / total * 100) if total else 0} for k, v in data.items()]


def get_stock_by_location_for_item(item):
    return list(
        StockBalance.objects.filter(item=item, qty__gt=0)
        .select_related("warehouse", "location")
        .values("warehouse__name", "location__name")
        .annotate(total_qty=Sum("qty"))
        .order_by("warehouse__name", "location__name")
    )


def get_item_analytics(item, filters):
    mv = filter_movements(filters).filter(item=item)
    return {
        "summary": mv.aggregate(
            operations=Count("id"),
            receive_qty=Sum("qty", filter=Q(movement_type__in=IN_TYPES)),
            issue_qty=Sum("qty", filter=Q(movement_type__in=ISSUE_TYPES)),
            return_qty=Sum("qty", filter=Q(movement_type__in=RETURN_TYPES)),
            writeoff_qty=Sum("qty", filter=Q(movement_type__in=WRITEOFF_TYPES)),
        ),
        "recent_movements": mv.order_by("-occurred_at", "-id")[:20],
        "top_usage_places": list(
            mv.filter(movement_type__in=ISSUE_TYPES)
            .values("department")
            .annotate(total_qty=Sum("qty"), operations=Count("id"))
            .order_by("-total_qty")[:10]
        ),
        "top_recipients": list(
            mv.filter(movement_type__in=ISSUE_TYPES, recipient__isnull=False)
            .values("recipient__id", "recipient__name")
            .annotate(total_qty=Sum("qty"), operations=Count("id"))
            .order_by("-total_qty")[:10]
        ),
        "stock_by_location": get_stock_by_location_for_item(item),
    }


def get_usage_place_analytics(usage_place, filters):
    mv = filter_movements(filters).filter(department=usage_place)
    return {
        "summary": mv.aggregate(operations=Count("id"), total_qty=Sum("qty")),
        "top_items": list(
            mv.values("item__id", "item__name", "item__internal_code")
            .annotate(total_qty=Sum("qty"), operations=Count("id"))
            .order_by("-total_qty")[:10]
        ),
        "top_recipients": list(
            mv.filter(recipient__isnull=False)
            .values("recipient__id", "recipient__name")
            .annotate(total_qty=Sum("qty"), operations=Count("id"))
            .order_by("-total_qty")[:10]
        ),
        "recent_movements": mv.order_by("-occurred_at", "-id")[:20],
    }


def get_recipient_analytics(recipient, filters):
    mv = filter_movements(filters).filter(recipient=recipient)
    return {
        "summary": mv.aggregate(operations=Count("id"), total_qty=Sum("qty")),
        "top_items": list(
            mv.values("item__id", "item__name", "item__internal_code")
            .annotate(total_qty=Sum("qty"), operations=Count("id"))
            .order_by("-total_qty")[:10]
        ),
        "recent_movements": mv.order_by("-occurred_at", "-id")[:20],
    }
