from decimal import Decimal
from io import StringIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase

from ..models import (
    Category,
    Item,
    Location,
    Recipient,
    StockBalance,
    StockMovement,
    Unit,
    UsagePlace,
    Warehouse,
)
from .i18n_test_utils import compile_test_messages
from .warehouse_access_utils import grant_warehouse_access


class I18NReadinessAuditTests(TestCase):
    """Regression coverage for tablet/self-service localization readiness."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        compile_test_messages()

    def setUp(self):
        call_command("init_roles", stdout=StringIO())
        User = get_user_model()
        self.admin = User.objects.create_user(username="audit-admin", password="pw")
        self.admin.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.storekeeper = User.objects.create_user(username="audit-keeper", password="pw")
        self.storekeeper.groups.add(Group.objects.get(name="Комірник"))
        self.unit = Unit.objects.create(name="Each", symbol="ea")
        self.category = Category.objects.create(name="Hardware")
        self.recipient = Recipient.objects.create(name="Alex Smith")
        self.usage_place = UsagePlace.objects.create(name="Assembly line")
        self.item = Item.objects.create(
            name="Bolt M8",
            internal_code="BOLT-M8",
            category=self.category,
            unit=self.unit,
        )
        self.warehouse = Warehouse.objects.create(name="Main warehouse")
        grant_warehouse_access(self.admin, self.warehouse, can_delegate=True)
        grant_warehouse_access(self.storekeeper, self.warehouse)
        self.location = Location.objects.create(
            warehouse=self.warehouse, name="Main location"
        )
        self.balance = StockBalance.objects.create(
            item=self.item, location=self.location, qty=Decimal("10.000")
        )
        self.issue_movement = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.OUT,
            item=self.item,
            qty=Decimal("1.000"),
            source_location=self.location,
            recipient=self.recipient,
            department=self.usage_place.name,
        )
        self.receive_movement = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.RETURN,
            item=self.item,
            qty=Decimal("1.000"),
            destination_location=self.location,
            recipient=self.recipient,
            department=self.usage_place.name,
        )

    def tearDown(self):
        from django.utils import translation

        translation.activate("uk")

    def assert_no_phrases(self, html, phrases):
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, html)

    def test_english_login_home_forms_results_and_print_slip_do_not_leak_ukrainian_ui(self):
        forbidden_phrases = [
            "Взяти товар",
            "Повернути товар",
            "Склад",
            "Локація",
            "Отримувачі",
            "Кількість",
            "Збереження",
            "Друкувати",
            "Журнал операцій",
            "Залишки",
            "Номенклатура",
            "Сканування товару",
            "Знайдений товар",
            "Хто взяв товар",
            "Хто повернув товар",
            "Контрольний талон",
        ]
        pages = [
            ("/en/accounts/login/", None),
            ("/en/", self.storekeeper),
            ("/en/stock/issue/", self.storekeeper),
            ("/en/stock/receive/", self.storekeeper),
            (f"/en/stock/issue/?barcode={self.item.barcode.barcode}", self.storekeeper),
            (f"/en/stock/receive/?barcode={self.item.barcode.barcode}", self.storekeeper),
            (f"/en/stock/issue/{self.issue_movement.pk}/", self.storekeeper),
            (f"/en/stock/receive/{self.receive_movement.pk}/", self.storekeeper),
            (f"/en/stock/movements/{self.issue_movement.pk}/print/", self.storekeeper),
        ]
        for path, user in pages:
            with self.subTest(path=path):
                self.client.logout()
                if user is not None:
                    self.client.force_login(user)
                response = self.client.get(path)
                html = response.content.decode()

                self.assertEqual(response.status_code, 200)
                self.assert_no_phrases(html, forbidden_phrases)

    def test_english_management_pages_use_localized_labels(self):
        self.client.force_login(self.admin)
        expected_labels = [
            "Items / materials",
            "Employees / recipients",
            "Usage places",
            "Operation journal",
            "Stock balances",
            "Quick warehouse actions",
            "Warehouse settings",
        ]
        forbidden_management_labels = [
            "Товари / матеріали",
            "Працівники / отримувачі",
            "Місця використання",
            "Журнал операцій",
            "Залишки на складі",
            "Швидкі складські операції",
            "Налаштування складу",
        ]
        for path in [
            "/en/management/",
            "/en/management/directories/",
            "/en/management/settings/",
            "/en/items/",
            "/en/recipients/",
            "/en/stock/balances/",
            "/en/stock/movements/",
        ]:
            with self.subTest(path=path):
                response = self.client.get(path)
                html = response.content.decode()

                self.assertEqual(response.status_code, 200)
                self.assert_no_phrases(html, forbidden_management_labels)
                self.assertTrue(
                    any(label in html for label in expected_labels),
                    f"Expected one management/sidebar label on {path}",
                )

    def test_self_service_form_scripts_are_shared_without_changing_tablet_hooks(self):
        include = Path("templates/core/includes/self_service_form_scripts.html").read_text()
        issue_template = Path("templates/core/stock_issue_form.html").read_text()
        receive_template = Path("templates/core/stock_receive_form.html").read_text()

        self.assertIn('include "core/includes/self_service_form_scripts.html"', issue_template)
        self.assertIn('include "core/includes/self_service_form_scripts.html"', receive_template)
        for hook in [
            'form[data-disable-on-submit]',
            '[data-submit-button]',
            '[data-qty-stepper]',
            '[data-qty-decrement]',
            '[data-qty-increment]',
            'Math.max(1, normalizeQuantity() - 1)',
        ]:
            self.assertIn(hook, include)
