from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone, translation

from ..models import (
    InventoryCount,
    Item,
    Location,
    Recipient,
    StockMovement,
    Unit,
    Warehouse,
)
from .i18n_test_utils import compile_test_messages
from .warehouse_access_utils import grant_warehouse_access


class StockOperationAuditTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        compile_test_messages()

    def setUp(self):
        translation.activate("uk")
        call_command("init_roles", stdout=StringIO())
        User = get_user_model()
        self.admin = User.objects.create_user("operation-audit-admin", password="pw")
        self.admin.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.storekeeper = User.objects.create_user(
            "operation-audit-storekeeper",
            password="pw",
        )
        self.storekeeper.groups.add(Group.objects.get(name="Комірник"))
        self.actor = User.objects.create_user(
            "operation-audit-actor",
            password="pw",
            first_name="Audit",
            last_name="Actor",
        )
        self.canceller = User.objects.create_user(
            "operation-audit-canceller",
            password="pw",
            first_name="Cancel",
            last_name="Manager",
        )
        self.unit = Unit.objects.create(name="Audit piece", symbol="ap")
        self.item = Item.objects.create(
            name="Audit cable",
            internal_code="AUDIT-CABLE",
            unit=self.unit,
        )
        self.other_item = Item.objects.create(name="Other audit item", unit=self.unit)
        self.warehouse = Warehouse.objects.create(name="Audit warehouse")
        self.other_warehouse = Warehouse.objects.create(name="Other audit warehouse")
        grant_warehouse_access(self.admin, [self.warehouse, self.other_warehouse])
        grant_warehouse_access(self.storekeeper, [self.warehouse, self.other_warehouse])
        self.location = Location.objects.create(warehouse=self.warehouse, name="AUDIT-A")
        self.other_location = Location.objects.create(
            warehouse=self.other_warehouse,
            name="AUDIT-B",
        )
        self.recipient = Recipient.objects.create(name="Audit recipient")
        self.inventory = InventoryCount.objects.create(
            number="INV-AUDIT-0001",
            warehouse=self.warehouse,
            status=InventoryCount.Status.COMPLETED,
        )
        self.old_movement = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.IN,
            item=self.other_item,
            qty=Decimal("5.000"),
            destination_warehouse=self.other_warehouse,
            destination_location=self.other_location,
            performed_by=self.actor,
            created_by=self.actor,
            document_number="AUDIT-OLD",
        )
        self.movement = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.OUT,
            item=self.item,
            qty=Decimal("2.000"),
            source_warehouse=self.warehouse,
            source_location=self.location,
            recipient=self.recipient,
            performed_by=self.actor,
            created_by=self.actor,
            document_number="AUDIT-DOC",
            comment="Business audit comment",
            inventory_count=self.inventory,
        )
        self.reversal = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.ADJUSTMENT,
            item=self.item,
            qty=Decimal("2.000"),
            destination_warehouse=self.warehouse,
            destination_location=self.location,
            performed_by=self.canceller,
            created_by=self.canceller,
            reversal_of=self.movement,
            comment="Cancellation movement",
        )
        self.movement.is_cancelled = True
        self.movement.cancelled_by = self.canceller
        self.movement.cancelled_at = timezone.now()
        self.movement.cancellation_reason = "Wrong recipient"
        self.movement.cancellation_movement = self.reversal
        self.movement.save(
            update_fields=[
                "is_cancelled",
                "cancelled_by",
                "cancelled_at",
                "cancellation_reason",
                "cancellation_movement",
                "updated_at",
            ]
        )
        old_created_at = timezone.now() - timedelta(days=10)
        StockMovement.objects.filter(pk=self.old_movement.pk).update(
            created_at=old_created_at
        )
        self.old_movement.refresh_from_db()
        self.url = reverse("stock_operation_audit")

    def audit_response(self, params=None, user=None):
        self.client.force_login(user or self.admin)
        return self.client.get(self.url, params or {})

    def movement_ids(self, response):
        return [movement.pk for movement in response.context["movements"]]

    def test_management_user_can_open_operation_audit(self):
        response = self.audit_response()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Аудит операцій")

    def test_non_management_user_cannot_open_operation_audit(self):
        response = self.audit_response(user=self.storekeeper)

        self.assertEqual(response.status_code, 403)

    def test_page_shows_business_fields_and_linked_records(self):
        response = self.audit_response()

        self.assertContains(response, "Audit cable")
        self.assertEqual(response.context["movements"][1].qty, Decimal("2.000"))
        self.assertContains(response, "Audit warehouse")
        self.assertContains(response, "Audit recipient")
        self.assertContains(response, "AUDIT-DOC")
        self.assertContains(response, "Business audit comment")
        self.assertContains(response, "Audit Actor")
        self.assertContains(response, "Cancel Manager")
        self.assertContains(response, "Wrong recipient")
        self.assertContains(response, "Анулювано")
        self.assertContains(response, "Пов'язано з інвентаризацією")
        self.assertContains(response, reverse("inventory_detail", args=[self.inventory.pk]))
        self.assertContains(response, reverse("stock_movement_print", args=[self.reversal.pk]))

    def test_filters_by_date_operation_type_warehouse_and_cancelled(self):
        today = timezone.localdate().isoformat()

        response = self.audit_response(
            {
                "date_from": today,
                "date_to": today,
                "movement_type": StockMovement.MovementType.OUT,
                "warehouse": self.warehouse.pk,
                "cancelled": "yes",
            }
        )

        self.assertEqual(self.movement_ids(response), [self.movement.pk])

    def test_cancelled_no_filter_excludes_cancelled_movement(self):
        response = self.audit_response({"cancelled": "no"})

        self.assertNotIn(self.movement.pk, self.movement_ids(response))
        self.assertIn(self.old_movement.pk, self.movement_ids(response))

    def test_filters_by_item_recipient_user_and_inventory_relation(self):
        response = self.audit_response(
            {
                "q": "AUDIT-CABLE",
                "recipient": self.recipient.pk,
                "user": self.actor.pk,
                "inventory_related": "yes",
            }
        )

        self.assertEqual(self.movement_ids(response), [self.movement.pk])

    def test_newest_movements_are_listed_first(self):
        response = self.audit_response()

        self.assertEqual(self.movement_ids(response)[0], self.reversal.pk)
        self.assertEqual(self.movement_ids(response)[-1], self.old_movement.pk)

    def test_localized_operation_audit_labels(self):
        expectations = {
            "uk": "Аудит операцій",
            "en": "Operation audit",
            "ru": "Аудит операций",
        }

        for language_code, label in expectations.items():
            self.client.force_login(self.admin)
            response = self.client.get(f"/{language_code}{self.url[3:]}")
            with self.subTest(language_code=language_code):
                self.assertContains(response, label)
