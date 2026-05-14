from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase


class TabletLoginScreenTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        call_command("compilemessages", stdout=StringIO(), verbosity=0)

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="tablet-user",
            password="correct-password",
        )

    def test_ukrainian_login_page_is_tablet_friendly(self):
        response = self.client.get("/uk/accounts/login/?next=/uk/self-service/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "YANTOS · Складський облік")
        self.assertContains(response, "Вхід до складського термінала")
        self.assertContains(response, 'name="username"')
        self.assertContains(response, 'class="form-control form-control-lg')
        self.assertContains(response, 'autocomplete="username"')
        self.assertContains(response, 'name="password"')
        self.assertContains(response, 'autocomplete="current-password"')
        self.assertContains(response, 'class="btn btn-primary btn-lg w-100"')
        self.assertContains(response, 'type="hidden"')
        self.assertContains(response, 'name="next"')
        self.assertContains(response, 'value="/uk/self-service/"')
        self.assertNotContains(response, "sidebar-link")
        self.assertNotContains(response, "Адміністрування")
        self.assertNotContains(response, "admin/")

    def test_successful_login_preserves_next_redirect(self):
        response = self.client.post(
            "/uk/accounts/login/",
            {
                "username": "tablet-user",
                "password": "correct-password",
                "next": "/uk/",
            },
        )

        self.assertRedirects(response, "/uk/", fetch_redirect_response=False)

    def test_invalid_login_shows_alert(self):
        response = self.client.post(
            "/uk/accounts/login/",
            {"username": "tablet-user", "password": "wrong-password"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="alert alert-danger"')

    def test_english_login_page_uses_english_copy_only(self):
        response = self.client.get("/en/accounts/login/")

        self.assertContains(response, "YANTOS · Warehouse accounting")
        self.assertContains(response, "Warehouse terminal sign in")
        self.assertContains(response, "Username")
        self.assertContains(response, "Password")
        self.assertContains(response, "Sign in")
        self.assertNotContains(response, "Вхід до складського термінала")
        self.assertNotContains(response, "Ім’я користувача")
        self.assertNotContains(response, "Пароль")
        self.assertNotContains(response, "Увійти")

    def test_ukrainian_login_page_uses_ukrainian_copy(self):
        response = self.client.get("/uk/accounts/login/")

        self.assertContains(response, "YANTOS · Складський облік")
        self.assertContains(response, "Вхід до складського термінала")
        self.assertContains(response, "Ім’я користувача")
        self.assertContains(response, "Пароль")
        self.assertContains(response, "Увійти")
