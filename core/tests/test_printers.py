from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.utils import translation
from django.urls import reverse

from core.forms import PrinterForm
from core.models import Item, LabelTemplate, PrintJob, Printer, Unit
from core.services.labels import print_item_label
from core.services.printers import (
    get_default_system_printer,
    list_system_printers,
    print_test_page,
    sync_system_printers_to_db,
)


class CommandResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TempFile:
    def __init__(self, name="/tmp/warehouse-test-print.pdf"):
        self.name = name
        self.written = b""

    def write(self, data):
        self.written += data


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

    @mock.patch("core.services.printers.subprocess.run")
    def test_list_system_printers_returns_empty_for_no_destinations(self, run):
        run.return_value = CommandResult(
            returncode=1,
            stderr="lpstat: No destinations added.\n",
        )

        self.assertEqual(list_system_printers(), [])

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


class PrintTestPageTests(TestCase):
    def setUp(self):
        self.printer = Printer.objects.create(name="Zebra", system_name="Zebra_ZD421")

    @mock.patch("core.services.printers.os.path.exists", return_value=False)
    @mock.patch("core.services.printers.tempfile.NamedTemporaryFile")
    @mock.patch("core.services.printers.check_printer_exists", return_value=True)
    @mock.patch("core.services.printers.subprocess.run")
    def test_print_test_page_creates_pdf_and_invokes_lp_without_shell(
        self, run, _exists, named_temporary_file, _path_exists
    ):
        temp_file = TempFile()
        named_temporary_file.return_value.__enter__.return_value = temp_file
        run.return_value = CommandResult(returncode=0, stdout="request id is Zebra-2")

        result = print_test_page(self.printer)

        self.assertTrue(result["success"])
        named_temporary_file.assert_called_once_with(delete=False, suffix=".pdf")
        self.assertTrue(temp_file.written.startswith(b"%PDF"))
        args, kwargs = run.call_args
        self.assertEqual(args[0], ["lp", "-d", self.printer.system_name, temp_file.name])
        self.assertNotIn("shell", kwargs)


class PrinterViewTests(TestCase):
    def setUp(self):
        self.language_override = translation.override("uk")
        self.language_override.__enter__()
        call_command("init_roles", stdout=StringIO())
        User = get_user_model()
        self.admin = User.objects.create_user(username="printer-admin", password="pw")
        self.admin.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.storekeeper = User.objects.create_user(username="printer-keeper", password="pw")
        self.storekeeper.groups.add(Group.objects.get(name="Комірник"))
        self.printer = Printer.objects.create(name="Zebra", system_name="Zebra_ZD421")

    def tearDown(self):
        self.language_override.__exit__(None, None, None)
        super().tearDown()

    @mock.patch("core.views.labels.get_default_system_printer", return_value="Zebra_ZD421")
    @mock.patch(
        "core.views.labels.list_system_printers",
        return_value=[{"system_name": "Zebra_ZD421", "name": "Zebra_ZD421", "raw": "device for Zebra_ZD421: usb://Zebra"}],
    )
    def test_printer_list_page_has_sync_edit_and_test_print_actions(self, _list, _default):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("printer_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "name=\"language\" type=\"hidden\" value=\"uk\"", html=False)
        self.assertContains(response, "<h1", count=1)
        self.assertContains(response, "<table", count=2)
        self.assertContains(response, "table-action", count=2)
        self.assertContains(response, reverse("printer_sync"))
        self.assertContains(response, reverse("printer_update", args=[self.printer.pk]))
        self.assertContains(response, reverse("printer_test_print", args=[self.printer.pk]))
        self.assertNotContains(response, reverse("labeltemplate_update", args=[self.printer.pk]))
        self.assertNotContains(response, reverse("item_create"))

    @mock.patch("core.views.labels.get_default_system_printer", return_value=None)
    @mock.patch("core.views.labels.list_system_printers", return_value=[])
    def test_printer_list_page_shows_empty_cups_warning_without_error(self, _list, _default):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("printer_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "У CUPS не додано жодного принтера. Додайте принтер у CUPS, після цього натисніть «Оновити список принтерів».",
        )

    @mock.patch("core.forms.labels.list_system_printers", side_effect=Exception("dev CUPS down"))
    def test_printer_edit_page_available_only_to_settings_groups(self, _list):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("printer_update", args=[self.printer.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "name=\"language\" type=\"hidden\" value=\"uk\"", html=False)

        response = self.client.post(
            reverse("printer_update", args=[self.printer.pk]),
            {
                "name": "Label printer",
                "system_name": "ZEBRA_QUEUE",
                "description": "Main label printer",
                "is_default": "on",
                "is_active": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.printer.refresh_from_db()
        self.assertEqual(self.printer.name, "Label printer")
        self.assertEqual(self.printer.system_name, "ZEBRA_QUEUE")
        self.assertEqual(self.printer.description, "Main label printer")
        self.assertTrue(self.printer.is_default)
        self.assertTrue(self.printer.is_active)

        self.client.force_login(self.storekeeper)
        response = self.client.get(reverse("printer_update", args=[self.printer.pk]))
        self.assertEqual(response.status_code, 403)

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
