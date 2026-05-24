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
    LabelTemplateElement,
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
        self.assertContains(response, "label-designer-workspace")
        self.assertContains(response, "Попередній перегляд етикетки")
        self.assertContains(response, "Дріт оцинкований Ø3 мм")
        self.assertContains(response, "Код: YT-000001")
        self.assertContains(response, "data-preview-barcode")
        self.assertContains(response, "label-preview-sheet")
        self.assertContains(response, "label-preview-safe-area")
        self.assertContains(response, "label-preview-barcode")
        self.assertContains(response, "label-preview-size-badge")
        self.assertContains(response, "show_item_name")
        self.assertContains(response, "margin_top_mm")
        self.assertContains(response, "item_name_font_size")
        self.assertContains(response, "barcode_height_mm")
        self.assertNotContains(response, "PDF preview")

    def test_label_template_update_uses_live_preview_template_and_pdf_link(self):
        template = LabelTemplate.objects.create(name="Edit me", is_default=True)
        response = self.client.get(reverse("labeltemplate_update", args=[template.pk]))
        self.assertTemplateUsed(response, "core/labeltemplate_form.html")
        self.assertContains(response, "label-designer-workspace")
        self.assertContains(response, reverse("labeltemplate_preview", args=[template.pk]))
        self.assertContains(response, "PDF")
        self.assertNotContains(response, "PDF preview")


    def test_label_template_update_has_all_visible_fields_and_preview_hooks(self):
        template = LabelTemplate.objects.create(name="Usable", is_default=True)
        response = self.client.get(reverse("labeltemplate_update", args=[template.pk]))

        for label in [
            "Назва",
            "Ширина, мм",
            "Висота, мм",
            "Показувати назву товару",
            "Показувати внутрішній код",
            "Показувати текст штрихкоду",
            "Верхній відступ, мм",
            "Правий відступ, мм",
            "Нижній відступ, мм",
            "Лівий відступ, мм",
            "Розмір шрифту назви",
            "Розмір шрифту внутрішнього коду",
            "Розмір шрифту тексту штрихкоду",
            "Тип штрихкоду",
            "Висота штрихкоду, мм",
            "Товщина лінії штрихкоду, мм",
        ]:
            self.assertContains(response, label)

        for field_name in [
            "name", "width_mm", "height_mm", "show_item_name", "show_internal_code", "show_barcode_text",
            "margin_top_mm", "margin_right_mm", "margin_bottom_mm", "margin_left_mm",
            "item_name_font_size", "internal_code_font_size", "barcode_text_font_size",
            "barcode_type", "barcode_height_mm", "barcode_bar_width_mm",
        ]:
            self.assertContains(response, f'name="{field_name}"')

        self.assertContains(response, "data-label-preview-root")
        self.assertContains(response, "data-preview-sheet")
        self.assertContains(response, "data-preview-content")
        self.assertContains(response, "data-preview-barcode")
        self.assertContains(response, "label-designer-canvas-panel")
        self.assertContains(response, "label-designer-inspector")
        self.assertContains(response, "label-element-list")
        self.assertContains(response, "data-label-element=\"item_name\"")
        self.assertContains(response, "data-label-element=\"internal_code\"")
        self.assertContains(response, "data-label-element=\"barcode\"")
        self.assertContains(response, "data-label-element=\"barcode_text\"")
        self.assertContains(response, "data-grid-toggle")
        self.assertContains(response, "data-snap-toggle")
        self.assertContains(response, "data-reset-layout")
        self.assertContains(response, "data-element-form-row")
        self.assertContains(response, "data-selected-element-summary")
        self.assertContains(response, "data-element-warnings")
        self.assertContains(response, "data-warning-overflow")

    def test_label_template_defaults_elements_created(self):
        template = LabelTemplate.objects.create(name="T1", show_item_name=False, show_internal_code=True, show_barcode_text=False)
        # emulate migration behavior for runtime-created template
        from core.views.labels import LabelTemplateUpdateView
        LabelTemplateUpdateView._create_default_elements(template)
        self.assertEqual(template.elements.count(), 4)
        self.assertFalse(template.elements.get(element_type="item_name").is_visible)
        self.assertFalse(template.elements.get(element_type="barcode_text").is_visible)

    def test_label_template_element_coordinates_saved(self):
        template = LabelTemplate.objects.create(name="Coords")
        from core.views.labels import LabelTemplateUpdateView
        LabelTemplateUpdateView._create_default_elements(template)
        url = reverse("labeltemplate_update", args=[template.pk])
        payload = {
            "name": "Coords", "width_mm": 58, "height_mm": 40, "show_item_name": "on", "show_internal_code": "on", "show_barcode_text": "on",
            "barcode_type": "code128", "margin_top_mm": 3, "margin_right_mm": 3, "margin_bottom_mm": 3, "margin_left_mm": 3,
            "item_name_font_size": 8, "internal_code_font_size": 6, "barcode_text_font_size": 7, "barcode_height_mm": 16,
            "barcode_bar_width_mm": "0.33", "is_default": "", "is_active": "on",
            "elements-TOTAL_FORMS": "4", "elements-INITIAL_FORMS": "4", "elements-MIN_NUM_FORMS": "0", "elements-MAX_NUM_FORMS": "1000",
        }
        for idx, element in enumerate(template.elements.order_by("sort_order", "id")):
            payload[f"elements-{idx}-id"] = str(element.id)
            payload[f"elements-{idx}-element_type"] = element.element_type
            payload[f"elements-{idx}-label"] = ""
            payload[f"elements-{idx}-text"] = ""
            payload[f"elements-{idx}-x_mm"] = "11.50" if element.element_type == "item_name" else str(element.x_mm)
            payload[f"elements-{idx}-y_mm"] = str(element.y_mm)
            payload[f"elements-{idx}-width_mm"] = str(element.width_mm)
            payload[f"elements-{idx}-height_mm"] = str(element.height_mm)
            payload[f"elements-{idx}-font_size"] = str(element.font_size)
            payload[f"elements-{idx}-sort_order"] = str(element.sort_order)
            if element.is_visible:
                payload[f"elements-{idx}-is_visible"] = "on"
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 302)
        template.refresh_from_db()
        self.assertEqual(str(template.elements.get(element_type="item_name").x_mm), "11.50")

    def test_generate_item_label_pdf_with_template_elements_coordinates(self):
        from core.services.labels import generate_item_label_pdf
        from core.views.labels import LabelTemplateUpdateView

        template = LabelTemplate.objects.create(name="58x40 coords", width_mm=58, height_mm=40)
        LabelTemplateUpdateView._create_default_elements(template)
        template.elements.filter(element_type="item_name").update(x_mm=3, y_mm=3, width_mm=52, height_mm=8, font_size=9)
        template.elements.filter(element_type="internal_code").update(x_mm=3, y_mm=13, width_mm=25, height_mm=5, font_size=7)
        template.elements.filter(element_type="barcode").update(x_mm=3, y_mm=20, width_mm=52, height_mm=12)
        template.elements.filter(element_type="barcode_text").update(x_mm=3, y_mm=33, width_mm=52, height_mm=5, font_size=7)
        pdf = generate_item_label_pdf(self.item, template)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 900)


    def test_label_template_update_ru_localization_without_ukrainian_fragments(self):
        template = LabelTemplate.objects.create(name="RU", is_default=True)
        url = reverse("labeltemplate_update", args=[template.pk]).replace("/uk/", "/ru/")
        response = self.client.get(url)
        self.assertContains(response, "label-designer-workspace")
        self.assertContains(response, "label-designer-inspector")
        self.assertContains(response, reverse("labeltemplate_preview", args=[template.pk]))

    def test_label_template_update_layout_help_text_not_repeated(self):
        template = LabelTemplate.objects.create(name="No duplicates", is_default=True)
        response = self.client.get(reverse("labeltemplate_update", args=[template.pk]))
        html = response.content.decode("utf-8")
        self.assertLessEqual(html.count("Параметри макета впливають на PDF етикетки."), 1)
        self.assertIn("data-label-preview-root", html)
        self.assertIn("data-preview-sheet", html)
        self.assertIn("data-preview-content", html)
        self.assertIn("data-preview-barcode", html)
        self.assertIn("data-label-size", html)

    def test_item_label_print_page_has_preview_link(self):
        printer = Printer.objects.create(name="P", system_name="P1", is_default=True)
        template = LabelTemplate.objects.create(name="T", is_default=True)
        response = self.client.get(reverse("item_label_print", args=[self.item.pk]))
        self.assertContains(response, reverse("item_label_download", args=[self.item.pk]))
        self.assertContains(response, "Переглянути етикетку PDF")
