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


class ActiveChoiceFormTests(TestCase):
    def setUp(self):
        self.active_category = Category.objects.create(name="Активна категорія")
        self.archived_category = Category.objects.create(
            name="Архівна категорія", is_active=False
        )
        self.active_unit = Unit.objects.create(name="Штука", symbol="шт")
        self.archived_unit = Unit.objects.create(
            name="Архівна штука", symbol="арх", is_active=False
        )
        self.active_warehouse = Warehouse.objects.create(name="Активний склад")
        self.archived_warehouse = Warehouse.objects.create(
            name="Архівний склад", is_active=False
        )

    def test_archived_category_is_hidden_from_item_form_category_queryset(self):
        form = ItemForm()

        self.assertIn(self.active_category, form.fields["category"].queryset)
        self.assertNotIn(self.archived_category, form.fields["category"].queryset)

    def test_archived_unit_is_hidden_from_item_form_unit_queryset(self):
        form = ItemForm()

        self.assertIn(self.active_unit, form.fields["unit"].queryset)
        self.assertNotIn(self.archived_unit, form.fields["unit"].queryset)

    def test_archived_warehouse_is_hidden_from_location_form_warehouse_queryset(self):
        form = LocationForm()

        self.assertIn(self.active_warehouse, form.fields["warehouse"].queryset)
        self.assertNotIn(self.archived_warehouse, form.fields["warehouse"].queryset)

    def test_archived_category_is_hidden_from_category_form_parent_queryset(self):
        form = CategoryForm()

        self.assertIn(self.active_category, form.fields["parent"].queryset)
        self.assertNotIn(self.archived_category, form.fields["parent"].queryset)

    def test_category_form_excludes_itself_from_parent_queryset(self):
        form = CategoryForm(instance=self.active_category)

        self.assertNotIn(self.active_category, form.fields["parent"].queryset)

    def test_item_form_rejects_posted_archived_category(self):
        form = ItemForm(
            data={
                "name": "Болт",
                "internal_code": "BOLT-1",
                "category": self.archived_category.pk,
                "unit": self.active_unit.pk,
                "description": "",
                "is_active": "on",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("Не можна вибрати архівний запис.", form.errors["category"])

    def test_active_category_and_unit_are_available_for_item_form(self):
        form = ItemForm(
            data={
                "name": "Гайка",
                "internal_code": "NUT-1",
                "category": self.active_category.pk,
                "unit": self.active_unit.pk,
                "description": "",
                "is_active": "on",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_stock_balance_filter_uses_only_active_references(self):
        active_location = Location.objects.create(
            warehouse=self.active_warehouse, name="Активна локація"
        )
        archived_location = Location.objects.create(
            warehouse=self.active_warehouse, name="Архівна локація", is_active=False
        )
        location_in_archived_warehouse = Location.objects.create(
            warehouse=self.archived_warehouse, name="Локація архівного складу"
        )
        active_item = Item.objects.create(
            name="Активна номенклатура", unit=self.active_unit
        )
        archived_item = Item.objects.create(
            name="Архівна номенклатура", unit=self.active_unit, is_active=False
        )

        form = StockBalanceFilterForm()

        self.assertIn(self.active_warehouse, form.fields["warehouse"].queryset)
        self.assertNotIn(self.archived_warehouse, form.fields["warehouse"].queryset)
        self.assertIn(active_location, form.fields["location"].queryset)
        self.assertNotIn(archived_location, form.fields["location"].queryset)
        self.assertNotIn(
            location_in_archived_warehouse, form.fields["location"].queryset
        )
        self.assertIn(active_item, form.fields["item"].queryset)
        self.assertNotIn(archived_item, form.fields["item"].queryset)


class WarehouseModelTests(TestCase):
    def setUp(self):
        self.unit = Unit.objects.create(name="Piece", symbol="pcs")
        warehouse_barcode = BarcodeRegistry.objects.create(
            barcode="WH00000001", prefix=BarcodeRegistry.Prefix.WAREHOUSE
        )
        self.warehouse = Warehouse.objects.create(
            name="Main warehouse", barcode=warehouse_barcode
        )
        location_barcode = BarcodeRegistry.objects.create(
            barcode="LOC00000001", prefix=BarcodeRegistry.Prefix.LOCATION
        )
        self.location = Location.objects.create(
            warehouse=self.warehouse,
            name="A-01",
            barcode=location_barcode,
        )

    def test_barcode_registry_keeps_barcodes_globally_unique(self):
        BarcodeRegistry.objects.create(
            barcode="ITM00000001", prefix=BarcodeRegistry.Prefix.ITEM
        )

        with self.assertRaises(IntegrityError):
            BarcodeRegistry.objects.create(
                barcode="ITM00000001", prefix=BarcodeRegistry.Prefix.ITEM
            )

    def test_barcode_registry_validates_prefix(self):
        barcode = BarcodeRegistry(
            barcode="WH00000002", prefix=BarcodeRegistry.Prefix.ITEM
        )

        with self.assertRaises(ValidationError):
            barcode.full_clean()

    def test_barcode_sequence_supports_required_prefixes(self):
        prefixes = {choice.value for choice in BarcodeRegistry.Prefix}

        self.assertEqual(prefixes, {"ITM", "WH", "RCK", "LOC"})
        sequence = BarcodeSequence.objects.create(prefix=BarcodeRegistry.Prefix.RACK)
        self.assertEqual(sequence.next_number, 1)
        self.assertEqual(sequence.padding, 10)

    def test_item_internal_code_is_normalized_when_filled(self):
        item = Item.objects.create(
            name="First item", internal_code=" SKU-1 ", unit=self.unit
        )

        self.assertEqual(item.internal_code, "SKU-1")

    def test_item_internal_code_can_be_blank_for_multiple_items(self):
        first = Item.objects.create(name="First item", internal_code="", unit=self.unit)
        second = Item.objects.create(
            name="Second item", internal_code="", unit=self.unit
        )

        self.assertIsNone(first.internal_code)
        self.assertIsNone(second.internal_code)
        self.assertEqual(Item.objects.filter(internal_code__isnull=True).count(), 2)

    def test_stock_balance_quantity_precision_and_unique_location_balance(self):
        item = Item.objects.create(name="Precise item", unit=self.unit)
        balance = StockBalance.objects.create(
            item=item,
            location=self.location,
            qty=Decimal("123456789012345.123"),
        )

        qty_field = StockBalance._meta.get_field("qty")
        self.assertEqual(qty_field.max_digits, 18)
        self.assertEqual(qty_field.decimal_places, 3)
        self.assertEqual(balance.qty, Decimal("123456789012345.123"))
        with self.assertRaises(IntegrityError):
            StockBalance.objects.create(
                item=item, location=self.location, qty=Decimal("1.000")
            )

    def test_stock_movement_has_required_types(self):
        expected_types = {
            "initial_balance",
            "in",
            "out",
            "return",
            "writeoff",
            "transfer",
            "adjustment",
        }
        actual_types = {choice.value for choice in StockMovement.MovementType}

        self.assertEqual(actual_types, expected_types)

    def test_stock_movement_can_store_transfer_between_locations(self):
        item = Item.objects.create(name="Transfer item", unit=self.unit)
        destination_barcode = BarcodeRegistry.objects.create(
            barcode="RCK00000001", prefix=BarcodeRegistry.Prefix.RACK
        )
        destination = Location.objects.create(
            warehouse=self.warehouse,
            name="Rack 1",
            location_type=Location.LocationType.RACK,
            barcode=destination_barcode,
        )
        movement = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.TRANSFER,
            item=item,
            qty=Decimal("5.500"),
            source_location=self.location,
            destination_location=destination,
        )

        self.assertEqual(movement.qty, Decimal("5.500"))
        self.assertEqual(movement.source_location, self.location)
        self.assertEqual(movement.destination_location, destination)

    def test_models_are_active_by_default_for_soft_delete_archiving(self):
        item = Item.objects.create(name="Active item", unit=self.unit)

        self.assertTrue(item.is_active)
        item.is_active = False
        item.save(update_fields=["is_active"])
        item.refresh_from_db()
        self.assertFalse(item.is_active)


class DirectoryWebInterfaceTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="ui-user", password="test-password"
        )
        call_command("init_roles", stdout=StringIO())
        self.user.groups.add(Group.objects.get(name="Адміністратор складу"))
        self.client.force_login(self.user)
        self.unit = Unit.objects.create(name="Штука", symbol="шт")
        self.category = Category.objects.create(name="Матеріали")
        self.recipient = Recipient.objects.create(name="Цех 1")
        self.item = Item.objects.create(
            name="Болт М8",
            internal_code="BOLT-M8",
            category=self.category,
            unit=self.unit,
        )
        self.warehouse = Warehouse.objects.create(name="Основний склад")
        self.location = Location.objects.create(warehouse=self.warehouse, name="A-01")
        self.balance = StockBalance.objects.create(
            item=self.item, location=self.location, qty=Decimal("5.000")
        )

    def test_pages_redirect_anonymous_user_to_login(self):
        self.client.logout()

        response = self.client.get(reverse("item_list"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_directory_list_pages_are_available_for_logged_in_user(self):
        url_names = [
            "unit_list",
            "category_list",
            "recipient_list",
            "item_list",
            "warehouse_list",
            "location_list",
        ]

        for url_name in url_names:
            with self.subTest(url_name=url_name):
                response = self.client.get(reverse(url_name))
                self.assertEqual(response.status_code, 200)

    def test_unit_create_update_and_archive(self):
        create_response = self.client.post(
            reverse("unit_create"),
            {"name": "Кілограм", "symbol": "кг", "is_active": "on"},
        )
        self.assertEqual(create_response.status_code, 302)
        unit = Unit.objects.get(symbol="кг")

        update_response = self.client.post(
            reverse("unit_update", args=[unit.pk]),
            {"name": "Кілограм", "symbol": "kg", "is_active": "on"},
        )
        self.assertEqual(update_response.status_code, 302)
        unit.refresh_from_db()
        self.assertEqual(unit.symbol, "kg")

        archive_response = self.client.post(reverse("unit_archive", args=[unit.pk]))
        self.assertEqual(archive_response.status_code, 302)
        unit.refresh_from_db()
        self.assertFalse(unit.is_active)

    def test_item_list_searches_by_name_internal_code_and_barcode(self):
        self.item.refresh_from_db()
        barcode = self.item.barcode.barcode

        self.assertEqual(barcode, "ITM0000000001")

        for query in [self.item.name, self.item.internal_code, barcode, barcode[-4:]]:
            with self.subTest(query=query):
                response = self.client.get(reverse("item_list"), {"q": query})

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, self.item.name)
                self.assertContains(response, barcode)

    def test_item_can_be_created_through_web(self):
        response = self.client.post(
            reverse("item_create"),
            {
                "name": "Гайка М8",
                "internal_code": "NUT-M8",
                "category": self.category.pk,
                "unit": self.unit.pk,
                "description": "",
                "is_active": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Item.objects.filter(internal_code="NUT-M8").exists())

    def test_item_create_page_hides_archived_categories(self):
        archived_category = Category.objects.create(
            name="Архівна категорія UI", is_active=False
        )

        response = self.client.get(reverse("item_create"), HTTP_ACCEPT_LANGUAGE="uk")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.category.name)
        self.assertNotContains(response, archived_category.name)

    def test_item_create_page_rejects_archived_category_post(self):
        archived_category = Category.objects.create(
            name="Архівна категорія POST", is_active=False
        )

        response = self.client.post(
            reverse("item_create"),
            {
                "name": "Шайба М8",
                "internal_code": "WASHER-M8",
                "category": archived_category.pk,
                "unit": self.unit.pk,
                "description": "",
                "is_active": "on",
            },
            HTTP_ACCEPT_LANGUAGE="uk",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Не можна вибрати архівний запис.")
        self.assertFalse(Item.objects.filter(internal_code="WASHER-M8").exists())

    def test_warehouse_and_location_can_be_created_through_web(self):
        warehouse_response = self.client.post(
            reverse("warehouse_create"),
            {"name": "Резервний склад", "address": "", "is_active": "on"},
        )
        self.assertEqual(warehouse_response.status_code, 302)
        warehouse = Warehouse.objects.get(name="Резервний склад")

        location_response = self.client.post(
            reverse("location_create"),
            {
                "warehouse": warehouse.pk,
                "name": "B-02",
                "location_type": Location.LocationType.LOCATION,
                "is_active": "on",
            },
        )
        self.assertEqual(location_response.status_code, 302)
        self.assertTrue(
            Location.objects.filter(warehouse=warehouse, name="B-02").exists()
        )

    def test_cannot_create_duplicate_root_category_with_trimmed_name(self):
        response = self.client.post(
            reverse("category_create"),
            {"name": " Матеріали ", "parent": "", "is_active": "on"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Категорія з такою назвою вже існує.")
        self.assertEqual(
            Category.objects.filter(
                name__iexact="Матеріали", parent__isnull=True
            ).count(),
            1,
        )

    def test_cannot_create_duplicate_category_with_same_parent(self):
        parent = Category.objects.create(name="Запчастини")
        Category.objects.create(name="Електрика", parent=parent)

        response = self.client.post(
            reverse("category_create"),
            {"name": " електрика ", "parent": parent.pk, "is_active": "on"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Категорія з такою назвою вже існує.")
        self.assertEqual(Category.objects.filter(parent=parent).count(), 1)

    def test_can_create_same_category_name_in_different_parents(self):
        first_parent = Category.objects.create(name="Склад 1")
        second_parent = Category.objects.create(name="Склад 2")
        Category.objects.create(name="Кабелі", parent=first_parent)

        response = self.client.post(
            reverse("category_create"),
            {"name": "Кабелі", "parent": second_parent.pk, "is_active": "on"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Category.objects.filter(name="Кабелі").count(), 2)

    def test_archive_and_restore_actions_toggle_active_status(self):
        unit = Unit.objects.create(name="Метр", symbol="м")

        archive_response = self.client.post(reverse("unit_archive", args=[unit.pk]))
        self.assertEqual(archive_response.status_code, 302)
        unit.refresh_from_db()
        self.assertFalse(unit.is_active)

        restore_response = self.client.post(reverse("unit_restore", args=[unit.pk]))
        self.assertEqual(restore_response.status_code, 302)
        unit.refresh_from_db()
        self.assertTrue(unit.is_active)

    def test_directory_list_shows_active_by_default_and_archived_by_filter(self):
        archived = Unit.objects.create(name="Літр", symbol="л", is_active=False)

        active_response = self.client.get(reverse("unit_list"))
        self.assertContains(active_response, self.unit.name)
        self.assertNotContains(active_response, archived.name)

        archived_response = self.client.get(
            reverse("unit_list"), {"status": "archived"}
        )
        self.assertNotContains(archived_response, self.unit.name)
        self.assertContains(archived_response, archived.name)

    def test_archive_category_blocked_when_active_items_exist(self):
        response = self.client.post(
            reverse("category_archive", args=[self.category.pk])
        )

        self.category.refresh_from_db()
        self.assertTrue(self.category.is_active)
        self.assertEqual(response.status_code, 302)

    def test_find_duplicates_command_reports_duplicates_without_changes(self):
        first = Category.objects.create(name="Електрозапчастини")
        second = Category.objects.create(name=" електрозапчастини ")
        before_count = Category.objects.count()
        out = StringIO()

        call_command("find_duplicates", stdout=out)

        self.assertIn("Category", out.getvalue())
        self.assertEqual(Category.objects.count(), before_count)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertTrue(first.is_active)
        self.assertTrue(second.is_active)
