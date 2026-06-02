from django.test import RequestFactory, TestCase


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
