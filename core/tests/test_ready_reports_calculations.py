from decimal import Decimal
from io import StringIO
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Item, Location, StockMovement, Unit, Warehouse
from core.services.analytics import (
    get_analytics_data_quality,
    get_analytics_summary,
    get_xlsx_summary_rows,
)
from core.services.analytics_presets import get_analytics_report_presets


class ReadyReportCalculationTests(TestCase):
    def setUp(self):
        call_command("init_roles", stdout=StringIO())
        self.user = get_user_model().objects.create_superuser(
            "ready-reports-root", password="pw", email="root@example.com"
        )
        self.client.force_login(self.user)
        self.unit = Unit.objects.create(name="Ready report unit", symbol="rr")
        self.item = Item.objects.create(name="Ready report item", unit=self.unit)
        self.warehouse = Warehouse.objects.create(name="Ready report warehouse")
        self.location = Location.objects.create(
            warehouse=self.warehouse, name="Ready report location"
        )
        self.other_warehouse = Warehouse.objects.create(name="Other warehouse")
        self.other_location = Location.objects.create(
            warehouse=self.other_warehouse, name="Other location"
        )
        self.now = timezone.now()
        self.today = timezone.localdate(self.now)

        self.receive = self.create_movement(
            StockMovement.MovementType.IN,
            Decimal("10.000"),
            destination_location=self.location,
            document_number="RECEIVE",
        )
        self.issue = self.create_movement(
            StockMovement.MovementType.OUT,
            Decimal("3.000"),
            source_location=self.location,
            document_number="ISSUE",
        )
        self.return_movement = self.create_movement(
            StockMovement.MovementType.RETURN,
            Decimal("2.000"),
            destination_location=self.location,
            document_number="RETURN",
        )
        self.outside_range = self.create_movement(
            StockMovement.MovementType.IN,
            Decimal("50.000"),
            destination_location=self.location,
            occurred_at=self.now - timezone.timedelta(days=10),
            document_number="OUTSIDE-RANGE",
        )
        self.other_warehouse_receive = self.create_movement(
            StockMovement.MovementType.IN,
            Decimal("40.000"),
            destination_location=self.other_location,
            document_number="OTHER-WAREHOUSE",
        )
        self.cancelled = self.create_movement(
            StockMovement.MovementType.IN,
            Decimal("99.000"),
            destination_location=self.location,
            document_number="",
            is_cancelled=True,
        )
        self.reversal = self.create_movement(
            StockMovement.MovementType.OUT,
            Decimal("99.000"),
            source_location=self.location,
            document_number="",
            reversal_of=self.cancelled,
        )
        self.cancelled.cancellation_movement = self.reversal
        self.cancelled.save(update_fields=["cancellation_movement"])

    def create_movement(self, movement_type, qty, occurred_at=None, **kwargs):
        return StockMovement.objects.create(
            movement_type=movement_type,
            item=self.item,
            qty=qty,
            occurred_at=occurred_at or self.now,
            **kwargs,
        )

    def filters(self, **extra):
        return {
            "date_from": self.today,
            "date_to": self.today,
            "warehouse": self.warehouse,
            **extra,
        }

    def journal_response(self, **extra):
        params = {
            "report_scope": "business",
            "date_from": self.today.isoformat(),
            "date_to": self.today.isoformat(),
            "warehouse": str(self.warehouse.pk),
            **extra,
        }
        return self.client.get(reverse("movement_list"), params)

    def test_all_ready_reports_document_their_calculation_rule(self):
        presets = get_analytics_report_presets()

        self.assertEqual(
            {preset["key"] for preset in presets},
            {
                "issue_7d",
                "issue_30d",
                "top_items_month",
                "top_usage_places_month",
                "missing_documents",
                "data_quality",
                "negative_stock",
                "inactive_stock",
                "recent_movements",
            },
        )
        self.assertTrue(all(preset.get("calculation_rule") for preset in presets))

    def test_business_report_scope_matches_analytics_summary(self):
        summary = get_analytics_summary(self.filters())
        response = self.journal_response()

        self.assertEqual(summary["operations_count"], 3)
        self.assertEqual(summary["receive_qty"], Decimal("10.000"))
        self.assertEqual(summary["issue_qty"], Decimal("3.000"))
        self.assertEqual(summary["return_qty"], Decimal("2.000"))
        self.assertEqual(response.context["paginator"].count, summary["operations_count"])
        self.assertEqual(
            set(response.context["movements"]),
            {self.receive, self.issue, self.return_movement},
        )

    def test_business_report_scope_applies_location_and_operation_type(self):
        response = self.journal_response(
            location=str(self.location.pk),
            movement_type=StockMovement.MovementType.OUT,
        )
        summary = get_analytics_summary(
            self.filters(
                location=self.location,
                movement_type=StockMovement.MovementType.OUT,
            )
        )

        self.assertEqual(response.context["paginator"].count, 1)
        self.assertEqual(list(response.context["movements"]), [self.issue])
        self.assertEqual(summary["operations_count"], 1)
        self.assertEqual(summary["issue_qty"], Decimal("3.000"))

    def test_recent_operations_preset_uses_occurred_at_dates_and_business_scope(self):
        preset = next(
            preset
            for preset in get_analytics_report_presets()
            if preset["key"] == "recent_movements"
        )
        params = parse_qs(urlparse(preset["url"]).query)

        self.assertEqual(params["report_scope"], ["business"])
        self.assertNotIn("period", params)
        self.assertEqual(params["date_to"], [self.today.isoformat()])
        self.assertEqual(
            params["date_from"],
            [(self.today - timezone.timedelta(days=6)).isoformat()],
        )

    def test_missing_documents_ready_report_excludes_cancelled_and_reversal_rows(self):
        preset = next(
            preset
            for preset in get_analytics_report_presets()
            if preset["key"] == "missing_documents"
        )
        response = self.client.get(preset["url"])

        self.assertEqual(response.context["paginator"].count, 0)
        self.assertEqual(list(response.context["movements"]), [])

    def test_ready_report_export_summary_agrees_with_analytics(self):
        filters = self.filters()
        summary = get_analytics_summary(filters)
        export_rows = dict(get_xlsx_summary_rows(filters))

        self.assertEqual(export_rows["operations_count"], summary["operations_count"])
        self.assertEqual(export_rows["receive_qty"], float(summary["receive_qty"]))
        self.assertEqual(export_rows["issue_qty"], float(summary["issue_qty"]))
        self.assertEqual(export_rows["return_qty"], float(summary["return_qty"]))

    def test_data_quality_receive_with_location_has_a_resolved_destination(self):
        data_quality = get_analytics_data_quality(self.filters())

        self.assertEqual(
            data_quality["checks"]["receive_without_destination"]["count"],
            0,
        )

    def test_data_quality_drilldown_matches_report_count(self):
        response = self.client.get(
            reverse("management_analytics_data_quality"),
            {
                "period": "custom",
                "date_from": self.today.isoformat(),
                "date_to": self.today.isoformat(),
                "warehouse": str(self.warehouse.pk),
            },
        )
        check = next(
            check
            for check in response.context["quality_checks"]
            if check["key"] == "issue_without_recipient"
        )
        journal_response = self.client.get(check["journal_url"])

        self.assertEqual(check["count"], 1)
        self.assertEqual(journal_response.context["paginator"].count, check["count"])
        self.assertEqual(list(journal_response.context["movements"]), [self.issue])
