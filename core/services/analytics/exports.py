from django.utils.translation import gettext_lazy as _

from .data_quality import get_analytics_data_quality
from .summaries import (
    get_analytics_summary,
    get_daily_movement,
    get_inactive_stock_items,
    get_operation_mix,
    get_recent_movements,
    get_top_issued_items,
    get_top_recipients,
    get_top_usage_places,
)


def movement_export_location(movement, filters):
    if filters.get("location"):
        location = filters["location"]
        if movement.source_location_id == location.pk:
            return movement.source_location
        if movement.destination_location_id == location.pk:
            return movement.destination_location
    if filters.get("warehouse"):
        warehouse = filters["warehouse"]
        if movement.source_location and movement.source_location.warehouse_id == warehouse.pk:
            return movement.source_location
        if movement.destination_location and movement.destination_location.warehouse_id == warehouse.pk:
            return movement.destination_location
    return movement.destination_location or movement.source_location


def get_csv_export_sections(filters):
    summary = get_analytics_summary(filters)
    return [
        (
            [_("Розділ"), _("Показник"), _("Значення")],
            [
                [_("Зведення"), label, summary[key]]
                for key, label in [
                    ("operations_count", _("Операцій за період")),
                    ("receive_qty", _("Прихід")),
                    ("issue_qty", _("Видача")),
                    ("return_qty", _("Повернення")),
                    ("writeoff_qty", _("Списання")),
                ]
            ],
        ),
        (
            [_("Рух по днях"), _("Дата"), _("Операції"), _("Прихід"), _("Видача"), _("Повернення"), _("Списання")],
            [
                ["", row["day"], row["operations"], row["receive_qty"], row["issue_qty"], row["return_qty"], row["writeoff_qty"]]
                for row in get_daily_movement(filters)
            ],
        ),
        (
            [_("Топ товарів"), _("Номенклатура"), _("Кількість"), _("Операції")],
            [["", row["item__name"], row["total_qty"], row["operations"]] for row in get_top_issued_items(filters)],
        ),
        (
            [_("Топ цехів"), _("Цех"), _("Кількість"), _("Операції")],
            [["", row["department"], row["total_qty"], row["operations"]] for row in get_top_usage_places(filters)],
        ),
        (
            [_("Топ отримувачів"), _("Отримувач"), _("Кількість"), _("Операції")],
            [["", row["recipient__name"], row["total_qty"], row["operations"]] for row in get_top_recipients(filters)],
        ),
        (
            [_("Останні операції"), _("Дата"), _("Тип"), _("Номенклатура"), _("Кількість"), _("Документ")],
            [
                [
                    "",
                    movement.occurred_at.strftime("%Y-%m-%d %H:%M"),
                    movement.get_movement_type_display(),
                    movement.item.name,
                    movement.qty,
                    movement.document_number or "",
                ]
                for movement in get_recent_movements(filters)
            ],
        ),
    ]


def get_xlsx_summary_rows(filters):
    summary = get_analytics_summary(filters)
    return [
        [key, float(summary[key]) if hasattr(summary[key], "quantize") else summary[key]]
        for key in ["operations_count", "receive_qty", "issue_qty", "return_qty", "writeoff_qty"]
    ]


def get_xlsx_data_sheets(filters):
    return [
        (
            "Daily movement",
            ["Date", "Operations", "Receive", "Issue", "Return", "Writeoff"],
            [
                [
                    r["day"].isoformat() if r["day"] else "",
                    r["operations"],
                    float(r["receive_qty"] or 0),
                    float(r["issue_qty"] or 0),
                    float(r["return_qty"] or 0),
                    float(r["writeoff_qty"] or 0),
                ]
                for r in get_daily_movement(filters)
            ],
        ),
        (
            "Operation mix",
            ["Type", "Total", "Percent"],
            [[r["key"], r["total"], r["percent"]] for r in get_operation_mix(filters)],
        ),
        (
            "Top issued items",
            ["Item", "Code", "Qty", "Ops"],
            [[r["item__name"], r["item__internal_code"], float(r["total_qty"] or 0), r["operations"]] for r in get_top_issued_items(filters)],
        ),
        (
            "Top usage places",
            ["Usage place", "Qty", "Ops"],
            [[r["department"], float(r["total_qty"] or 0), r["operations"]] for r in get_top_usage_places(filters)],
        ),
        (
            "Top recipients",
            ["Recipient", "Qty", "Ops"],
            [[r["recipient__name"], float(r["total_qty"] or 0), r["operations"]] for r in get_top_recipients(filters)],
        ),
        (
            "Recent movements",
            ["Date", "Type", "Item", "Qty", "Document"],
            [
                [
                    m.occurred_at.strftime("%Y-%m-%d %H:%M"),
                    m.get_movement_type_display(),
                    m.item.name,
                    float(m.qty),
                    m.document_number or "",
                ]
                for m in get_recent_movements(filters)
            ],
        ),
        (
            "Inactive stock items",
            ["Item", "Code", "Qty"],
            [[r["item__name"], r["item__internal_code"], float(r["qty"] or 0)] for r in get_inactive_stock_items(filters)],
        ),
    ]


def get_xlsx_data_quality_rows(filters):
    dq = get_analytics_data_quality(filters)
    rec = dq["reconciliation"]
    metric_rows = [[key, dq[key]] for key in ["score", "status"]]
    metric_rows.extend(
        [
            [key, rec[key]]
            for key in [
                "total_movements",
                "daily_chart_operations",
                "difference",
                "incomplete_movements",
                "missing_documents",
                "negative_stock",
                "suspicious_stock",
            ]
        ]
    )
    check_rows = [[key, value["count"]] for key, value in dq["checks"].items()]
    return metric_rows, check_rows
