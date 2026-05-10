from decimal import Decimal
from pathlib import Path
from unittest import mock
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone
from io import BytesIO, StringIO
from django.urls import reverse
from ..forms import CategoryForm, ItemForm, LocationForm, StockBalanceFilterForm, StockTransferForm
from ..models import (
    BarcodeRegistry,
    BarcodeSequence,
    Category,
    InventoryCount,
    InventoryCountLine,
    Item,
    LabelTemplate,
    Location,
    PrintJob,
    Printer,
    Recipient,
    StockBalance,
    StockMovement,
    Unit,
    Warehouse,
)


class LabelAndBarcodeTests(TestCase):

    def setUp(self):
        call_command("init_roles", stdout=StringIO())
        self.user = get_user_model().objects.create_user("workflow", password="pass")
        self.user.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.client.force_login(self.user)
        self.unit = Unit.objects.create(name="Штука workflow", symbol="wf")
        self.item = Item.objects.create(name="Workflow item", unit=self.unit)
        self.warehouse = Warehouse.objects.create(name="Workflow warehouse")
        self.location = Location.objects.create(
            warehouse=self.warehouse, name="Workflow location"
        )
        self.destination_warehouse = Warehouse.objects.create(name="Workflow destination")
        self.destination_location = Location.objects.create(
            warehouse=self.destination_warehouse, name="Workflow destination location"
        )

    def test_item_without_barcode_gets_itm_barcode(self):
        self.assertTrue(self.item.barcode.barcode.startswith("ITM"))
        self.assertEqual(len(self.item.barcode.barcode), 13)

    def test_warehouse_without_barcode_gets_wh_barcode(self):
        self.assertTrue(self.warehouse.barcode.barcode.startswith("WH"))
        self.assertEqual(len(self.warehouse.barcode.barcode), 12)

    def test_location_types_get_loc_and_rck_barcodes(self):
        rack = Location.objects.create(
            warehouse=self.warehouse,
            name="Workflow rack",
            location_type=Location.LocationType.RACK,
        )
        self.assertTrue(self.location.barcode.barcode.startswith("LOC"))
        self.assertTrue(rack.barcode.barcode.startswith("RCK"))

    def test_pdf_label_generates(self):
        from ..services.labels import generate_item_label_pdf

        pdf = generate_item_label_pdf(self.item)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 1000)
        self.assertEqual(self.item.barcode.barcode, "ITM0000000001")

    def test_pdf_label_generates_with_cyrillic_name(self):
        from unittest.mock import patch

        from ..services import labels

        regular_path, _bold_path = labels._discover_label_ttf_fonts()
        if not regular_path:
            self.skipTest("Unicode TTF font is not available in this environment")

        self.item.name = "Кінцевий вимикач"
        self.item.save(update_fields=["name"])

        with patch(
            "core.services.labels._fallback_pdf",
            side_effect=AssertionError("fallback must not be used"),
        ):
            pdf = labels.generate_item_label_pdf(self.item)

        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 1000)
        self.assertEqual(
            labels._get_label_font_names(needs_unicode=True),
            ("WarehouseSans", "WarehouseSansBold"),
        )

    def test_printer_labeltemplate_and_printjob_can_be_created(self):
        printer = Printer.objects.create(name="Test printer", system_name="TEST_PRINTER")
        template = LabelTemplate.objects.create(name="58x40", is_default=True)
        job = PrintJob.objects.create(
            printer=printer,
            item=self.item,
            barcode=self.item.barcode.barcode,
            label_template=template,
            copies=1,
            user=self.user,
        )
        self.assertEqual(job.status, PrintJob.Status.PENDING)

    def test_lp_error_does_not_break_print_page(self):
        from unittest.mock import patch

        printer = Printer.objects.create(name="Broken printer", system_name="BROKEN", is_default=True)
        LabelTemplate.objects.create(name="Default label", is_default=True)

        class Result:
            returncode = 1
            stdout = ""
            stderr = "lp failed"

        with patch("core.services.labels.subprocess.run", return_value=Result()):
            response = self.client.post(
                reverse("item_label_print", args=[self.item.pk]),
                {"printer": printer.pk, "label_template": LabelTemplate.objects.get().pk, "copies": 1},
            )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(PrintJob.objects.filter(status=PrintJob.Status.FAILED).exists())

    def test_barcode_lookup_finds_item(self):
        response = self.client.get(
            reverse("barcode_lookup"), {"barcode": self.item.barcode.barcode}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "found": True,
                "type": "item",
                "id": self.item.pk,
                "name": self.item.name,
                "internal_code": self.item.internal_code or "",
                "barcode": self.item.barcode.barcode,
            },
        )

    def test_barcode_lookup_finds_warehouse(self):
        response = self.client.get(
            reverse("barcode_lookup"), {"barcode": self.warehouse.barcode.barcode}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "found": True,
                "type": "warehouse",
                "id": self.warehouse.pk,
                "name": self.warehouse.name,
                "barcode": self.warehouse.barcode.barcode,
            },
        )

    def test_barcode_lookup_finds_location(self):
        response = self.client.get(
            reverse("barcode_lookup"), {"barcode": self.location.barcode.barcode}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "found": True,
                "type": "location",
                "id": self.location.pk,
                "name": self.location.name,
                "warehouse_id": self.warehouse.pk,
                "warehouse_name": self.warehouse.name,
                "barcode": self.location.barcode.barcode,
            },
        )

    def test_barcode_lookup_returns_not_found_for_unknown_barcode(self):
        response = self.client.get(reverse("barcode_lookup"), {"barcode": "UNKNOWN"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"found": False, "message": "Штрихкод не знайдено."},
        )

    def test_anonymous_user_cannot_access_barcode_lookup(self):
        self.client.logout()

        response = self.client.get(
            reverse("barcode_lookup"), {"barcode": self.item.barcode.barcode}
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])
