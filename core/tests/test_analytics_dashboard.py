from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Item, Location, Recipient, StockBalance, StockMovement, Unit, Warehouse
from core.services.analytics import get_analytics_summary, get_top_issued_items


class AnalyticsDashboardTests(TestCase):
    def setUp(self):
        call_command("init_roles", stdout=StringIO())
        self.admin = get_user_model().objects.create_user("adm", password="pw")
        self.admin.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.storekeeper = get_user_model().objects.create_user("keeper", password="pw")
        self.storekeeper.groups.add(Group.objects.get(name="Комірник"))
        self.superuser = get_user_model().objects.create_superuser("root", password="pw", email="r@e.com")
        self.unit = Unit.objects.create(name="шт", symbol="шт")
        self.item = Item.objects.create(name="Кабель", unit=self.unit)
        self.wh = Warehouse.objects.create(name="WH")
        self.loc = Location.objects.create(name="L1", warehouse=self.wh)
        self.rec = Recipient.objects.create(name="Р1")
        StockBalance.objects.create(item=self.item, location=self.loc, qty=Decimal("5.000"))
        StockMovement.objects.create(movement_type=StockMovement.MovementType.IN, item=self.item, qty=Decimal("10.000"), destination_location=self.loc, occurred_at=timezone.now(), document_number="DOC-IN")
        StockMovement.objects.create(movement_type=StockMovement.MovementType.OUT, item=self.item, qty=Decimal("2.000"), source_location=self.loc, recipient=self.rec, department="Цех 1", occurred_at=timezone.now(), document_number="DOC-OUT")

    def test_access(self):
        self.assertEqual(self.client.get(reverse("management_analytics")).status_code, 302)
        self.client.force_login(self.storekeeper)
        self.assertEqual(self.client.get(reverse("management_analytics")).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("management_analytics")).status_code, 200)
        self.client.force_login(self.superuser)
        self.assertEqual(self.client.get(reverse("management_analytics")).status_code, 200)

    def test_page_sections(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse("management_analytics"))
        self.assertContains(r, "Аналітика складу")
        self.assertContains(r, "Операцій за період")
        self.assertContains(r, "Топ товарів по видачі")

    def test_summary_and_top(self):
        summary = get_analytics_summary({})
        self.assertEqual(summary["operations_count"], 2)
        top = get_top_issued_items({})
        self.assertEqual(top[0]["item__name"], "Кабель")

    def test_recent_document_and_empty_state(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse("management_analytics"))
        self.assertContains(r, "DOC-OUT")
        StockMovement.objects.all().delete()
        r2 = self.client.get(reverse("management_analytics"))
        self.assertContains(r2, "За вибраний період операцій немає.")
