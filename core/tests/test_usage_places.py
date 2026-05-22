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

    def test_seed_data_contains_wire_drawing_shop_and_tp_506(self):
        migration = importlib.import_module("core.migrations.0011_seed_usage_places")

        self.assertIn("Цех волочіння", migration.USAGE_PLACE_NAMES)
        self.assertIn("ТП-506", migration.USAGE_PLACE_NAMES)

    def test_seed_data_does_not_contain_protozhka_or_wire_drawing_stand(self):
        migration = importlib.import_module("core.migrations.0011_seed_usage_places")

        self.assertNotIn("Протяжка", migration.USAGE_PLACE_NAMES)
        self.assertNotIn("Стан волочіння", migration.USAGE_PLACE_NAMES)

    def test_update_usage_places_migration_renames_protozhka_when_tp_506_missing(self):
        migration = importlib.import_module(
            "core.migrations.0013_update_usage_places_tp506"
        )
        UsagePlace.objects.filter(name="ТП-506").delete()
        protozhka = UsagePlace.objects.create(name="Протяжка", is_active=True)
        UsagePlace.objects.update_or_create(
            name="Стан волочіння", defaults={"is_active": True}
        )
        wire_drawing_shop = UsagePlace.objects.get(name="Цех волочіння")
        wire_drawing_shop.is_active = False
        wire_drawing_shop.save(update_fields=["is_active"])

        migration.update_usage_places(apps, None)

        protozhka.refresh_from_db()
        wire_drawing_shop.refresh_from_db()
        self.assertEqual(protozhka.name, "ТП-506")
        self.assertTrue(protozhka.is_active)
        self.assertEqual(UsagePlace.objects.filter(name="ТП-506").count(), 1)
        self.assertFalse(UsagePlace.objects.get(name="Стан волочіння").is_active)
        self.assertTrue(wire_drawing_shop.is_active)

    def test_update_usage_places_migration_archives_protozhka_when_tp_506_exists(self):
        migration = importlib.import_module(
            "core.migrations.0013_update_usage_places_tp506"
        )
        tp_506 = UsagePlace.objects.get(name="ТП-506")
        tp_506.is_active = True
        tp_506.save(update_fields=["is_active"])
        protozhka = UsagePlace.objects.create(name="Протяжка", is_active=True)
        UsagePlace.objects.update_or_create(
            name="Стан волочіння", defaults={"is_active": True}
        )
        wire_drawing_shop = UsagePlace.objects.get(name="Цех волочіння")
        wire_drawing_shop.is_active = True
        wire_drawing_shop.save(update_fields=["is_active"])

        migration.update_usage_places(apps, None)

        tp_506.refresh_from_db()
        protozhka.refresh_from_db()
        wire_drawing_shop.refresh_from_db()
        self.assertTrue(tp_506.is_active)
        self.assertFalse(protozhka.is_active)
        self.assertEqual(protozhka.name, "Протяжка")
        self.assertEqual(UsagePlace.objects.filter(name="ТП-506").count(), 1)
        self.assertFalse(UsagePlace.objects.get(name="Стан волочіння").is_active)
        self.assertTrue(wire_drawing_shop.is_active)
