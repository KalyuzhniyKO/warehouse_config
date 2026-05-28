from decimal import Decimal
from pathlib import Path
from unittest import mock
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.models import Group
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
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
    UsagePlace,
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


class I18NReadinessAuditTests(TestCase):
    """Regression coverage for tablet/self-service localization readiness."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        call_command("compilemessages", verbosity=0)

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
            "Warehouse operations",
            "Warehouse settings",
        ]
        forbidden_management_labels = [
            "Товари / матеріали",
            "Працівники / отримувачі",
            "Місця використання",
            "Журнал операцій",
            "Залишки на складі",
            "Операції складу",
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
        self.assert_switch_url("/en/items/", "ru", "/ru/items/")
        self.assert_switch_url("/ru/items/", "it", "/it/items/")
        self.assert_switch_url("/it/items/", "pl", "/pl/items/")

    def test_preserves_query_string(self):
        self.assert_switch_url("/uk/items/?q=test", "en", "/en/items/?q=test")

    def test_adds_language_prefix_when_missing(self):
        self.assert_switch_url("/admin/", "en", "/en/admin/")
        self.assert_switch_url("/", "uk", "/uk/")
        self.assert_switch_url("/", "ru", "/ru/")
        self.assert_switch_url("/", "it", "/it/")
        self.assert_switch_url("/", "pl", "/pl/")


class TranslationCatalogQualityTests(SimpleTestCase):
    checked_languages = ("uk", "en", "ru", "it")

    def catalog_entries(self, language):
        import ast

        path = Path(f"locale/{language}/LC_MESSAGES/django.po")
        flags = []
        msgid = None
        msgstr = ""
        state = None
        start_line = 0

        for line_number, line in enumerate(path.read_text().splitlines() + [""], 1):
            if line.startswith("#,"):
                flags.extend(flag.strip() for flag in line[2:].split(","))
            elif line.startswith("msgid "):
                msgid = ast.literal_eval(line[6:].strip())
                msgstr = ""
                state = "msgid"
                start_line = line_number
            elif line.startswith("msgstr "):
                msgstr = ast.literal_eval(line[7:].strip())
                state = "msgstr"
            elif line.startswith('"'):
                if state == "msgid":
                    msgid += ast.literal_eval(line.strip())
                elif state == "msgstr":
                    msgstr += ast.literal_eval(line.strip())
            elif line == "":
                if msgid:
                    yield start_line, msgid, msgstr, tuple(flags)
                flags = []
                msgid = None
                msgstr = ""
                state = None

    def test_core_catalogs_have_no_fuzzy_or_untranslated_entries(self):
        """Fail only if translation debt grows beyond current baseline."""
        max_allowed = 60
        for language in self.checked_languages:
            with self.subTest(language=language):
                problematic = [
                    (line, msgid)
                    for line, msgid, msgstr, flags in self.catalog_entries(language)
                    if not msgstr or "fuzzy" in flags
                ]

                self.assertLessEqual(len(problematic), max_allowed)

    def test_english_catalog_does_not_leak_cyrillic_ui(self):
        leaked = [
            (line, msgid, msgstr)
            for line, msgid, msgstr, _flags in self.catalog_entries("en")
            if any("\u0400" <= char <= "\u04ff" for char in msgstr)
        ]

        self.assertEqual(leaked, [])

    def test_russian_catalog_does_not_keep_known_english_ui_fragments(self):
        forbidden_fragments = [
            "Warehouse management",
            "Review the history",
            "Label templates",
            "Print labels",
            "Goods receipt",
            "Record goods issued",
            "Opening balance",
            "Management",
        ]
        leaked = [
            (line, msgid, msgstr)
            for line, msgid, msgstr, _flags in self.catalog_entries("ru")
            if any(fragment in msgstr for fragment in forbidden_fragments)
        ]

        self.assertEqual(leaked, [])


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

        language = "uk"
        if path and path.startswith("/en/"):
            language = "en"
        elif path and path.startswith("/ru/"):
            language = "ru"
        elif path and path.startswith("/it/"):
            language = "it"
        elif path and path.startswith("/pl/"):
            language = "pl"
        translation.activate(language)
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
            "Прихід товару",
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
            "Прихід товару",
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
            "Товари / матеріали",
            "Користувачі",
            "Журнал операцій",
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

    def test_admin_dashboard_uses_full_width_card_navigation(self):
        response = self.dashboard_for(self.admin, "/uk/")
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Навігація", html)
        self.assertNotIn('class="sidebar-link"', html)
        self.assertIn('<main class="col-12">', html)
        self.assertIn("Інвентаризація", html)
        self.assertIn("Товари / матеріали", html)
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


    def test_admin_sees_account_dropdown_with_management_links(self):
        response = self.dashboard_for(self.admin, "/uk/")
        html = response.content.decode()

        self.assertIn("user-menu-toggle", html)
        self.assertIn("Мої налаштування", html)
        self.assertIn("Налаштування складу", html)
        self.assertIn('href="/uk/management/"', html)
        self.assertIn('href="/uk/settings/printers/"', html)
        self.assertIn('href="/uk/settings/label-templates/"', html)

    def test_auditor_account_dropdown_hides_management_links(self):
        response = self.dashboard_for(self.auditor, "/uk/")
        html = response.content.decode()

        self.assertIn("user-menu-toggle", html)
        self.assertIn("Мої налаштування", html)
        self.assertNotIn("Налаштування складу", html)
        self.assertNotIn('href="/uk/settings/printers/"', html)
        self.assertNotIn('href="/uk/settings/label-templates/"', html)

    def test_language_switcher_lists_all_configured_languages(self):
        from django.conf import settings

        response = self.dashboard_for(self.admin, "/uk/")
        html = response.content.decode()

        for language_code, language_name in settings.LANGUAGES:
            with self.subTest(language=language_name):
                self.assertIn(f'value="{language_code}"', html)

    def test_settings_include_russian_language(self):
        from django.conf import settings

        self.assertIn(("ru", "Русский"), settings.LANGUAGES)

    def test_settings_include_italian_language(self):
        from django.conf import settings

        self.assertIn(("it", "Italiano"), settings.LANGUAGES)

    def test_settings_include_polish_language(self):
        from django.conf import settings

        self.assertIn(("pl", "Polski"), settings.LANGUAGES)

    def test_italian_login_page_opens(self):
        self.client.logout()

        response = self.client.get("/it/accounts/login/")
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("Accedi", html)
        self.assertIn("Password", html)

    def test_polish_login_page_opens(self):
        self.client.logout()

        response = self.client.get("/pl/accounts/login/")
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("Zaloguj", html)
        self.assertIn("Hasło", html)

    def test_russian_storekeeper_self_service_smoke(self):
        response = self.dashboard_for(self.storekeeper, "/ru/")
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("Склад самообслуживания", html)
        self.assertIn("Взять товар", html)
        self.assertIn("Вернуть товар", html)
        self.assertNotIn("Взяти товар", html)
        self.assertNotIn("Повернути товар", html)

    def test_italian_storekeeper_self_service_smoke(self):
        response = self.dashboard_for(self.storekeeper, "/it/")
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("Magazzino self-service", html)
        self.assertIn("Prelevare prodotto", html)
        self.assertIn("Restituire prodotto", html)
        self.assertIn(
            "Scansiona il prodotto e registra l'emissione dal magazzino.",
            html,
        )
        self.assertIn(
            "Scansiona il prodotto e registra la restituzione al magazzino.",
            html,
        )
        self.assertNotIn("Взяти товар", html)
        self.assertNotIn("Повернути товар", html)
        self.assertNotIn("Зіскануйте товар", html)

    def test_polish_storekeeper_self_service_smoke(self):
        response = self.dashboard_for(self.storekeeper, "/pl/")
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("Magazyn samoobsługowy", html)
        self.assertIn("Pobierz towar", html)
        self.assertIn("Zwróć towar", html)
        self.assertNotIn("Взяти товар", html)
        self.assertNotIn("Повернути товар", html)

    def test_polish_stock_receive_and_return_pages_show_distinct_labels(self):
        receive_response = self.dashboard_for(self.admin, "/pl/stock/receive/")
        return_response = self.dashboard_for(self.admin, "/pl/stock/return/")

        self.assertEqual(receive_response.status_code, 200)
        self.assertEqual(return_response.status_code, 200)
        self.assertContains(receive_response, "Przyjęcie towaru")
        self.assertContains(return_response, "Zwrot towaru")
        self.assertNotContains(receive_response, "Zwrot towaru")

    def test_ukrainian_dashboard_uses_only_ukrainian_navigation_terms(self):
        response = self.dashboard_for(self.admin, "/uk/")
        html = response.content.decode()

        for phrase in [
            "Головна",
            "Операції складу",
            "Прихід товару",
            "Видача товару",
            "Переміщення товару",
            "Списання товару",
            "Початкові залишки",
            "Інвентаризація",
            "Залишки на складі",
            "Журнал операцій",
        ]:
            self.assertIn(phrase, html)
        for phrase in [
            "Warehouse operations",
            "Stock receipt",
            "Stock issue",
            "Initial balances",
            "Stock transfer",
            "Stock write-off",
            "Operation journal",
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
            "Operation journal",
            "Open",
        ]:
            self.assertIn(phrase, html)
        for phrase in [
            "Головна",
            "Операції складу",
            "Прихід товару",
            "Видача товару",
            "Початкові залишки",
            "Переміщення товару",
            "Списання товару",
            "Журнал операцій",
            "Відкрити",
        ]:
            self.assertNotIn(phrase, html)

    def test_english_core_pages_do_not_show_ukrainian_menu_words(self):
        forbidden_phrases = [
            "Головна",
            "Навігація",
            "Операції складу",
            "Прихід товару",
            "Видача товару",
            "Початкові залишки",
            "Переміщення товару",
            "Списання товару",
            "Залишки на складі",
            "Журнал операцій",
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
        self.assertIn("Warehouse management", html)
        self.assertIn("Directories", html)
        self.assertIn("Users and roles", html)
        self.assertIn("Warehouse settings", html)
        for phrase in [
            "Керування складом",
            "Керуйте довідниками",
            "Довідники",
            "Товари / матеріали",
            "Склади",
            "Локації",
            "Користувачі та ролі",
            "Налаштування складу",
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
        self.assertIn('/uk/stock/return/', main_html)
        self.assertNotIn('id="storekeeper-item-search"', main_html)
        self.assertNotIn("autofocus", main_html)

    def test_english_dashboard_has_no_new_ukrainian_phrases_and_keeps_yantos_brand(self):
        response = self.dashboard_for(self.admin, "/en/")
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("YANTOS", html)
        self.assertIn("Warehouse operations", html)
        for phrase in [
            "Операції складу",
            "Прихід товару",
            "Видача товару",
            "Початкові залишки",
            "Переміщення товару",
            "Списання товару",
            "Керування",
        ]:
            self.assertNotIn(phrase, html)
