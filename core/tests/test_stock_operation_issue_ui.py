from html.parser import HTMLParser

from .stock_operations_ui_utils import *  # noqa: F403


class IssueHiddenInputParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_issue_form = False
        self.hidden_inputs = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        form_classes = attrs.get("class", "").split()
        if (
            tag == "form"
            and attrs.get("method", "").lower() == "post"
            and "operation-form-card" in form_classes
        ):
            self.in_issue_form = True
        if (
            self.in_issue_form
            and tag == "input"
            and attrs.get("type", "").lower() == "hidden"
            and attrs.get("name")
        ):
            self.hidden_inputs[attrs["name"]] = attrs.get("value", "")

    def handle_endtag(self, tag):
        if tag == "form" and self.in_issue_form:
            self.in_issue_form = False


class StockIssueInterfaceTests(StockIssueInterfaceTestBase):
    def test_stock_issue_page_available_to_storekeeper(self):
        self.client.force_login(self.storekeeper)
        response = self.client.get(reverse("stock_issue"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Видача товару")

    def test_stock_issue_post_decreases_balance_and_creates_out_movement(self):
        self.client.force_login(self.storekeeper)
        response = self.client.post(
            reverse("stock_issue"),
            {
                "item": self.item.pk,
                "warehouse": self.warehouse.pk,
                "location": self.location.pk,
                "qty": "2.000",
                "issue_reason": StockMovement.IssueReason.SALE,
                "department": self.usage_place.pk,
                "recipient": self.recipient.pk,
                "document_number": "SO-1",
                "comment": "",
                "occurred_at": "2026-01-15T10:00",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.balance.refresh_from_db()
        movement = StockMovement.objects.latest("id")
        self.assertEqual(self.balance.qty, Decimal("5.000"))
        self.assertEqual(movement.movement_type, StockMovement.MovementType.OUT)
        self.assertEqual(movement.issue_reason, StockMovement.IssueReason.SALE)

    def test_rendered_issue_form_submits_auto_selected_warehouse(self):
        self.client.force_login(self.superuser)
        response = self.client.get(
            reverse("stock_issue"),
            {"barcode": self.item.barcode.barcode},
        )
        parser = IssueHiddenInputParser()
        parser.feed(response.content.decode())

        self.assertIn("warehouse", parser.hidden_inputs)
        self.assertEqual(parser.hidden_inputs["warehouse"], str(self.warehouse.pk))

        post_data = {
            **parser.hidden_inputs,
            "qty": "2.000",
            "recipient": self.recipient.pk,
            "department": self.usage_place.pk,
        }
        issue_response = self.client.post(reverse("stock_issue"), post_data)

        self.assertRedirects(
            issue_response,
            reverse("stock_issue_result", args=[StockMovement.objects.latest("id").pk]),
            fetch_redirect_response=False,
        )
        self.balance.refresh_from_db()
        movement = StockMovement.objects.latest("id")
        self.assertEqual(self.balance.qty, Decimal("5.000"))
        self.assertEqual(movement.movement_type, StockMovement.MovementType.OUT)
        self.assertEqual(movement.source_warehouse, self.warehouse)
        self.assertEqual(movement.source_location, self.location)

    def test_issue_hidden_field_validation_errors_are_visible(self):
        self.client.force_login(self.superuser)
        response = self.client.post(
            reverse("stock_issue"),
            {
                "item": self.item.pk,
                "location": self.location.pk,
                "qty": "1.000",
                "issue_reason": StockMovement.IssueReason.OTHER,
                "recipient": self.recipient.pk,
                "department": self.usage_place.pk,
                "occurred_at": "2026-01-15T10:00",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Склад:")
        self.assertContains(response, "Це поле обов")

    def test_stock_issue_result_page_is_simple_and_links_autoprint_control_slip(self):
        self.client.force_login(self.storekeeper)
        response = self.client.post(
            reverse("stock_issue"),
            {
                "item": self.item.pk,
                "warehouse": self.warehouse.pk,
                "location": self.location.pk,
                "qty": "2.000",
                "issue_reason": StockMovement.IssueReason.SALE,
                "department": self.usage_place.pk,
                "recipient": self.recipient.pk,
                "document_number": "SO-PRINT",
                "comment": "",
                "occurred_at": "2026-05-13T10:06",
            },
            follow=True,
        )

        movement = StockMovement.objects.get(document_number="SO-PRINT")
        print_url = reverse("stock_movement_print", kwargs={"pk": movement.pk})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Видачу виконано")
        self.assertContains(response, "✓")
        self.assertContains(response, "Товар видано зі складу")
        self.assertContains(response, "Товар")
        self.assertContains(response, self.item.name)
        self.assertContains(response, "Кількість")
        self.assertContains(response, "2,000")
        self.assertContains(response, "Хто взяв товар")
        self.assertContains(response, self.recipient.name)
        self.assertContains(response, "Цех / місце використання")
        self.assertContains(response, "Sales")
        self.assertContains(response, "Дата і час операції")
        self.assertContains(response, "2026-05-13 10:06:00")
        self.assertContains(response, "Залишок після операції")
        self.assertContains(response, "5,000")
        self.assertContains(response, "Друкувати контрольний талон")
        self.assertContains(response, f"{print_url}?autoprint=1")
        self.assertContains(response, "Нова видача")
        self.assertContains(response, "На головний екран")
        self.assertContains(response, reverse("dashboard"))
        self.assertNotContains(response, ">Склад</dt>")
        self.assertNotContains(response, ">Локація</dt>")
        self.assertNotContains(response, "Тип видачі")
        self.assertNotContains(response, "Документ")
        self.assertNotContains(response, "Коментар")
        self.assertNotContains(response, "До рухів товарів")
        self.assertNotContains(response, "До залишків")

    def test_english_stock_issue_result_page_uses_english_only_tablet_labels(self):
        from .test_stock_services import _messages_compiled

        if not _messages_compiled():
            self.skipTest("GNU gettext msgfmt is not available; skipping EN assertion")

        self.client.force_login(self.storekeeper)
        movement = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.OUT,
            item=self.item,
            qty=Decimal("1.000"),
            source_location=self.location,
            recipient=self.recipient,
            department="Assembly",
            occurred_at=timezone.datetime(
                2026, 5, 13, 10, 6, 32, tzinfo=timezone.get_current_timezone()
            ),
        )

        response = self.client.get(f"/en/stock/issue/{movement.pk}/")
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("Issue completed", html)
        self.assertIn("Item has been issued from stock", html)
        self.assertIn("✓", html)
        self.assertIn("Item", html)
        self.assertIn("Quantity", html)
        self.assertIn("Who takes the item", html)
        self.assertTrue("Department / place of use" in html or "Місце використання" in html)
        self.assertIn("Operation date and time", html)
        self.assertIn("Balance after operation", html)
        self.assertIn("Print control slip", html)
        self.assertIn("New issue", html)
        self.assertIn("Home", html)
        self.assertNotIn("Видачу виконано", html)
        self.assertNotIn("Товар видано зі складу", html)
        self.assertNotIn("На головний екран", html)
        self.assertNotIn("Товар", html)
        self.assertNotIn("Хто взяв товар", html)
        self.assertNotIn("Цех / місце використання", html)
        self.assertNotIn("Друкувати контрольний талон", html)

    def test_stock_issue_post_stores_repair_reason_and_department(self):
        self.client.force_login(self.storekeeper)
        usage_place = UsagePlace.objects.create(name="Ремонтний цех")
        response = self.client.post(
            reverse("stock_issue"),
            {
                "item": self.item.pk,
                "warehouse": self.warehouse.pk,
                "location": self.location.pk,
                "qty": "1.000",
                "issue_reason": StockMovement.IssueReason.REPAIR,
                "department": usage_place.pk,
                "recipient": self.recipient.pk,
                "document_number": "",
                "comment": "",
                "occurred_at": "2026-01-15T11:00",
            },
        )

        self.assertEqual(response.status_code, 302)
        movement = StockMovement.objects.latest("id")
        self.assertEqual(movement.issue_reason, StockMovement.IssueReason.REPAIR)
        self.assertEqual(movement.department, "Ремонтний цех")

    def test_stock_issue_rejects_quantity_greater_than_balance(self):
        self.client.force_login(self.storekeeper)
        movement_count = StockMovement.objects.count()
        response = self.client.post(
            reverse("stock_issue"),
            {
                "item": self.item.pk,
                "warehouse": self.warehouse.pk,
                "location": self.location.pk,
                "qty": "99.000",
                "issue_reason": StockMovement.IssueReason.OTHER,
                "department": self.usage_place.pk,
                "recipient": self.recipient.pk,
                "document_number": "",
                "comment": "",
                "occurred_at": "2026-01-15T12:00",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Недостатньо залишку для видачі")
        self.assertContains(response, "alert-danger")
        self.assertEqual(StockMovement.objects.count(), movement_count)
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.qty, Decimal("7.000"))

    def test_stock_issue_post_without_recipient_fails_validation_uk(self):
        self.client.force_login(self.storekeeper)
        response = self.client.post(
            "/uk/stock/issue/",
            {
                "item": self.item.pk,
                "warehouse": self.warehouse.pk,
                "location": self.location.pk,
                "qty": "1.000",
                "issue_reason": StockMovement.IssueReason.OTHER,
                "department": "",
                "document_number": "",
                "comment": "",
                "occurred_at": "2026-01-15T12:00",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Оберіть, хто бере товар.")

    def test_stock_issue_post_without_recipient_fails_validation_en(self):
        from .test_stock_services import _messages_compiled

        if not _messages_compiled():
            self.skipTest("GNU gettext msgfmt is not available; skipping EN assertion")

        self.client.force_login(self.storekeeper)
        response = self.client.post(
            "/en/stock/issue/",
            {
                "item": self.item.pk,
                "warehouse": self.warehouse.pk,
                "location": self.location.pk,
                "qty": "1.000",
                "issue_reason": StockMovement.IssueReason.OTHER,
                "department": "",
                "document_number": "",
                "comment": "",
                "occurred_at": "2026-01-15T12:00",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Choose who takes the item.")

    def test_movements_show_translated_issue_reason(self):
        StockMovement.objects.create(
            movement_type=StockMovement.MovementType.OUT,
            item=self.item,
            qty=Decimal("1.000"),
            source_location=self.location,
            issue_reason=StockMovement.IssueReason.SALE,
            department="Цех 1",
            document_number="DOC-1",
        )
        self.client.force_login(self.storekeeper)
        response = self.client.get(reverse("movement_list"), HTTP_ACCEPT_LANGUAGE="uk")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Продаж")
        self.assertContains(response, "Цех 1")
        self.assertContains(response, "DOC-1")

class StockOperationWorkflowTests(StockOperationWorkflowTestBase):
    def test_issue_uses_default_location_when_locations_disabled(self):
        from ..services.stock import receive_stock

        self.disable_locations()
        default_location = get_default_location_for_warehouse(self.warehouse)
        receive_stock(item=self.item, location=default_location, qty=Decimal("5.000"))

        response = self.client.post(
            reverse("stock_issue"),
            {
                "item": self.item.pk,
                "warehouse": self.warehouse.pk,
                "qty": "2.000",
                "issue_reason": StockMovement.IssueReason.OTHER,
                "department": self.usage_place.pk,
                "recipient": self.recipient.pk,
                "document_number": "",
                "comment": "Default issue",
                "occurred_at": timezone.now().strftime("%Y-%m-%dT%H:%M"),
            },
        )

        self.assertEqual(response.status_code, 302)
        movement = StockMovement.objects.get(comment="Default issue")
        self.assertEqual(movement.movement_type, StockMovement.MovementType.OUT)
        self.assertEqual(movement.source_location, default_location)
        self.assertEqual(
            StockBalance.objects.get(item=self.item, location=default_location).qty,
            Decimal("3.000"),
        )

    def test_issue_insufficient_stock_shows_alert_when_locations_disabled(self):
        self.disable_locations()
        default_location = get_default_location_for_warehouse(self.warehouse)
        StockBalance.objects.create(
            item=self.item, location=default_location, qty=Decimal("1.000")
        )

        response = self.client.post(
            reverse("stock_issue"),
            {
                "item": self.item.pk,
                "warehouse": self.warehouse.pk,
                "qty": "2.000",
                "issue_reason": StockMovement.IssueReason.OTHER,
                "department": self.usage_place.pk,
                "recipient": self.recipient.pk,
                "document_number": "",
                "comment": "Too much default issue",
                "occurred_at": timezone.now().strftime("%Y-%m-%dT%H:%M"),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Недостатньо залишку для видачі")
        self.assertContains(response, "alert-danger")
        self.assertFalse(
            StockMovement.objects.filter(comment="Too much default issue").exists()
        )

    def test_issue_page_contains_tablet_scan_card(self):
        response = self.client.get(reverse("stock_issue"))
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Сканування товару")
        self.assertContains(
            response, "Відскануйте штрихкод товару або введіть його вручну"
        )
        self.assertContains(response, "Знайти товар")
        self.assertIn('operation-form-card', html)
        self.assertIn('name="barcode"', html)
        self.assertIn('autocomplete="off"', html)
        self.assertIn('placeholder="Штрихкод товару"', html)
        self.assertIn('form-control form-control-lg py-3 fs-4', html)
        self.assertIn('btn btn-primary btn-lg px-4 py-3 fw-semibold', html)
        self.assertNotIn('autofocus', html)

    def test_issue_get_barcode_prefills_item_and_stock_source(self):
        StockBalance.objects.create(
            item=self.item, location=self.location, qty=Decimal("7.000")
        )

        response = self.client.get(
            f'{reverse("stock_issue")}?barcode={self.item.barcode.barcode}'
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form"].initial["item"], self.item)
        self.assertEqual(response.context["form"].initial["warehouse"], self.warehouse)
        self.assertEqual(response.context["form"].initial["location"], self.location)
        self.assertContains(response, "Очистити")
        self.assertContains(response, f'href="{reverse("stock_issue")}"', html=False)
        self.assertContains(response, "Знайдений товар")
        self.assertContains(response, "Назва товару")
        self.assertContains(response, self.item.name)
        self.assertContains(response, self.item.barcode.barcode)
        self.assertContains(response, "Доступний залишок")
        self.assertEqual(
            response.context["scanned_item_context"]["available_qty"], Decimal("7.000")
        )
        self.assertContains(response, "Дані для видачі визначено автоматично.")

    def test_issue_get_barcode_contains_operation_token_and_disable_submit_attrs(self):
        StockBalance.objects.create(
            item=self.item, location=self.location, qty=Decimal("7.000")
        )

        response = self.client.get(
            f'{reverse("stock_issue")}?barcode={self.item.barcode.barcode}'
        )
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["operation_token"])
        self.assertIn('name="operation_token"', html)
        self.assertIn('value="%s"' % response.context["operation_token"], html)
        self.assertIn('data-disable-on-submit', html)
        self.assertIn('data-submit-button', html)
        self.assertIn('data-saving-label="Збереження..."', html)

    def test_issue_duplicate_post_with_same_operation_token_redirects_without_second_movement(self):
        StockBalance.objects.create(
            item=self.item, location=self.location, qty=Decimal("7.000")
        )
        get_response = self.client.get(
            f'{reverse("stock_issue")}?barcode={self.item.barcode.barcode}'
        )
        form = get_response.context["form"]
        token = get_response.context["operation_token"]
        movement_count = StockMovement.objects.count()
        data = {
            "operation_token": token,
            "item": form.initial["item"].pk,
            "warehouse": form.initial["warehouse"].pk,
            "location": form.initial["location"].pk,
            "qty": "2.000",
            "issue_reason": form.initial["issue_reason"],
            "department": self.usage_place.pk,
            "recipient": self.recipient.pk,
            "document_number": "",
            "comment": "",
            "occurred_at": form.initial["occurred_at"],
        }

        first_response = self.client.post(reverse("stock_issue"), data)
        second_response = self.client.post(reverse("stock_issue"), data)

        self.assertEqual(first_response.status_code, 302)
        self.assertEqual(second_response.status_code, 302)
        self.assertEqual(second_response["Location"], first_response["Location"])
        self.assertEqual(
            StockMovement.objects.count(),
            movement_count + 1,
        )

    def test_issue_get_barcode_chooses_largest_positive_balance(self):
        StockBalance.objects.create(
            item=self.item, location=self.location, qty=Decimal("7.000")
        )
        larger_balance = StockBalance.objects.create(
            item=self.item, location=self.destination_location, qty=Decimal("9.000")
        )

        response = self.client.get(
            f'{reverse("stock_issue")}?barcode={self.item.barcode.barcode}'
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["best_stock_balance"], larger_balance)
        self.assertEqual(response.context["form"].initial["location"], self.destination_location)
        self.assertEqual(response.context["form"].initial["warehouse"], self.destination_warehouse)

    def test_issue_get_barcode_with_no_stock_shows_warning(self):
        StockBalance.objects.create(
            item=self.item, location=self.location, qty=Decimal("0.000")
        )

        response = self.client.get(
            f'{reverse("stock_issue")}?barcode={self.item.barcode.barcode}'
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, "Товар знайдено, але доступного залишку для видачі немає."
        )
        self.assertFalse(response.context["show_issue_form"])

    def test_issue_page_hides_manual_stock_source_and_comment_fields(self):
        StockBalance.objects.create(
            item=self.item, location=self.location, qty=Decimal("7.000")
        )

        response = self.client.get(
            f'{reverse("stock_issue")}?barcode={self.item.barcode.barcode}'
        )
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('for="id_warehouse"', html)
        self.assertNotIn('for="id_location"', html)
        self.assertNotIn('for="id_issue_reason"', html)
        self.assertNotIn('for="id_document_number"', html)
        self.assertNotIn('for="id_comment"', html)
        self.assertNotIn('for="id_occurred_at"', html)
        self.assertNotContains(response, ">Склад</label>")
        self.assertNotContains(response, ">Локація</label>")
        self.assertNotContains(response, "Тип видачі")
        self.assertNotContains(response, "Документ")
        self.assertNotContains(response, "Коментар")
        self.assertNotContains(response, "Дата операції")
        self.assertContains(response, "Кількість")
        self.assertContains(response, "Хто взяв товар")
        self.assertContains(response, "Цех / місце використання")
        self.assertContains(response, 'class="form-select form-select-lg"')

    def test_issue_form_lists_only_active_usage_places(self):
        form = StockIssueForm()
        choices = list(form.fields["department"].queryset)

        self.assertIsInstance(form.fields["department"].widget, forms.Select)
        self.assertIn(self.usage_place, choices)
        self.assertNotIn(self.inactive_usage_place, choices)
        self.assertEqual(
            form.fields["department"].empty_label,
            "Оберіть цех або місце використання",
        )
        self.assertEqual(
            form.fields["qty"].widget.attrs["class"],
            "form-control form-control-lg text-center",
        )
        self.assertEqual(form.fields["qty"].widget.attrs["min"], "1")
        self.assertEqual(form.fields["qty"].widget.attrs["step"], "1")
        self.assertEqual(form.fields["qty"].widget.attrs["inputmode"], "numeric")
        self.assertEqual(
            form.fields["department"].widget.attrs["class"],
            "form-select form-select-lg",
        )

    def test_issue_quantity_stepper_controls_and_attrs(self):
        StockBalance.objects.create(
            item=self.item, location=self.location, qty=Decimal("7.000")
        )

        response = self.client.get(
            f'{reverse("stock_issue")}?barcode={self.item.barcode.barcode}'
        )
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn('data-qty-stepper', html)
        self.assertIn('data-qty-decrement', html)
        self.assertIn('data-qty-increment', html)
        self.assertIn('name="qty"', html)
        self.assertIn('min="1"', html)
        self.assertIn('step="1"', html)
        self.assertIn('inputmode="numeric"', html)
        self.assertIn('pattern="[0-9]*"', html)
        self.assertIn('text-center', html)
        self.assertIn('normalizeQuantity', html)

    def test_issue_form_cleans_department_to_usage_place_name(self):
        form = StockIssueForm(
            data={
                "item": self.item.pk,
                "warehouse": self.warehouse.pk,
                "location": self.location.pk,
                "qty": "1.000",
                "issue_reason": StockMovement.IssueReason.OTHER,
                "department": self.usage_place.pk,
                "recipient": self.recipient.pk,
                "document_number": "",
                "comment": "",
                "occurred_at": "2026-01-15T10:00",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["department"], "Sales")

    def test_issue_page_lists_only_active_usage_places(self):
        StockBalance.objects.create(
            item=self.item, location=self.location, qty=Decimal("7.000")
        )

        response = self.client.get(
            f'{reverse("stock_issue")}?barcode={self.item.barcode.barcode}'
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sales")
        self.assertNotContains(response, "Archived place")

    def test_issue_form_shows_tp_506_and_wire_drawing_shop_but_not_legacy_places(self):
        form = StockIssueForm()
        choice_names = set(form.fields["department"].queryset.values_list("name", flat=True))

        self.assertIn("ТП-506", choice_names)
        self.assertIn("Цех волочіння", choice_names)
        self.assertNotIn("Протяжка", choice_names)
        self.assertNotIn("Стан волочіння", choice_names)

    def test_issue_department_is_required(self):
        form = StockIssueForm(
            data={
                "item": self.item.pk,
                "warehouse": self.warehouse.pk,
                "location": self.location.pk,
                "qty": "1.000",
                "issue_reason": StockMovement.IssueReason.OTHER,
                "department": "",
                "recipient": self.recipient.pk,
                "document_number": "",
                "comment": "",
                "occurred_at": "2026-01-15T10:00",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("department", form.errors)
        self.assertEqual(
            str(form.errors["department"][0]),
            "Оберіть цех або місце використання.",
        )

    def test_issue_form_without_active_usage_places_requires_configuration(self):
        UsagePlace.objects.update(is_active=False)
        form = StockIssueForm(
            data={
                "item": self.item.pk,
                "warehouse": self.warehouse.pk,
                "location": self.location.pk,
                "qty": "1.000",
                "issue_reason": StockMovement.IssueReason.OTHER,
                "department": "",
                "recipient": self.recipient.pk,
                "document_number": "",
                "comment": "",
                "occurred_at": "2026-01-15T10:00",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("department", form.errors)
        self.assertEqual(
            str(form.errors["department"][0]),
            "Налаштуйте хоча б одне активне місце використання.",
        )

    def test_issue_post_after_barcode_without_manual_stock_source_saves_department(self):
        balance = StockBalance.objects.create(
            item=self.item, location=self.location, qty=Decimal("7.000")
        )
        get_response = self.client.get(
            f'{reverse("stock_issue")}?barcode={self.item.barcode.barcode}'
        )
        form = get_response.context["form"]
        usage_place = UsagePlace.objects.create(name="Монтажна дільниця")

        response = self.client.post(
            reverse("stock_issue"),
            {
                "item": form.initial["item"].pk,
                "warehouse": form.initial["warehouse"].pk,
                "location": form.initial["location"].pk,
                "qty": "2.000",
                "issue_reason": form.initial["issue_reason"],
                "department": usage_place.pk,
                "recipient": self.recipient.pk,
                "document_number": "",
                "comment": "",
                "occurred_at": form.initial["occurred_at"],
            },
        )

        self.assertEqual(response.status_code, 302)
        balance.refresh_from_db()
        movement = StockMovement.objects.latest("id")
        self.assertEqual(balance.qty, Decimal("5.000"))
        self.assertEqual(movement.source_location, self.location)
        self.assertEqual(movement.department, "Монтажна дільниця")
        self.assertEqual(movement.issue_reason, StockMovement.IssueReason.OTHER)
        self.assertEqual(movement.comment, "")

    def test_control_slip_shows_issue_department(self):
        movement = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.OUT,
            item=self.item,
            qty=Decimal("1.000"),
            source_location=self.location,
            recipient=self.recipient,
            department="Компресорна",
        )

        response = self.client.get(
            reverse("stock_movement_print", kwargs={"pk": movement.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Цех / місце використання")
        self.assertContains(response, "Компресорна")

    def test_english_issue_page_has_no_ukrainian_tablet_phrases(self):
        StockBalance.objects.create(
            item=self.item, location=self.location, qty=Decimal("7.000")
        )

        response = self.client.get(
            f'/en/stock/issue/?barcode={self.item.barcode.barcode}'
        )
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("Scan item", html)
        self.assertIn("Found item", html)
        self.assertIn("Available stock", html)
        self.assertIn("Who takes the item", html)
        self.assertTrue("Department / place of use" in html or "Місце використання" in html)
        self.assertIn("Take item", html)
        self.assertIn('data-qty-decrement', html)
        self.assertIn('data-qty-increment', html)
        self.assertIn('inputmode="numeric"', html)
        self.assertIn('data-saving-label="Saving..."', html)
        self.assertNotIn("Збереження...", html)
        self.assertNotIn("Операція вже була збережена.", html)
