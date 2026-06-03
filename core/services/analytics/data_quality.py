from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from core.models import Item

from .filters import IN_TYPES, ISSUE_TYPES, filter_balances, filter_movements
from .summaries import get_daily_movement


def _limited_examples(qs, limit=10):
    return list(
        qs.select_related("item", "recipient", "source_location", "destination_location")
        .order_by("-occurred_at", "-id")[:limit]
    )


def get_missing_document_movements(filters):
    return filter_movements(filters).filter(Q(document_number__isnull=True) | Q(document_number=""))


def get_movements_missing_required_fields(filters):
    issue = filter_movements(filters).filter(movement_type__in=ISSUE_TYPES)
    return {
        "issue_without_recipient": issue.filter(recipient__isnull=True),
        "issue_without_usage_place": issue.filter(Q(department__isnull=True) | Q(department="")),
        "movement_without_item": filter_movements(filters).filter(item__isnull=True),
        "non_positive_qty": filter_movements(filters).filter(qty__lte=0),
        "receive_without_destination": filter_movements(filters).filter(
            movement_type__in=IN_TYPES, destination_warehouse__isnull=True
        ),
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
    stock_without_movement = list(
        balances.filter(qty__gt=0)
        .exclude(item_id__in=movement_item_ids)
        .select_related("item", "location")[:20]
    )
    items_with_movement_no_balance = list(
        Item.objects.filter(stock_movements__in=filter_movements(filters))
        .exclude(stock_balances__in=balances)
        .distinct()[:20]
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
    suspicious_stock = (
        len(stock_warnings["zero_active_balances"])
        + len(stock_warnings["stock_without_movement"])
        + len(stock_warnings["movement_without_balance"])
    )
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
        "issue_without_recipient": {
            "count": missing_fields["issue_without_recipient"].count(),
            "examples": _limited_examples(missing_fields["issue_without_recipient"]),
        },
        "issue_without_usage_place": {
            "count": missing_fields["issue_without_usage_place"].count(),
            "examples": _limited_examples(missing_fields["issue_without_usage_place"]),
        },
        "movement_without_item": {
            "count": missing_fields["movement_without_item"].count(),
            "examples": _limited_examples(missing_fields["movement_without_item"]),
        },
        "non_positive_qty": {
            "count": missing_fields["non_positive_qty"].count(),
            "examples": _limited_examples(missing_fields["non_positive_qty"]),
        },
        "receive_without_destination": {
            "count": missing_fields["receive_without_destination"].count(),
            "examples": _limited_examples(missing_fields["receive_without_destination"]),
        },
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
