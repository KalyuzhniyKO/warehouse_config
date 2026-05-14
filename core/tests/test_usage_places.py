import importlib

from django.apps import apps
from django.test import TestCase

from core.models import UsagePlace


class UsagePlaceTests(TestCase):
    def test_usage_place_can_be_created(self):
        usage_place = UsagePlace.objects.create(name="Тестовий цех")

        self.assertEqual(usage_place.name, "Тестовий цех")
        self.assertTrue(usage_place.is_active)
        self.assertEqual(usage_place.note, "")

    def test_str_returns_name(self):
        usage_place = UsagePlace.objects.create(name="Лінія тестування")

        self.assertEqual(str(usage_place), "Лінія тестування")

    def test_seed_data_contains_other_usage_place(self):
        self.assertTrue(UsagePlace.objects.filter(name="Інше").exists())

    def test_seed_data_does_not_contain_service_usage_place(self):
        self.assertFalse(UsagePlace.objects.filter(name="Сервіс").exists())

    def test_seed_data_migration_is_idempotent(self):
        migration = importlib.import_module("core.migrations.0011_seed_usage_places")

        migration.seed_usage_places(apps, None)
        migration.seed_usage_places(apps, None)

        for name in migration.USAGE_PLACE_NAMES:
            self.assertEqual(UsagePlace.objects.filter(name=name).count(), 1)
