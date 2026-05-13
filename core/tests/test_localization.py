from decimal import Decimal
from pathlib import Path
from unittest import mock
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone
from io import BytesIO, StringIO
from django.urls import reverse
from ..forms import CategoryForm, ItemForm, LocationForm, StockBalanceFilterForm, StockTransferForm
from ..models import (
    BarcodeRegistry,
    BarcodeSequence,
    Category,
    InventoryCount,
    InventoryCountLine,
    Item,
    LabelTemplate,
    Location,
    PrintJob,
    Printer,
    Recipient,
    StockBalance,
    StockMovement,
    Unit,
    Warehouse,
)


class LocalizedWebInterfaceTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="ui-user", password="test-password"
        )
        call_command("init_roles", stdout=StringIO())
        self.user.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.client.force_login(self.user)
        self.unit = Unit.objects.create(name="Штука", symbol="шт")
        self.category = Category.objects.create(name="Матеріали")
        self.recipient = Recipient.objects.create(name="Цех 1")
        self.item = Item.objects.create(
            name="Болт М8",
            internal_code="BOLT-M8",
            category=self.category,
            unit=self.unit,
        )
        self.warehouse = Warehouse.objects.create(name="Основний склад")
        self.location = Location.objects.create(warehouse=self.warehouse, name="A-01")
        self.balance = StockBalance.objects.create(
            item=self.item, location=self.location, qty=Decimal("5.000")
        )

    def test_localized_home_pages_show_yantos_brand(self):
        for path in ["/uk/", "/en/"]:
            with self.subTest(path=path):
                response = self.client.get(path)

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "YANTOS")

    def test_base_navbar_uses_yantos_theme_instead_of_bootstrap_primary(self):
        template = Path("templates/base.html").read_text()

        self.assertNotIn("navbar-dark bg-primary", template)
        self.assertNotIn("bg-primary", template)
        self.assertIn("yantos-navbar", template)
        self.assertIn('brand-name">YANTOS</span>', template)
        self.assertNotIn('brand-name">Yantos</span>', template)

    def test_item_form_labels_are_ukrainian(self):
        response = self.client.get(reverse("item_create"))

        for label in ["Назва", "Внутрішній код", "Категорія", "Одиниця виміру", "Опис"]:
            self.assertContains(response, label)
        self.assertNotContains(response, ">Name<")
        self.assertNotContains(response, ">Internal code<")


class SwitchLanguageUrlTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def assert_switch_url(self, source_url, language_code, expected_url):
        from ..templatetags.i18n_extras import switch_language_url

        request = self.factory.get(source_url)
        self.assertEqual(switch_language_url(request, language_code), expected_url)

    def test_replaces_existing_language_prefix(self):
        self.assert_switch_url("/uk/", "en", "/en/")
        self.assert_switch_url("/en/items/", "uk", "/uk/items/")

    def test_preserves_query_string(self):
        self.assert_switch_url("/uk/items/?q=test", "en", "/en/items/?q=test")

    def test_adds_language_prefix_when_missing(self):
        self.assert_switch_url("/admin/", "en", "/en/admin/")
        self.assert_switch_url("/", "uk", "/uk/")


class DashboardLocalizationTests(TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        call_command("compilemessages", verbosity=0)

    def setUp(self):
        call_command("init_roles", stdout=StringIO())
        User = get_user_model()
        self.admin = User.objects.create_user(username="dash-admin", password="pw")
        self.admin.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.storekeeper = User.objects.create_user(
            username="dash-storekeeper", password="pw"
        )
        self.storekeeper.groups.add(Group.objects.get(name="Комірник"))
        self.auditor = User.objects.create_user(username="dash-auditor", password="pw")
        self.auditor.groups.add(Group.objects.get(name="Перегляд / аудитор"))

    def dashboard_for(self, user, path=None):
        from django.utils import translation

        translation.activate("en" if path and path.startswith("/en/") else "uk")
        self.client.force_login(user)
        return self.client.get(path or reverse("dashboard"))

    def tearDown(self):
        from django.utils import translation

        translation.activate("uk")

    def test_english_dashboard_contains_stock_writeoff(self):
        response = self.dashboard_for(self.admin, "/en/")

        self.assertContains(response, "Stock write-off")

    def test_ukrainian_dashboard_contains_stock_writeoff(self):
        response = self.dashboard_for(self.admin, "/uk/")

        self.assertContains(response, "Списання товару")

    def test_english_dashboard_contains_stock_transfer(self):
        response = self.dashboard_for(self.admin, "/en/")

        self.assertContains(response, "Stock transfer")

    def test_english_storekeeper_workplace_uses_only_english_action_terms(self):
        response = self.dashboard_for(self.storekeeper, "/en/")
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        main_html = html[html.index('<main class="col-12">'):]
        self.assertIn("Warehouse self-service", main_html)
        for phrase in [
            "Take item",
            "Return item",
            "Choose an action",
        ]:
            self.assertIn(phrase, main_html)
        for phrase in [
            "Робоче місце комірника",
            "Комірник",
            "Повернення товару",
            "Перемістити товар",
            "Списати товар",
            "Провести інвентаризацію",
            "Перевірити залишки",
            "Надрукувати етикетку",
            "Пошук товару",
            "Назва, внутрішній код або штрихкод",
            "Знайти",
            "Допомога",
            "Взяти товар",
            "Повернути товар",
        ]:
            self.assertNotIn(phrase, main_html)

    def test_ukrainian_storekeeper_workplace_uses_only_ukrainian_action_terms(self):
        response = self.dashboard_for(self.storekeeper, "/uk/")
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        main_html = html[html.index('<main class="col-12">'):]
        self.assertIn("Склад самообслуговування", main_html)
        for phrase in [
            "Взяти товар",
            "Повернути товар",
            "Оберіть дію",
        ]:
            self.assertIn(phrase, main_html)
        for phrase in [
            "Storekeeper workplace",
            "Storekeeper",
            "Issue item",
            "Return item",
            "Transfer goods",
            "Write off goods",
            "Run inventory count",
            "Check stock",
            "Print label",
            "Item search",
            "Search",
            "Help",
            "Видача товару",
            "Повернення товару",
            "Допомога",
        ]:
            self.assertNotIn(phrase, main_html)

    def test_ukrainian_storekeeper_workplace_removes_complex_navigation(self):
        response = self.dashboard_for(self.storekeeper, "/uk/")
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("Склад самообслуговування", html)
        self.assertIn("Взяти товар", html)
        self.assertIn("Повернути товар", html)
        self.assertNotIn('class="navbar-toggler"', html)
        self.assertNotIn("Навігація", html)
        for phrase in [
            "Інвентаризація",
            "Аналітика",
            "Номенклатура",
            "Користувачі",
            "Рухи товарів",
            "Довідники",
            "Керування",
            "Допомога",
        ]:
            self.assertNotIn(phrase, html)

    def test_english_storekeeper_workplace_has_no_ukrainian_action_phrases(self):
        response = self.dashboard_for(self.storekeeper, "/en/")
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("Warehouse self-service", html)
        self.assertIn("Take item", html)
        self.assertIn("Return item", html)
        for phrase in [
            "Склад самообслуговування",
            "Оберіть дію",
            "Взяти товар",
            "Повернути товар",
        ]:
            self.assertNotIn(phrase, html)

    def test_admin_dashboard_keeps_navigation(self):
        response = self.dashboard_for(self.admin, "/uk/")
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("Навігація", html)
        self.assertIn("Інвентаризація", html)
        self.assertIn("Номенклатура", html)
        self.assertIn("Керування", html)

    def test_english_transfer_page_has_no_ukrainian_transfer_phrases(self):
        response = self.dashboard_for(self.admin, "/en/stock/transfer/")
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("Stock transfer", html)
        for phrase in [
            "Переміщення товару",
            "Перемістіть товар",
            "Склад-відправник",
            "Локація-відправник",
            "Перемістити",
        ]:
            self.assertNotIn(phrase, html)

    def test_ukrainian_transfer_page_has_no_english_transfer_phrases(self):
        response = self.dashboard_for(self.admin, "/uk/stock/transfer/")
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("Переміщення товару", html)
        for phrase in [
            "Stock transfer",
            "Move items between warehouses or locations",
            "Source warehouse",
            "Destination location",
        ]:
            self.assertNotIn(phrase, html)

    def test_language_switcher_lists_all_configured_languages(self):
        from django.conf import settings

        response = self.dashboard_for(self.admin, "/uk/")
        html = response.content.decode()

        for language_code, language_name in settings.LANGUAGES:
            with self.subTest(language=language_name):
                self.assertIn(f'value="{language_code}"', html)

    def test_ukrainian_dashboard_uses_only_ukrainian_navigation_terms(self):
        response = self.dashboard_for(self.admin, "/uk/")
        html = response.content.decode()

        for phrase in [
            "Головна",
            "Складські операції",
            "Прихід товару",
            "Видача товару",
            "Переміщення товару",
            "Списання товару",
            "Початкові залишки",
            "Інвентаризація",
            "Залишки",
            "Рухи товарів",
        ]:
            self.assertIn(phrase, html)
        for phrase in [
            "Warehouse operations",
            "Stock receipt",
            "Stock issue",
            "Initial balances",
            "Stock transfer",
            "Stock write-off",
            "Stock movements",
            "Open",
        ]:
            self.assertNotIn(phrase, html)

    def test_english_dashboard_uses_only_english_navigation_terms(self):
        response = self.dashboard_for(self.admin, "/en/")
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("YANTOS", html)
        for phrase in [
            "Home",
            "Warehouse operations",
            "Stock receipt",
            "Stock issue",
            "Stock transfer",
            "Stock write-off",
            "Initial balances",
            "Inventory count",
            "Stock balances",
            "Stock movements",
            "Open",
        ]:
            self.assertIn(phrase, html)
        for phrase in [
            "Головна",
            "Складські операції",
            "Прихід товару",
            "Видача товару",
            "Початкові залишки",
            "Переміщення товару",
            "Списання товару",
            "Рухи товарів",
            "Відкрити",
        ]:
            self.assertNotIn(phrase, html)

    def test_english_core_pages_do_not_show_ukrainian_menu_words(self):
        forbidden_phrases = [
            "Головна",
            "Навігація",
            "Складські операції",
            "Прихід товару",
            "Видача товару",
            "Початкові залишки",
            "Переміщення товару",
            "Списання товару",
            "Залишки",
            "Рухи товарів",
            "Довідники",
            "Етикетки",
            "Адміністрування",
            "Допомога",
            "Відкрити",
            "Зберегти",
            "Скасувати",
        ]
        for path in [
            "/en/stock/balances/",
            "/en/stock/movements/",
            "/en/stock/receive/",
            "/en/stock/issue/",
            "/en/stock/transfer/",
            "/en/stock/writeoff/",
            "/en/stock/initial/",
            "/en/stock/inventory/",
        ]:
            with self.subTest(path=path):
                response = self.dashboard_for(self.admin, path)
                html = response.content.decode()

                self.assertEqual(response.status_code, 200)
                self.assertIn("YANTOS", html)
                for phrase in forbidden_phrases:
                    self.assertNotIn(phrase, html)

    def test_ukrainian_core_pages_do_not_show_english_menu_words(self):
        forbidden_phrases = [
            "Warehouse operations",
            "Stock receipt",
            "Stock issue",
            "Stock transfer",
            "Stock write-off",
            "Initial balances",
            "Stock movements",
            "Stock balances",
            "Stock transfer",
            "Directories",
            "Labels",
            "Administration",
            "Management",
            "Help",
            "Open",
            "Save",
            "Cancel",
        ]
        for path in [
            "/uk/stock/balances/",
            "/uk/stock/movements/",
            "/uk/stock/receive/",
            "/uk/stock/issue/",
            "/uk/stock/transfer/",
            "/uk/stock/writeoff/",
            "/uk/stock/initial/",
            "/uk/stock/inventory/",
        ]:
            with self.subTest(path=path):
                response = self.dashboard_for(self.admin, path)
                html = response.content.decode()

                self.assertEqual(response.status_code, 200)
                self.assertIn("YANTOS", html)
                for phrase in forbidden_phrases:
                    self.assertNotIn(phrase, html)


    def test_english_management_dashboard_uses_only_english_terms(self):
        response = self.dashboard_for(self.admin, "/en/management/")
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("Warehouse administration", html)
        self.assertIn("Directories", html)
        self.assertIn("Users and roles", html)
        self.assertIn("System settings", html)
        for phrase in [
            "Адміністрування складу",
            "Керуйте довідниками",
            "Довідники",
            "Номенклатура",
            "Склади",
            "Локації",
            "Користувачі та ролі",
            "Налаштування системи",
            "Довідка адміністратора",
            "Відкрити",
        ]:
            self.assertNotIn(phrase, html)

    def test_ukrainian_storekeeper_workplace_links_to_scanner_flows(self):
        response = self.dashboard_for(self.storekeeper, "/uk/")
        html = response.content.decode()
        main_html = html[html.index('<main class="col-12">'):]

        self.assertEqual(response.status_code, 200)
        self.assertIn("Склад самообслуговування", main_html)
        self.assertIn("Взяти товар", main_html)
        self.assertIn("Повернути товар", main_html)
        self.assertNotIn("Робоче місце комірника", main_html)
        self.assertNotIn("Комірник", main_html)
        self.assertIn('/uk/stock/issue/', main_html)
        self.assertIn('/uk/stock/receive/', main_html)
        self.assertNotIn('id="storekeeper-item-search"', main_html)
        self.assertNotIn("autofocus", main_html)

    def test_english_dashboard_has_no_new_ukrainian_phrases_and_keeps_yantos_brand(self):
        response = self.dashboard_for(self.admin, "/en/")
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("YANTOS", html)
        self.assertIn("Warehouse operations", html)
        for phrase in [
            "Складські операції",
            "Прихід товару",
            "Видача товару",
            "Початкові залишки",
            "Переміщення товару",
            "Списання товару",
            "Керування",
        ]:
            self.assertNotIn(phrase, html)
