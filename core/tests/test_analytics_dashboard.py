from decimal import Decimal
from io import BytesIO, StringIO

from openpyxl import load_workbook

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Item, Location, Recipient, StockBalance, StockMovement, Unit, Warehouse
from core.services.analytics import get_analytics_summary, get_kpi_delta, get_top_issued_items


class AnalyticsDashboardTests(TestCase):
    def setUp(self):
        call_command("init_roles", stdout=StringIO())
        self.admin = get_user_model().objects.create_user("adm", password="pw")
        self.admin.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.storekeeper = get_user_model().objects.create_user("keeper", password="pw")
        self.storekeeper.groups.add(Group.objects.get(name="Комірник"))
        self.superuser = get_user_model().objects.create_superuser("root", password="pw", email="r@e.com")
        self.unit = Unit.objects.create(name="шт", symbol="шт")
        self.item = Item.objects.create(name="Кабель", unit=self.unit, internal_code="KB-1")
        self.wh = Warehouse.objects.create(name="WH")
        self.loc = Location.objects.create(name="L1", warehouse=self.wh)
        self.rec = Recipient.objects.create(name="Р1")
        StockBalance.objects.create(item=self.item, location=self.loc, qty=Decimal("5.000"))
        now = timezone.now()
        StockMovement.objects.create(movement_type=StockMovement.MovementType.IN, item=self.item, qty=Decimal("10.000"), destination_location=self.loc, occurred_at=now, document_number="DOC-IN")
        StockMovement.objects.create(movement_type=StockMovement.MovementType.OUT, item=self.item, qty=Decimal("2.000"), source_location=self.loc, recipient=self.rec, department="Цех 1", occurred_at=now, document_number="DOC-OUT")
        StockMovement.objects.create(movement_type=StockMovement.MovementType.OUT, item=self.item, qty=Decimal("1.000"), source_location=self.loc, occurred_at=now - timezone.timedelta(days=2), document_number="DOC-OLD")

    def test_access(self):
        self.assertEqual(self.client.get(reverse("management_analytics")).status_code, 302)
        self.client.force_login(self.storekeeper)
        self.assertEqual(self.client.get(reverse("management_analytics")).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("management_analytics")).status_code, 200)
        self.client.force_login(self.superuser)
        self.assertEqual(self.client.get(reverse("management_analytics")).status_code, 200)

    def test_dashboard_markers_and_drilldown(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse("management_analytics"))
        self.assertContains(r, "data-analytics-daily-chart")
        self.assertContains(r, "data-analytics-operation-mix")
        self.assertContains(r, "data-analytics-top-items-chart")
        self.assertContains(r, "movement_type=out")

    def test_summary_and_top(self):
        summary = get_analytics_summary({})
        self.assertEqual(summary["operations_count"], 3)
        top = get_top_issued_items({})
        self.assertEqual(top[0]["item__name"], "Кабель")

    def test_kpi_delta_helper(self):
        self.assertEqual(get_kpi_delta(10, 5)["trend"], "positive")
        self.assertEqual(get_kpi_delta(0, 0)["trend"], "neutral")
        self.assertEqual(get_kpi_delta(3, 0)["label"], "нові дані")

    def test_export_csv(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse("management_analytics_export_csv"), {"movement_type": StockMovement.MovementType.OUT})
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r["Content-Type"])
        self.assertIn("analytics", r["Content-Disposition"])
        body = r.content.decode("utf-8")
        self.assertIn("Топ товарів", body)
        self.assertIn("DOC-OUT", body)
        self.assertNotIn("DOC-IN", body)

    def test_recent_document_and_empty_state(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse("management_analytics"))
        self.assertContains(r, "DOC-OUT")
        StockMovement.objects.all().delete()
        r2 = self.client.get(reverse("management_analytics"))
        self.assertContains(r2, "За вибраний період операцій немає.")

    def test_detail_pages_and_links_and_quick_filters(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse("management_analytics"), {"date_from": "2026-01-01", "date_to": "2026-01-31"})
        self.assertContains(r, reverse("management_analytics_item_detail", args=[self.item.pk]))
        self.assertContains(r, reverse("management_analytics_usage_place_detail", args=["Цех 1"]))
        self.assertContains(r, reverse("management_analytics_recipient_detail", args=[self.rec.pk]))
        self.assertContains(r, "period=today")
        self.assertContains(r, "period=7d")
        self.assertContains(r, "period=30d")
        self.assertContains(r, "period=month")
        self.assertContains(r, "period=prev_month")

    def test_detail_access_permissions(self):
        self.client.force_login(self.storekeeper)
        self.assertEqual(self.client.get(reverse("management_analytics_item_detail", args=[self.item.pk])).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("management_analytics_item_detail", args=[self.item.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("management_analytics_usage_place_detail", args=["Цех 1"])).status_code, 200)
        self.assertEqual(self.client.get(reverse("management_analytics_recipient_detail", args=[self.rec.pk])).status_code, 200)

    def test_xlsx_export(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse("management_analytics_export_xlsx"), {"movement_type": StockMovement.MovementType.OUT})
        self.assertEqual(r.status_code, 200)
        self.assertIn("spreadsheetml", r["Content-Type"])
        wb = load_workbook(filename=BytesIO(r.content))
        for title in ["Summary", "Daily movement", "Operation mix", "Top issued items", "Top usage places", "Top recipients", "Recent movements", "Inactive stock items"]:
            self.assertIn(title, wb.sheetnames)
