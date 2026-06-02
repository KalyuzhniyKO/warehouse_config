from io import StringIO

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import translation

from ..models import Warehouse
from .warehouse_access_utils import grant_warehouse_access


class DashboardLocalizationTests(TestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        call_command("compilemessages", verbosity=0)

    def setUp(self):
        call_command("init_roles", stdout=StringIO())
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="dash-admin",
            password="pw",
            first_name="Тарас",
            last_name="Технолог",
        )
        self.admin.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.storekeeper = User.objects.create_user(
            username="dash-storekeeper", password="pw"
        )
        self.storekeeper.groups.add(Group.objects.get(name="Комірник"))
        self.auditor = User.objects.create_user(username="dash-auditor", password="pw")
        self.auditor.groups.add(Group.objects.get(name="Перегляд / аудитор"))
        self.warehouse = Warehouse.objects.create(name="Dashboard warehouse")
        grant_warehouse_access(self.admin, self.warehouse, can_delegate=True)
        grant_warehouse_access(self.storekeeper, self.warehouse)
        grant_warehouse_access(self.auditor, self.warehouse)

    def dashboard_for(self, user, path=None):
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
        self.assertIn("Тарас Технолог", html)
        self.assertNotIn(">dash-admin<", html)
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

    def test_language_switcher_lists_all_configured_languages_in_navbar(self):
        from django.conf import settings

        response = self.dashboard_for(self.admin, "/uk/")
        html = response.content.decode()

        for language_code, language_name in settings.LANGUAGES:
            with self.subTest(language=language_name):
                self.assertIn(f'value="{language_code}"', html)
        navbar_actions = html[html.index('href="/uk/management/analytics/"'):html.index('<button class="btn user-menu-toggle')]
        self.assertIn('language-switcher', navbar_actions)
        dropdown_start = html.index('<div class="dropdown-menu dropdown-menu-end shadow user-menu-dropdown">')
        dropdown_html = html[dropdown_start:html.index('text-danger', dropdown_start)]
        self.assertNotIn('language-switcher', dropdown_html)

    def test_admin_navbar_places_analytics_before_language_switcher(self):
        response = self.dashboard_for(self.admin, "/uk/")
        html = response.content.decode()

        analytics_index = html.index('href="/uk/management/analytics/"')
        language_index = html.index('<div class="dropdown language-switcher">')
        user_index = html.index('<button class="btn user-menu-toggle')
        self.assertLess(analytics_index, language_index)
        self.assertLess(language_index, user_index)
        self.assertIn('href="/uk/management/analytics/"', html)
        self.assertIn('Аналітика', html)

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
        with translation.override("ru"):
            response = self.dashboard_for(self.storekeeper, "/ru/")
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("Склад самообслуживания", html)
        self.assertIn("Взять товар", html)
        self.assertIn("Вернуть товар", html)
        self.assertNotIn("Взяти товар", html)
        self.assertNotIn("Повернути товар", html)

    def test_italian_storekeeper_self_service_smoke(self):
        with translation.override("it"):
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
        with translation.override("pl"):
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
            "Часті операції",
            "Прихід товару",
            "Видача товару",
            "Переміщення товару",
            "Списання товару",
            "Контроль",
            "Інвентаризація",
            "Залишки на складі",
            "Журнал операцій",
        ]:
            self.assertIn(phrase, html)
        for phrase in [
            "Quick warehouse actions",
            "Stock receipt",
            "Stock issue",
            "Initial balances",
            "Stock transfer",
            "Stock write-off",
            "Operation journal",
        ]:
            self.assertNotIn(phrase, html)

    def test_english_dashboard_uses_only_english_navigation_terms(self):
        response = self.dashboard_for(self.admin, "/en/")
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("YANTOS", html)
        for phrase in [
            "Home",
            "Frequent operations",
            "Stock receipt",
            "Stock issue",
            "Stock transfer",
            "Stock write-off",
            "Control",
            "Inventory count",
            "Stock balances",
            "Operation journal",
        ]:
            self.assertIn(phrase, html)
        main_html = html[html.index('<main'):]
        for phrase in [
            "Головна",
            "Швидкі складські операції",
            "Прихід товару",
            "Видача товару",
            "Початкові залишки",
            "Переміщення товару",
            "Списання товару",
            "Журнал операцій",
        ]:
            self.assertNotIn(phrase, main_html)

    def test_english_core_pages_do_not_show_ukrainian_menu_words(self):
        forbidden_phrases = [
            "Головна",
            "Навігація",
            "Швидкі складські операції",
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
        self.assertIn("Frequent operations", html)
        for phrase in [
            "Швидкі складські операції",
            "Прихід товару",
            "Видача товару",
            "Початкові залишки",
            "Переміщення товару",
            "Списання товару",
            "Керування",
        ]:
            self.assertNotIn(phrase, html)
