from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from core.forms import PrinterForm
from core.models import Item, LabelTemplate, PrintJob, Printer, Unit
from core.services.labels import print_item_label
from core.services.printers import (
    get_default_system_printer,
    list_system_printers,
    sync_system_printers_to_db,
)


class CommandResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class CupsPrinterDiscoveryTests(TestCase):
    @mock.patch("core.services.printers.subprocess.run")
    def test_list_system_printers_parses_lpstat_output(self, run):
        run.return_value = CommandResult(
            stdout=(
                "device for Zebra_ZD421: usb://Zebra/ZD421\n"
                "device for Office_Printer: ipp://printer.local/ipp/print\n"
            )
        )

        printers = list_system_printers()

        self.assertEqual(
            printers,
            [
                {
                    "system_name": "Zebra_ZD421",
                    "name": "Zebra_ZD421",
                    "raw": "device for Zebra_ZD421: usb://Zebra/ZD421",
                },
                {
                    "system_name": "Office_Printer",
                    "name": "Office_Printer",
                    "raw": "device for Office_Printer: ipp://printer.local/ipp/print",
                },
            ],
        )
        run.assert_called_once_with(
            ["lpstat", "-v"], capture_output=True, text=True, check=False
        )

    @mock.patch("core.services.printers.subprocess.run")
    def test_get_default_system_printer_parses_lpstat_d(self, run):
        run.return_value = CommandResult(stdout="system default destination: Zebra_ZD421\n")

        self.assertEqual(get_default_system_printer(), "Zebra_ZD421")
        run.assert_called_once_with(
            ["lpstat", "-d"], capture_output=True, text=True, check=False
        )

    @mock.patch("core.services.printers.get_default_system_printer", return_value=None)
    @mock.patch(
        "core.services.printers.list_system_printers",
        return_value=[{"system_name": "Zebra_ZD421", "name": "Zebra_ZD421", "raw": ""}],
    )
    def test_sync_system_printers_to_db_creates_printer(self, _list, _default):
        result = sync_system_printers_to_db()

        printer = Printer.objects.get(system_name="Zebra_ZD421")
        self.assertEqual(printer.name, "Zebra_ZD421")
        self.assertTrue(printer.is_active)
        self.assertEqual(result["created"], 1)

    @mock.patch("core.services.printers.get_default_system_printer", return_value=None)
    @mock.patch(
        "core.services.printers.list_system_printers",
        return_value=[{"system_name": "Zebra_ZD421", "name": "Zebra_ZD421", "raw": ""}],
    )
    def test_sync_does_not_overwrite_existing_name_or_description(self, _list, _default):
        Printer.objects.create(
            name="Label printer",
            system_name="Zebra_ZD421",
            description="Manual description",
            is_active=False,
        )

        sync_system_printers_to_db()

        printer = Printer.objects.get(system_name="Zebra_ZD421")
        self.assertEqual(printer.name, "Label printer")
        self.assertEqual(printer.description, "Manual description")
        self.assertTrue(printer.is_active)

    @mock.patch("core.services.printers.get_default_system_printer", return_value="Zebra_ZD421")
    @mock.patch(
        "core.services.printers.list_system_printers",
        return_value=[
            {"system_name": "Zebra_ZD421", "name": "Zebra_ZD421", "raw": ""},
            {"system_name": "Office_Printer", "name": "Office_Printer", "raw": ""},
        ],
    )
    def test_sync_applies_cups_default_and_resets_other_defaults(self, _list, _default):
        Printer.objects.create(name="Old default", system_name="Office_Printer", is_default=True)

        sync_system_printers_to_db()

        self.assertTrue(Printer.objects.get(system_name="Zebra_ZD421").is_default)
        self.assertFalse(Printer.objects.get(system_name="Office_Printer").is_default)


class PrinterFormTests(TestCase):
    @mock.patch(
        "core.forms.labels.list_system_printers",
        return_value=[{"system_name": "Zebra_ZD421", "name": "Zebra_ZD421", "raw": ""}],
    )
    def test_clean_system_name_strips_and_validates_against_cups(self, _list):
        form = PrinterForm(
            data={
                "name": "Zebra",
                "system_name": "  Zebra_ZD421  ",
                "description": "",
                "is_active": "on",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["system_name"], "Zebra_ZD421")

    @mock.patch("core.forms.labels.list_system_printers", side_effect=Exception("dev CUPS down"))
    def test_clean_system_name_does_not_block_when_cups_unavailable(self, _list):
        form = PrinterForm(
            data={
                "name": "Manual",
                "system_name": "MANUAL_QUEUE",
                "description": "",
                "is_active": "on",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)


class PrintItemLabelCupsTests(TestCase):
    def setUp(self):
        self.unit = Unit.objects.create(name="Piece", symbol="pc")
        self.item = Item.objects.create(name="Cable", unit=self.unit)
        self.template = LabelTemplate.objects.create(name="58x40", is_default=True)
        self.printer = Printer.objects.create(name="Zebra", system_name="Zebra_ZD421")

    @mock.patch("core.services.labels.generate_item_label_pdf", return_value=b"%PDF-1.4")
    @mock.patch("core.services.labels.check_printer_exists", return_value=True)
    @mock.patch("core.services.labels.subprocess.run")
    def test_print_item_label_invokes_lp_with_selected_printer(self, run, _exists, _pdf):
        run.return_value = CommandResult(returncode=0, stdout="request id is Zebra-1")

        job = print_item_label(
            item=self.item,
            printer=self.printer,
            label_template=self.template,
            copies=2,
        )

        self.assertEqual(job.status, PrintJob.Status.PRINTED)
        args = run.call_args.args[0]
        self.assertEqual(args[:5], ["lp", "-d", self.printer.system_name, "-n", "2"])
        self.assertTrue(args[5].endswith(".pdf"))

    @mock.patch("core.services.labels.generate_item_label_pdf", return_value=b"%PDF-1.4")
    @mock.patch("core.services.labels.check_printer_exists", return_value=True)
    @mock.patch("core.services.labels.subprocess.run")
    def test_print_item_label_marks_failed_when_lp_returns_error(self, run, _exists, _pdf):
        run.return_value = CommandResult(returncode=1, stderr="lp failed")

        job = print_item_label(
            item=self.item,
            printer=self.printer,
            label_template=self.template,
            copies=1,
        )

        self.assertEqual(job.status, PrintJob.Status.FAILED)
        self.assertEqual(job.error_message, "lp failed")

    @mock.patch("core.services.labels.generate_item_label_pdf", return_value=b"%PDF-1.4")
    @mock.patch("core.services.labels.check_printer_exists", return_value=False)
    @mock.patch("core.services.labels.subprocess.run")
    def test_print_item_label_marks_failed_when_cups_printer_missing(self, run, _exists, _pdf):
        job = print_item_label(
            item=self.item,
            printer=self.printer,
            label_template=self.template,
            copies=1,
        )

        self.assertEqual(job.status, PrintJob.Status.FAILED)
        self.assertIn("не знайдено в CUPS", job.error_message)
        run.assert_not_called()


class PrinterViewTests(TestCase):
    def setUp(self):
        call_command("init_roles", stdout=StringIO())
        User = get_user_model()
        self.admin = User.objects.create_user(username="printer-admin", password="pw")
        self.admin.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.storekeeper = User.objects.create_user(username="printer-keeper", password="pw")
        self.storekeeper.groups.add(Group.objects.get(name="Комірник"))
        self.printer = Printer.objects.create(name="Zebra", system_name="Zebra_ZD421")

    @mock.patch("core.views.labels.get_default_system_printer", return_value="Zebra_ZD421")
    @mock.patch(
        "core.views.labels.list_system_printers",
        return_value=[{"system_name": "Zebra_ZD421", "name": "Zebra_ZD421", "raw": "device for Zebra_ZD421: usb://Zebra"}],
    )
    def test_printer_list_page_has_sync_button_and_test_print_action(self, _list, _default):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("printer_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Оновити список принтерів")
        self.assertContains(response, reverse("printer_sync"))
        self.assertContains(response, reverse("printer_test_print", args=[self.printer.pk]))
        self.assertContains(response, "Системні принтери сервера")

    @mock.patch(
        "core.views.labels.sync_system_printers_to_db",
        return_value={"created": 1, "updated": 0, "total": 1, "default_system_name": None},
    )
    def test_post_sync_available_only_to_settings_groups(self, sync):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("printer_sync"))
        self.assertEqual(response.status_code, 302)
        sync.assert_called_once()

        self.client.force_login(self.storekeeper)
        response = self.client.post(reverse("printer_sync"))
        self.assertEqual(response.status_code, 403)

    @mock.patch(
        "core.views.labels.print_test_page",
        return_value={"success": True, "message": "ok"},
    )
    def test_post_test_print_available_only_to_settings_groups(self, print_test):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("printer_test_print", args=[self.printer.pk]))
        self.assertEqual(response.status_code, 302)
        print_test.assert_called_once_with(self.printer)

        self.client.force_login(self.storekeeper)
        response = self.client.post(reverse("printer_test_print", args=[self.printer.pk]))
        self.assertEqual(response.status_code, 403)
