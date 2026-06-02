from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from .warehouse_access_utils import grant_warehouse_access
from ..models import (
    Category,
    Item,
    Location,
    Recipient,
    StockBalance,
    StockMovement,
    Unit,
    Warehouse,
)


class AnalyticsInterfaceTestBase(TestCase):
    def setUp(self):
        call_command("init_roles", stdout=StringIO())
        self.admin = get_user_model().objects.create_user(
            username="admin", password="pw"
        )
        self.admin.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.storekeeper = get_user_model().objects.create_user(
            username="keeper", password="pw"
        )
        self.storekeeper.groups.add(Group.objects.get(name="Комірник"))
        self.auditor = get_user_model().objects.create_user(
            username="auditor", password="pw"
        )
        self.superuser = get_user_model().objects.create_superuser(
            username="root", password="pw", email="root@example.com"
        )
        self.auditor.groups.add(Group.objects.get(name="Перегляд / аудитор"))
        self.unit = Unit.objects.create(name="Штука", symbol="шт")
        self.category = Category.objects.create(name="Кабель")
        self.item = Item.objects.create(
            name="Кабель ВВГ",
            internal_code="CBL-1",
            category=self.category,
            unit=self.unit,
        )
        self.other_item = Item.objects.create(
            name="Автомат",
            internal_code="AUTO-1",
            category=self.category,
            unit=self.unit,
        )
        self.warehouse = Warehouse.objects.create(name="Основний склад")
        self.other_warehouse = Warehouse.objects.create(name="Резервний склад")
        grant_warehouse_access(
            self.admin,
            [self.warehouse, self.other_warehouse],
            can_delegate=True,
        )
        grant_warehouse_access(
            self.storekeeper,
            [self.warehouse, self.other_warehouse],
        )
        grant_warehouse_access(
            self.auditor,
            [self.warehouse, self.other_warehouse],
        )
        self.location = Location.objects.create(warehouse=self.warehouse, name="A1")
        self.other_location = Location.objects.create(
            warehouse=self.other_warehouse, name="B1"
        )
        self.recipient = Recipient.objects.create(name="Цех 1")
        self.balance = StockBalance.objects.create(
            item=self.item, location=self.location, qty=Decimal("7.000")
        )
        StockBalance.objects.create(
            item=self.other_item, location=self.other_location, qty=Decimal("0.000")
        )
        StockMovement.objects.create(
            movement_type=StockMovement.MovementType.IN,
            item=self.item,
            qty=Decimal("10.000"),
            destination_location=self.location,
            occurred_at=timezone.datetime(
                2026, 1, 10, 12, tzinfo=timezone.get_current_timezone()
            ),
        )
        StockMovement.objects.create(
            movement_type=StockMovement.MovementType.OUT,
            item=self.item,
            qty=Decimal("3.000"),
            source_location=self.location,
            recipient=self.recipient,
            occurred_at=timezone.datetime(
                2026, 1, 12, 12, tzinfo=timezone.get_current_timezone()
            ),
        )
        StockMovement.objects.create(
            movement_type=StockMovement.MovementType.IN,
            item=self.other_item,
            qty=Decimal("5.000"),
            destination_location=self.other_location,
            occurred_at=timezone.datetime(
                2026, 2, 1, 12, tzinfo=timezone.get_current_timezone()
            ),
        )


class WarehouseAnalyticsAuditTestBase(TestCase):
    def setUp(self):
        call_command("init_roles", stdout=StringIO())
        User = get_user_model()
        self.superuser = User.objects.create_superuser(
            username="analytics-root", password="pw", email="analytics-root@example.com"
        )
        self.admin = User.objects.create_user(username="analytics-admin", password="pw")
        self.admin.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.user = User.objects.create_user(username="analytics-user", password="pw")
        self.user.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.no_access_user = User.objects.create_user(
            username="analytics-no-access", password="pw"
        )
        self.no_access_user.groups.add(Group.objects.get(name="Адміністратор складу"))

        self.unit = Unit.objects.create(name="Piece", symbol="pc")
        self.item = Item.objects.create(
            name="Audit Cable", unit=self.unit, internal_code="AUD-CBL"
        )
        self.other_item = Item.objects.create(
            name="Audit Bolt", unit=self.unit, internal_code="AUD-BLT"
        )
        self.warehouse = Warehouse.objects.create(name="Audit Warehouse A")
        self.other_warehouse = Warehouse.objects.create(name="Audit Warehouse B")
        self.location = Location.objects.create(
            warehouse=self.warehouse, name="Основна локація"
        )
        self.other_location = Location.objects.create(
            warehouse=self.other_warehouse, name="Основна локація"
        )
        self.recipient = Recipient.objects.create(name="Audit Recipient")
        grant_warehouse_access(self.admin, self.warehouse, can_delegate=True)
        grant_warehouse_access(self.user, self.warehouse)
        grant_warehouse_access(self.no_access_user, [])

        self.now = timezone.now()
        self.today = timezone.localdate(self.now)
        StockBalance.objects.create(
            item=self.item, location=self.location, qty=Decimal("12.000")
        )
        StockBalance.objects.create(
            item=self.other_item, location=self.other_location, qty=Decimal("4.000")
        )
        self.receive = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.IN,
            item=self.item,
            qty=Decimal("20.000"),
            destination_location=self.location,
            occurred_at=self.now,
            document_number="AUD-IN",
        )
        self.issue = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.OUT,
            item=self.item,
            qty=Decimal("5.000"),
            source_location=self.location,
            recipient=self.recipient,
            department="Audit Dept",
            occurred_at=self.now,
            document_number="AUD-OUT",
        )
        self.return_movement = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.RETURN,
            item=self.item,
            qty=Decimal("2.000"),
            destination_location=self.location,
            recipient=self.recipient,
            occurred_at=self.now,
            document_number="AUD-RET",
        )
        self.writeoff = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.WRITEOFF,
            item=self.item,
            qty=Decimal("1.000"),
            source_location=self.location,
            occurred_at=self.now,
            document_number="AUD-WOFF",
        )
        self.transfer = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.TRANSFER,
            item=self.item,
            qty=Decimal("3.000"),
            source_location=self.location,
            destination_location=self.other_location,
            occurred_at=self.now,
            document_number="AUD-TRN",
        )
        self.other_receive = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.IN,
            item=self.other_item,
            qty=Decimal("7.000"),
            destination_location=self.other_location,
            occurred_at=self.now,
            document_number="AUD-OTHER-IN",
        )
        self.old_receive = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.IN,
            item=self.item,
            qty=Decimal("11.000"),
            destination_location=self.location,
            occurred_at=self.now - timezone.timedelta(days=45),
            document_number="AUD-OLD-IN",
        )
        self.cancelled = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.IN,
            item=self.item,
            qty=Decimal("99.000"),
            destination_location=self.location,
            occurred_at=self.now,
            document_number="AUD-CANCELLED",
            is_cancelled=True,
        )
        self.reversal = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.OUT,
            item=self.item,
            qty=Decimal("99.000"),
            source_location=self.location,
            occurred_at=self.now,
            document_number="AUD-REVERSAL",
            reversal_of=self.cancelled,
        )
        self.cancelled.cancellation_movement = self.reversal
        self.cancelled.save(update_fields=["cancellation_movement"])

    def summary_for_user(self, user, **filters):
        from core.services.analytics import get_analytics_summary
        from core.services.warehouse_access import get_accessible_warehouses

        filters["accessible_warehouses"] = get_accessible_warehouses(user)
        return get_analytics_summary(filters)
