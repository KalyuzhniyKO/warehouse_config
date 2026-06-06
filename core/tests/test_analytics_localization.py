from core.tests.analytics_test_utils import AnalyticsInterfaceTestBase
from core.tests.i18n_test_utils import compile_test_messages


class AnalyticsLocalizationTests(AnalyticsInterfaceTestBase):
    @classmethod
    def setUpClass(cls):
        compile_test_messages(["uk", "en", "ru", "it", "pl"])
        super().setUpClass()

    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def test_english_analytics_page_is_consistently_localized(self):
        response = self.client.get("/en/management/analytics/")

        self.assertEqual(response.status_code, 200)
        for text in [
            "Warehouse analytics",
            "Filters",
            "Update",
            "Reset",
            "Advanced filters",
            "Data quality",
            "Ready reports",
            "30 days",
        ]:
            self.assertContains(response, text)
        for text in [
            "Аналітика складу",
            "Фільтри",
            "Оновити",
            "Контроль даних",
            "Розширені фільтри",
            "30 днів",
            "7 днів",
        ]:
            self.assertNotContains(response, text)

    def test_ukrainian_analytics_page_is_consistently_localized(self):
        response = self.client.get("/uk/management/analytics/")

        self.assertEqual(response.status_code, 200)
        for text in [
            "Аналітика складу",
            "Фільтри",
            "Оновити",
            "Скинути",
            "Контроль даних",
        ]:
            self.assertContains(response, text)
        self.assertNotContains(response, "Сбросить")

    def test_russian_analytics_page_is_consistently_localized(self):
        response = self.client.get("/ru/management/analytics/")

        self.assertEqual(response.status_code, 200)
        for text in [
            "Аналитика склада",
            "Фильтры",
            "Обновить",
            "Сбросить",
            "Контроль данных",
            "Готовые отчёты",
        ]:
            self.assertContains(response, text)

    def test_italian_and_polish_analytics_pages_use_their_locales(self):
        expected = {
            "it": ["Analisi magazzino", "Filtri", "Aggiorna", "Reimposta", "Qualità dei dati"],
            "pl": ["Analityka magazynu", "Filtry", "Odśwież", "Resetuj", "Jakość danych"],
        }

        for language, texts in expected.items():
            with self.subTest(language=language):
                response = self.client.get(f"/{language}/management/analytics/")
                self.assertEqual(response.status_code, 200)
                for text in texts:
                    self.assertContains(response, text)
                self.assertNotContains(response, "Аналітика складу")
                self.assertNotContains(response, "Контроль даних")
