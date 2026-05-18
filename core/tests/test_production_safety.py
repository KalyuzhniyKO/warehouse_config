import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

from django.db import IntegrityError
from django.test import TestCase

from core.models import BarcodeRegistry, BarcodeSequence, SystemSettings
from core.services.barcodes import BarcodeGenerationError, generate_barcode


class SettingsSafetyTests(TestCase):
    def run_settings_subprocess(self, code, extra_env=None, unset_env=()):
        project_root = Path(__file__).resolve().parents[2]
        env = os.environ.copy()
        for name in unset_env:
            env.pop(name, None)
        if extra_env:
            env.update(extra_env)
        env["PYTHONPATH"] = str(project_root)

        return subprocess.run(
            [sys.executable, "-c", code],
            cwd=project_root,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_django_debug_defaults_to_false_without_env_var(self):
        result = self.run_settings_subprocess(
            (
                "import os, dotenv; "
                "dotenv.load_dotenv = lambda *args, **kwargs: None; "
                "os.environ.pop('DJANGO_DEBUG', None); "
                "import config.settings; "
                "print(config.settings.DEBUG)"
            ),
            unset_env=("DJANGO_DEBUG",),
        )

        self.assertEqual(result.stdout.strip(), "False")

    def test_security_flags_can_be_enabled_from_env(self):
        result = self.run_settings_subprocess(
            (
                "import dotenv; "
                "dotenv.load_dotenv = lambda *args, **kwargs: None; "
                "import config.settings; "
                "print(config.settings.SESSION_COOKIE_SECURE); "
                "print(config.settings.CSRF_COOKIE_SECURE); "
                "print(config.settings.SECURE_SSL_REDIRECT)"
            ),
            extra_env={
                "DJANGO_SESSION_COOKIE_SECURE": "True",
                "DJANGO_CSRF_COOKIE_SECURE": "True",
                "DJANGO_SECURE_SSL_REDIRECT": "True",
            },
        )

        self.assertEqual(result.stdout.splitlines(), ["True", "True", "True"])

    def test_database_conn_max_age_reads_from_env(self):
        result = self.run_settings_subprocess(
            (
                "import dotenv; "
                "dotenv.load_dotenv = lambda *args, **kwargs: None; "
                "import config.settings; "
                "print(config.settings.DATABASES['default']['CONN_MAX_AGE'])"
            ),
            extra_env={"DJANGO_DB_CONN_MAX_AGE": "60"},
        )

        self.assertEqual(result.stdout.strip(), "60")


class BarcodeGenerationSafetyTests(TestCase):
    def test_generate_barcode_raises_clear_error_after_max_attempts(self):
        BarcodeSequence.objects.create(
            prefix=BarcodeRegistry.Prefix.ITEM,
            next_number=1,
        )
        BarcodeRegistry.objects.create(
            prefix=BarcodeRegistry.Prefix.ITEM,
            barcode="ITM0000000001",
        )
        BarcodeRegistry.objects.create(
            prefix=BarcodeRegistry.Prefix.ITEM,
            barcode="ITM0000000002",
        )

        with self.assertRaisesMessage(
            BarcodeGenerationError,
            "Unable to generate a unique barcode for prefix 'ITM' after 2 attempts.",
        ):
            generate_barcode(BarcodeRegistry.Prefix.ITEM, max_attempts=2)

    def test_generate_barcode_keeps_existing_format_after_collisions(self):
        BarcodeSequence.objects.create(
            prefix=BarcodeRegistry.Prefix.WAREHOUSE,
            next_number=1,
        )
        BarcodeRegistry.objects.create(
            prefix=BarcodeRegistry.Prefix.WAREHOUSE,
            barcode="WH0000000001",
        )

        barcode = generate_barcode(BarcodeRegistry.Prefix.WAREHOUSE, max_attempts=2)

        self.assertEqual(barcode, "WH0000000002")


class SystemSettingsSoloTests(TestCase):
    def test_get_solo_creates_instance_when_missing(self):
        settings = SystemSettings.get_solo()

        self.assertIsInstance(settings, SystemSettings)
        self.assertTrue(settings.use_locations)
        self.assertEqual(SystemSettings.objects.count(), 1)

    def test_get_solo_returns_existing_instance(self):
        existing = SystemSettings.objects.create(use_locations=False)

        settings = SystemSettings.get_solo()

        self.assertEqual(settings, existing)
        self.assertFalse(settings.use_locations)
        self.assertEqual(SystemSettings.objects.count(), 1)

    def test_get_solo_repeated_calls_do_not_create_duplicates(self):
        first = SystemSettings.get_solo()
        second = SystemSettings.get_solo()

        self.assertEqual(first, second)
        self.assertEqual(SystemSettings.objects.count(), 1)

    def test_get_solo_returns_concurrent_instance_after_integrity_error(self):
        original_create = SystemSettings.objects.create

        def create_concurrent_instance(*args, **kwargs):
            original_create(use_locations=False)
            raise IntegrityError("duplicate singleton")

        with mock.patch.object(
            SystemSettings.objects,
            "create",
            side_effect=create_concurrent_instance,
        ):
            settings = SystemSettings.get_solo()

        self.assertIsInstance(settings, SystemSettings)
        self.assertFalse(settings.use_locations)
        self.assertEqual(SystemSettings.objects.count(), 1)
