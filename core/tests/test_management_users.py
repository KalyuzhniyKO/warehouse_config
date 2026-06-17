from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.auth.password_validation import validate_password
from django.test import override_settings
from django.urls import reverse

from .management_test_utils import ManagementTestBase


class ManagementUserTests(ManagementTestBase):
    def test_warehouse_admin_sees_create_user_button(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("management_users"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Створити користувача")
        self.assertNotContains(response, "Створити в Django Admin")

    def test_warehouse_admin_can_open_user_create_page(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("management_user_create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Створити користувача")

    def test_superuser_management_users_page_renders(self):
        self.client.force_login(self.superuser)

        response = self.client.get(reverse("management_users"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Користувачі")
        self.assertContains(response, "Адміністратор")
        self.assertContains(response, "Користувач")

    def test_user_management_shows_business_roles_and_hides_root(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("management_users"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Адміністратор")
        self.assertContains(response, "Користувач")
        self.assertContains(response, "Керує складом і користувачами")
        self.assertContains(response, "Простий складський інтерфейс")
        self.assertNotContains(response, f"/management/users/{self.superuser.pk}/edit/")
        self.assertNotContains(response, "root@example.com")
        self.assertNotContains(response, ">root<")
        self.assertNotContains(response, "Superuser")
        self.assertNotContains(response, "Перегляд / аудитор")

    def test_user_create_form_uses_business_role_labels(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("management_user_create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Адміністратор")
        self.assertContains(response, "Користувач")
        self.assertNotContains(response, "Адміністратор складу")
        self.assertNotContains(response, "Комірник")
        self.assertNotContains(response, "Перегляд / аудитор")
        self.assertNotContains(response, 'name="is_staff"')
        self.assertNotContains(response, 'name="is_superuser"')

    def test_user_create_form_shows_explicit_access_permissions(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("management_user_create"))

        self.assertContains(response, "Права доступу")
        self.assertContains(response, "Може входити в складську систему")
        self.assertContains(response, "Може переглядати заявки на закупівлю")
        self.assertContains(response, "Може створювати заявки на закупівлю")
        self.assertContains(response, "Може погоджувати заявки на закупівлю")
        self.assertContains(response, "Може змінювати оплату та доставку заявок")

    def test_auditor_cannot_open_user_management_forms(self):
        self.client.force_login(self.auditor)
        target = self.storekeeper

        for url in [
            reverse("management_user_create"),
            reverse("management_user_update", args=[target.pk]),
            reverse("management_user_password", args=[target.pk]),
        ]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 403, url)

    def test_storekeeper_cannot_open_user_management_forms(self):
        self.client.force_login(self.storekeeper)
        target = self.auditor

        for url in [
            reverse("management_user_create"),
            reverse("management_user_update", args=[target.pk]),
            reverse("management_user_password", args=[target.pk]),
        ]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 403, url)

    def test_create_user_creates_user_and_adds_selected_group(self):
        self.client.force_login(self.admin)
        group = Group.objects.get(name="Комірник")
        approve_permission = Permission.objects.get(
            codename="can_approve_purchase_requests"
        )
        tracking_permission = Permission.objects.get(
            codename="can_update_purchase_request_tracking"
        )

        response = self.client.post(
            reverse("management_user_create"),
            {
                "username": "newkeeper",
                "first_name": "Новий",
                "last_name": "Комірник",
                "email": "newkeeper@example.com",
                "password1": "secret",
                "password2": "secret",
                "groups": [str(group.pk)],
                "access_permissions": [
                    str(approve_permission.pk),
                    str(tracking_permission.pk),
                ],
                "is_active": "on",
                "is_staff": "on",
                "is_superuser": "on",
            },
        )

        self.assertRedirects(response, reverse("management_users"))
        created = get_user_model().objects.get(username="newkeeper")
        self.assertTrue(created.check_password("secret"))
        self.assertTrue(created.groups.filter(name="Комірник").exists())
        self.assertTrue(created.has_perm("core.can_approve_purchase_requests"))
        self.assertTrue(created.has_perm("core.can_update_purchase_request_tracking"))
        self.assertFalse(created.is_staff)
        self.assertFalse(created.is_superuser)

    def test_create_password_mismatch_shows_error(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("management_user_create"),
            {
                "username": "badpass",
                "password1": "one",
                "password2": "two",
                "is_active": "on",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Паролі не співпадають")
        self.assertFalse(get_user_model().objects.filter(username="badpass").exists())

    def test_update_user_changes_profile_and_groups(self):
        self.client.force_login(self.admin)
        group = Group.objects.get(name="Адміністратор складу")
        view_permission = Permission.objects.get(codename="can_view_purchase_requests")

        response = self.client.post(
            reverse("management_user_update", args=[self.storekeeper.pk]),
            {
                "first_name": "Олена",
                "last_name": "Петренко",
                "email": "olena@example.com",
                "groups": [str(group.pk)],
                "access_permissions": [str(view_permission.pk)],
                "is_active": "on",
            },
        )

        self.assertRedirects(response, reverse("management_users"))
        self.storekeeper.refresh_from_db()
        self.assertEqual(self.storekeeper.email, "olena@example.com")
        self.assertEqual(self.storekeeper.first_name, "Олена")
        self.assertEqual(self.storekeeper.last_name, "Петренко")
        self.assertTrue(self.storekeeper.groups.filter(name="Адміністратор складу").exists())
        self.assertFalse(self.storekeeper.groups.filter(name="Комірник").exists())
        self.assertTrue(self.storekeeper.has_perm("core.can_view_purchase_requests"))

        response = self.client.post(
            reverse("management_user_update", args=[self.storekeeper.pk]),
            {
                "first_name": "Олена",
                "last_name": "Петренко",
                "email": "olena@example.com",
                "groups": [str(group.pk)],
                "is_active": "on",
            },
        )
        self.assertRedirects(response, reverse("management_users"))
        self.storekeeper.refresh_from_db()
        self.assertFalse(
            self.storekeeper.user_permissions.filter(
                codename="can_view_purchase_requests"
            ).exists()
        )

    def test_password_view_changes_password(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("management_user_password", args=[self.storekeeper.pk]),
            {"password1": "new-secret", "password2": "new-secret"},
        )

        self.assertRedirects(response, reverse("management_users"))
        self.storekeeper.refresh_from_db()
        self.assertTrue(self.storekeeper.check_password("new-secret"))

    def test_cannot_deactivate_self(self):
        self.client.force_login(self.admin)
        group = Group.objects.get(name="Адміністратор складу")

        response = self.client.post(
            reverse("management_user_update", args=[self.admin.pk]),
            {
                "first_name": self.admin.first_name,
                "last_name": self.admin.last_name,
                "email": self.admin.email,
                "groups": [str(group.pk)],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Не можна деактивувати самого себе")
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_warehouse_admin_cannot_edit_superuser_through_user_management_ui(self):
        self.client.force_login(self.admin)
        group = Group.objects.get(name="Комірник")

        response = self.client.post(
            reverse("management_user_update", args=[self.superuser.pk]),
            {
                "first_name": "Root",
                "last_name": "User",
                "email": "root2@example.com",
                "groups": [str(group.pk)],
                "is_active": "on",
            },
        )

        self.assertEqual(response.status_code, 404)
        self.superuser.refresh_from_db()
        self.assertFalse(self.superuser.groups.filter(name="Комірник").exists())
        self.assertTrue(self.superuser.is_superuser)
        self.assertTrue(self.superuser.is_staff)

    def test_english_management_users_page_uses_english_labels(self):
        self.client.force_login(self.admin)

        response = self.client.get("/en/management/users/")
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn('<html lang="en">', html)
        self.assertContains(response, '/en/management/users/create/')
        self.assertContains(response, '/en/management/users/1/edit/')
        self.assertContains(response, '/en/management/users/1/password/')
        self.assertContains(response, "Administrator")
        self.assertContains(response, "User")
        self.assertContains(response, "Manages warehouse and users")
        self.assertContains(response, "Simple warehouse interface")

    def test_init_roles_creates_expected_groups(self):
        for name in ["Адміністратор складу", "Комірник", "Перегляд / аудитор"]:
            self.assertTrue(Group.objects.filter(name=name).exists())

    @override_settings(AUTH_PASSWORD_VALIDATORS=[])
    def test_simple_passwords_are_not_blocked_when_validators_disabled(self):
        validate_password("1", user=self.storekeeper)
