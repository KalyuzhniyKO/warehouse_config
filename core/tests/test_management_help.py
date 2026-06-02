from django.urls import reverse

from .management_test_utils import ManagementTestBase


class ManagementHelpTests(ManagementTestBase):
    def test_documentation_files_exist(self):
        from pathlib import Path

        docs = Path(__file__).resolve().parents[2] / "docs"
        for filename in [
            "USER_GUIDE.md",
            "ADMIN_GUIDE.md",
            "START_WAREHOUSE_FROM_ZERO.md",
        ]:
            self.assertTrue((docs / filename).exists())

    def test_management_help_page_shows_instruction_sections(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("management_help"))
        self.assertEqual(response.status_code, 200)
        for text in [
            "Як почати склад з нуля",
            "Інструкція користувача",
            "Інструкція адміністратора",
            "Типові помилки",
            "Backup і відновлення",
            "Принтери і друк етикеток",
            "Штрихкоди",
            "Прихід товару",
            "Початковий залишок",
            "Журнал операцій",
        ]:
            self.assertContains(response, text)

    def test_user_help_page_shows_only_user_instruction(self):
        self.client.force_login(self.storekeeper)
        response = self.client.get(reverse("help"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Інструкція користувача")
        self.assertNotContains(response, "Інструкція адміністратора")
        self.assertNotContains(response, "Backup і відновлення")

    def test_help_page_opens(self):
        self.client.force_login(self.auditor)
        response = self.client.get(reverse("help"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Центр допомоги")
