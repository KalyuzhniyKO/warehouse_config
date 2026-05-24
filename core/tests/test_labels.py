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


    def test_label_template_form_has_layout_fields(self):
        from core.forms.labels import LabelTemplateForm

        form = LabelTemplateForm()
        for field in [
            "margin_top_mm", "margin_right_mm", "margin_bottom_mm", "margin_left_mm",
            "item_name_font_size", "internal_code_font_size", "barcode_text_font_size",
            "barcode_height_mm", "barcode_bar_width_mm",
        ]:
            self.assertIn(field, form.fields)

    def test_label_template_preview_route_returns_pdf(self):
        template = LabelTemplate.objects.create(name="Preview", is_default=True)
        response = self.client.get(reverse("labeltemplate_preview", args=[template.pk]), {"item": self.item.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_label_template_list_has_edit_and_preview_links(self):
        template = LabelTemplate.objects.create(name="Preview", is_default=True)
        response = self.client.get(reverse("labeltemplate_list"))
        self.assertContains(response, reverse("labeltemplate_update", args=[template.pk]))
        self.assertContains(response, reverse("labeltemplate_preview", args=[template.pk]))

    def test_label_template_edit_available_only_for_settings_groups(self):
        template = LabelTemplate.objects.create(name="Edit me", is_default=True)
        response = self.client.get(reverse("labeltemplate_update", args=[template.pk]))
        self.assertEqual(response.status_code, 200)

        User = get_user_model()
        user = User.objects.create_user("print-only", password="pass")
        user.groups.add(Group.objects.get(name="Комірник"))
        self.client.force_login(user)
        response = self.client.get(reverse("labeltemplate_update", args=[template.pk]))
        self.assertEqual(response.status_code, 403)

    def test_label_template_create_uses_live_preview_template(self):
        response = self.client.get(reverse("labeltemplate_create"))
        self.assertTemplateUsed(response, "core/labeltemplate_form.html")
        self.assertContains(response, "label-template-editor")
        self.assertContains(response, "Попередній перегляд етикетки")
        self.assertContains(response, "Дріт оцинкований Ø3 мм")
        self.assertContains(response, "Код: YT-000001")
        self.assertContains(response, "data-preview-barcode")
        self.assertContains(response, "label-preview-panel")
        self.assertContains(response, "label-preview-sheet")
        self.assertContains(response, "label-preview-safe-area")
        self.assertContains(response, "label-preview-barcode")
        self.assertContains(response, "label-preview-size-badge")
        self.assertContains(response, "Основні параметри")
        self.assertContains(response, "Вміст етикетки")
        self.assertContains(response, "Відступи")
        self.assertContains(response, "Шрифти")
        self.assertContains(response, "Штрихкод")
        self.assertContains(response, "show_item_name")
        self.assertContains(response, "margin_top_mm")
        self.assertContains(response, "item_name_font_size")
        self.assertContains(response, "barcode_height_mm")
        self.assertContains(response, "PDF-перегляд")
        self.assertNotContains(response, "PDF preview")

    def test_label_template_update_uses_live_preview_template_and_pdf_link(self):
        template = LabelTemplate.objects.create(name="Edit me", is_default=True)
        response = self.client.get(reverse("labeltemplate_update", args=[template.pk]))
        self.assertTemplateUsed(response, "core/labeltemplate_form.html")
        self.assertContains(response, "label-template-editor")
        self.assertContains(response, reverse("labeltemplate_preview", args=[template.pk]))
        self.assertContains(response, "Відкрити PDF-перегляд")
        self.assertNotContains(response, "PDF preview")

    def test_item_label_print_page_has_preview_link(self):
        printer = Printer.objects.create(name="P", system_name="P1", is_default=True)
        template = LabelTemplate.objects.create(name="T", is_default=True)
        response = self.client.get(reverse("item_label_print", args=[self.item.pk]))
        self.assertContains(response, reverse("item_label_download", args=[self.item.pk]))
        self.assertContains(response, "Переглянути етикетку PDF")
