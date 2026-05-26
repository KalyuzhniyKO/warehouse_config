from datetime import timedelta
from decimal import Decimal
from io import BytesIO

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import Item, Location, Recipient, StockBalance, StockMovement

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
    qs = StockMovement.objects.select_related("item", "source_location", "source_location__warehouse", "destination_location", "destination_location__warehouse", "recipient")
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

# keep existing funcs...

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
    return list(filter_movements(filters).filter(movement_type__in=ISSUE_TYPES).values("item__id", "item__name", "item__internal_code", "item__barcode__barcode").annotate(total_qty=Sum("qty"), operations=Count("id")).order_by("-total_qty", "item__name")[:10])


def get_top_usage_places(filters):
    return list(filter_movements(filters).filter(movement_type__in=ISSUE_TYPES).values("department").annotate(total_qty=Sum("qty"), operations=Count("id")).order_by("-total_qty", "department")[:10])


def get_top_recipients(filters):
    return list(filter_movements(filters).filter(recipient__isnull=False).values("recipient__id", "recipient__name").annotate(total_qty=Sum("qty"), operations=Count("id")).order_by("-total_qty", "recipient__name")[:10])


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




def _limited_examples(qs, limit=10):
    return list(qs.select_related("item", "recipient", "source_location", "destination_location").order_by("-occurred_at", "-id")[:limit])


def get_missing_document_movements(filters):
    return filter_movements(filters).filter(Q(document_number__isnull=True) | Q(document_number=""))


def get_movements_missing_required_fields(filters):
    issue = filter_movements(filters).filter(movement_type__in=ISSUE_TYPES)
    return {
        "issue_without_recipient": issue.filter(recipient__isnull=True),
        "issue_without_usage_place": issue.filter(Q(department__isnull=True) | Q(department="")),
        "movement_without_item": filter_movements(filters).filter(item__isnull=True),
        "non_positive_qty": filter_movements(filters).filter(qty__lte=0),
        "receive_without_destination": filter_movements(filters).filter(movement_type__in=IN_TYPES, destination_location__isnull=True),
    }


def get_suspicious_movements(filters):
    data = get_movements_missing_required_fields(filters)
    combined = filter_movements(filters).none()
    for qs in data.values():
        combined = combined | qs
    return combined.distinct()


def get_stock_reconciliation_warnings(filters):
    balances = filter_balances(filters)
    negative_balances = list(balances.filter(qty__lt=0).select_related("item", "location")[:20])
    zero_active = list(balances.filter(qty=0, item__is_active=True).select_related("item", "location")[:20])
    movement_item_ids = filter_movements(filters).values_list("item_id", flat=True).distinct()
    stock_without_movement = list(balances.filter(qty__gt=0).exclude(item_id__in=movement_item_ids).select_related("item", "location")[:20])
    items_with_movement_no_balance = list(
        Item.objects.filter(stock_movements__in=filter_movements(filters)).exclude(stock_balances__in=balances).distinct()[:20]
    )
    return {
        "negative_balances": negative_balances,
        "zero_active_balances": zero_active,
        "stock_without_movement": stock_without_movement,
        "movement_without_balance": items_with_movement_no_balance,
    }


def get_reconciliation_summary(filters):
    movements = filter_movements(filters)
    total_movements = movements.count()
    daily_count = sum(row.get("operations", 0) for row in get_daily_movement(filters))
    missing_docs = get_missing_document_movements(filters).count()
    incomplete = get_suspicious_movements(filters).count()
    stock_warnings = get_stock_reconciliation_warnings(filters)
    negative_stock = len(stock_warnings["negative_balances"])
    suspicious_stock = len(stock_warnings["zero_active_balances"]) + len(stock_warnings["stock_without_movement"]) + len(stock_warnings["movement_without_balance"])
    diff = total_movements - daily_count
    issues = []
    if diff:
        issues.append(_("Розбіжність між журналом та денним графіком"))
    if missing_docs:
        issues.append(_("Є рухи без документа"))
    if incomplete:
        issues.append(_("Є рухи з неповними даними"))
    if negative_stock:
        issues.append(_("Виявлено негативні залишки"))
    if suspicious_stock:
        issues.append(_("Є підозрілі залишки"))
    return {
        "total_movements": total_movements,
        "daily_chart_operations": daily_count,
        "difference": diff,
        "incomplete_movements": incomplete,
        "missing_documents": missing_docs,
        "negative_stock": negative_stock,
        "suspicious_stock": suspicious_stock,
        "is_consistent": not issues,
        "issues": issues,
    }


def get_analytics_data_quality(filters):
    missing_docs_qs = get_missing_document_movements(filters)
    missing_fields = get_movements_missing_required_fields(filters)
    stock = get_stock_reconciliation_warnings(filters)
    reconciliation = get_reconciliation_summary(filters)
    checks = {
        "missing_documents": {"count": missing_docs_qs.count(), "examples": _limited_examples(missing_docs_qs)},
        "issue_without_recipient": {"count": missing_fields["issue_without_recipient"].count(), "examples": _limited_examples(missing_fields["issue_without_recipient"])},
        "issue_without_usage_place": {"count": missing_fields["issue_without_usage_place"].count(), "examples": _limited_examples(missing_fields["issue_without_usage_place"])},
        "movement_without_item": {"count": missing_fields["movement_without_item"].count(), "examples": _limited_examples(missing_fields["movement_without_item"])},
        "non_positive_qty": {"count": missing_fields["non_positive_qty"].count(), "examples": _limited_examples(missing_fields["non_positive_qty"])},
        "receive_without_destination": {"count": missing_fields["receive_without_destination"].count(), "examples": _limited_examples(missing_fields["receive_without_destination"])},
    }
    warning_total = sum(v["count"] for v in checks.values()) + reconciliation["negative_stock"] + reconciliation["suspicious_stock"]
    score = max(0, 100 - warning_total * 5)
    return {
        "checks": checks,
        "stock": stock,
        "reconciliation": reconciliation,
        "warning_total": warning_total,
        "score": score,
        "status": "ok" if warning_total == 0 else "warning",
    }
def get_stock_by_location_for_item(item):
    return list(StockBalance.objects.filter(item=item, qty__gt=0).select_related('location', 'location__warehouse').values('location__warehouse__name', 'location__name').annotate(total_qty=Sum('qty')).order_by('location__warehouse__name', 'location__name'))


def get_item_analytics(item, filters):
    mv = filter_movements(filters).filter(item=item)
    return {
        'summary': mv.aggregate(operations=Count('id'), receive_qty=Sum('qty', filter=Q(movement_type__in=IN_TYPES)), issue_qty=Sum('qty', filter=Q(movement_type__in=ISSUE_TYPES)), return_qty=Sum('qty', filter=Q(movement_type__in=RETURN_TYPES)), writeoff_qty=Sum('qty', filter=Q(movement_type__in=WRITEOFF_TYPES))),
        'recent_movements': mv.order_by('-occurred_at', '-id')[:20],
        'top_usage_places': list(mv.filter(movement_type__in=ISSUE_TYPES).values('department').annotate(total_qty=Sum('qty'), operations=Count('id')).order_by('-total_qty')[:10]),
        'top_recipients': list(mv.filter(movement_type__in=ISSUE_TYPES, recipient__isnull=False).values('recipient__id', 'recipient__name').annotate(total_qty=Sum('qty'), operations=Count('id')).order_by('-total_qty')[:10]),
        'stock_by_location': get_stock_by_location_for_item(item),
    }


def get_usage_place_analytics(usage_place, filters):
    mv = filter_movements(filters).filter(department=usage_place)
    return {
        'summary': mv.aggregate(operations=Count('id'), total_qty=Sum('qty')),
        'top_items': list(mv.values('item__id', 'item__name', 'item__internal_code').annotate(total_qty=Sum('qty'), operations=Count('id')).order_by('-total_qty')[:10]),
        'top_recipients': list(mv.filter(recipient__isnull=False).values('recipient__id', 'recipient__name').annotate(total_qty=Sum('qty'), operations=Count('id')).order_by('-total_qty')[:10]),
        'recent_movements': mv.order_by('-occurred_at', '-id')[:20],
    }


def get_recipient_analytics(recipient, filters):
    mv = filter_movements(filters).filter(recipient=recipient)
    return {
        'summary': mv.aggregate(operations=Count('id'), total_qty=Sum('qty')),
        'top_items': list(mv.values('item__id', 'item__name', 'item__internal_code').annotate(total_qty=Sum('qty'), operations=Count('id')).order_by('-total_qty')[:10]),
        'recent_movements': mv.order_by('-occurred_at', '-id')[:20],
    }
