from .stock_operations_ui_utils import *  # noqa: F403


class StockOperationWorkflowTests(StockOperationWorkflowTestBase):
    def test_receive_stock_ui_increases_balance_creates_movement_and_barcode(self):
        self.item.barcode = None
        self.item.save(update_fields=["barcode"])
        prefill_response = self.client.get(
            f'{reverse("stock_return")}?barcode={self.item.barcode.barcode}'
        )
        return_location = prefill_response.context["form"].initial["location"]
        expected_location = get_default_location_for_warehouse(return_location.warehouse)

        response = self.client.post(
            reverse("stock_return"),
            {
                "item": self.item.pk,
                "warehouse": return_location.warehouse.pk,
                "location": return_location.pk,
                "qty": "7.000",
                "recipient": self.recipient.pk,
                "department": self.usage_place.pk,
                "comment": "",
                "occurred_at": timezone.now().strftime("%Y-%m-%dT%H:%M"),
            },
        )
        self.assertEqual(response.status_code, 302)
        balance = StockBalance.objects.get(item=self.item, location=expected_location)
        movement = StockMovement.objects.get(department=self.usage_place.name)
        self.item.refresh_from_db()
        self.assertEqual(balance.qty, Decimal("7.000"))
        self.assertEqual(movement.movement_type, StockMovement.MovementType.RETURN)
        self.assertEqual(movement.recipient, self.recipient)
        self.assertEqual(movement.department, self.usage_place.name)
        self.assertEqual(movement.comment, "")
        self.assertIsNotNone(self.item.barcode)

    def test_receive_uses_default_location_when_locations_disabled(self):
        self.disable_locations()

        response = self.client.get(reverse("stock_return"))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("location", response.context["form"].fields)
        response = self.client.post(
            reverse("stock_return"),
            {
                "item": self.item.pk,
                "warehouse": self.warehouse.pk,
                "qty": "7.000",
                "recipient": self.recipient.pk,
                "department": self.usage_place.pk,
                "comment": "",
                "occurred_at": timezone.now().strftime("%Y-%m-%dT%H:%M"),
            },
        )

        self.assertEqual(response.status_code, 302)
        default_location = get_default_location_for_warehouse(self.warehouse)
        movement = StockMovement.objects.get(department=self.usage_place.name)
        self.assertEqual(movement.movement_type, StockMovement.MovementType.RETURN)
        self.assertEqual(movement.recipient, self.recipient)
        self.assertEqual(movement.department, self.usage_place.name)
        self.assertEqual(movement.comment, "")
        self.assertEqual(movement.destination_location, default_location)
        self.assertEqual(movement.destination_location.name, DEFAULT_LOCATION_NAME)
        self.assertEqual(
            StockBalance.objects.get(item=self.item, location=default_location).qty,
            Decimal("7.000"),
        )

    def test_receive_page_contains_tablet_scan_card(self):
        response = self.client.get(reverse("stock_return"))
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

    def test_stock_receive_get_barcode_requires_explicit_warehouse_destination(self):
        response = self.client.get(
            f'{reverse("stock_receive")}?barcode={self.item.barcode.barcode}'
        )
        form = response.context["form"]
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(form.initial["item"], self.item)
        self.assertNotIn("warehouse", form.initial)
        self.assertNotIn("location", form.initial)
        self.assertContains(response, "Склад")
        self.assertNotContains(response, "Локація")
        self.assertIn('name="warehouse"', html)
        self.assertNotIn('name="location"', html)
        self.assertContains(response, self.warehouse.name)
        self.assertContains(response, self.destination_warehouse.name)
        self.assertNotContains(response, "Дані для повернення визначено автоматично.")

    def test_stock_receive_posts_to_user_selected_warehouse_destination(self):
        get_response = self.client.get(
            f'{reverse("stock_receive")}?barcode={self.item.barcode.barcode}'
        )
        token = get_response.context["operation_token"]

        response = self.client.post(
            reverse("stock_receive"),
            {
                "operation_token": token,
                "item": self.item.pk,
                "warehouse": self.destination_warehouse.pk,
                "location": self.destination_location.pk,
                "qty": "4.000",
                "comment": "",
                "occurred_at": timezone.now().strftime("%Y-%m-%dT%H:%M"),
            },
        )

        self.assertEqual(response.status_code, 302)
        movement = StockMovement.objects.get(movement_type=StockMovement.MovementType.IN)
        expected_destination = get_default_location_for_warehouse(
            self.destination_warehouse
        )
        self.assertEqual(movement.destination_location, expected_destination)
        self.assertFalse(
            StockBalance.objects.filter(item=self.item, location=self.location).exists()
        )
        self.assertFalse(
            StockBalance.objects.filter(
                item=self.item, location=self.destination_location
            ).exists()
        )
        self.assertEqual(
            StockBalance.objects.get(
                item=self.item, location=expected_destination
            ).qty,
            Decimal("4.000"),
        )

    def test_english_receive_page_has_no_ukrainian_new_submit_messages(self):
        response = self.client.get(
            f'/en/stock/receive/?barcode={self.item.barcode.barcode}'
        )
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn('name="operation_token"', html)
        self.assertIn('data-saving-label="Saving..."', html)
        self.assertNotIn("Збереження...", html)
        self.assertNotIn("Операція вже була збережена.", html)

    def test_receive_get_barcode_prefills_item(self):
        response = self.client.get(
            f'{reverse("stock_return")}?barcode={self.item.barcode.barcode}'
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form"].initial["item"], self.item)
        self.assertIn("warehouse", response.context["form"].initial)
        self.assertIn("location", response.context["form"].initial)
        self.assertContains(response, "Очистити")
        self.assertContains(response, f'href="{reverse("stock_return")}"', html=False)
        self.assertContains(response, "Знайдений товар")
        self.assertContains(response, "Назва товару")
        self.assertContains(response, self.item.name)
        self.assertContains(response, self.item.barcode.barcode)
        self.assertContains(response, "Дані для повернення визначено автоматично.")

    def test_receive_get_barcode_contains_operation_token_and_disable_submit_attrs(self):
        response = self.client.get(
            f'{reverse("stock_return")}?barcode={self.item.barcode.barcode}'
        )
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["operation_token"])
        self.assertIn('name="operation_token"', html)
        self.assertIn('value="%s"' % response.context["operation_token"], html)
        self.assertIn('data-disable-on-submit', html)
        self.assertIn('data-submit-button', html)
        self.assertIn('data-saving-label="Збереження..."', html)

    def test_receive_duplicate_post_with_same_operation_token_redirects_without_second_movement(self):
        get_response = self.client.get(
            f'{reverse("stock_return")}?barcode={self.item.barcode.barcode}'
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
            "recipient": self.recipient.pk,
            "department": self.usage_place.pk,
            "comment": "",
            "occurred_at": form.initial["occurred_at"],
        }

        first_response = self.client.post(reverse("stock_return"), data)
        second_response = self.client.post(reverse("stock_return"), data)

        self.assertEqual(first_response.status_code, 302)
        self.assertEqual(second_response.status_code, 302)
        self.assertEqual(second_response["Location"], first_response["Location"])
        self.assertEqual(
            StockMovement.objects.count(),
            movement_count + 1,
        )

    def test_receive_form_hides_manual_warehouse_location_and_service_fields(self):
        response = self.client.get(
            f'{reverse("stock_return")}?barcode={self.item.barcode.barcode}'
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, ">Склад</label>")
        self.assertNotContains(response, ">Локація</label>")
        self.assertNotContains(response, "Документ")
        self.assertNotContains(response, "Коментар")
        self.assertNotContains(response, "Дата операції")
        self.assertNotContains(response, "Надрукувати етикетку")
        self.assertContains(response, "Кількість")
        self.assertNotContains(response, "Хто повертає товар")
        self.assertNotContains(response, "Цех / місце використання")

    def test_receive_form_lists_only_active_usage_places_and_touch_fields(self):
        form = StockReceiveForm()

        self.assertNotIn("recipient", form.fields)
        self.assertNotIn("department", form.fields)
        self.assertEqual(
            form.fields["qty"].widget.attrs["class"],
            "form-control form-control-lg text-center",
        )
        self.assertEqual(form.fields["qty"].widget.attrs["min"], "1")
        self.assertEqual(form.fields["qty"].widget.attrs["step"], "1")
        self.assertEqual(form.fields["qty"].widget.attrs["inputmode"], "numeric")

    def test_receive_quantity_stepper_controls_and_attrs(self):
        response = self.client.get(
            f'{reverse("stock_return")}?barcode={self.item.barcode.barcode}'
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

    def test_receive_without_default_return_location_hides_submit(self):
        Location.objects.update(is_active=False)

        response = self.client.get(
            f'{reverse("stock_return")}?barcode={self.item.barcode.barcode}'
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, "Товар знайдено, але локацію для повернення не налаштовано."
        )
        self.assertFalse(response.context["can_submit_receive"])
        self.assertNotContains(response, "Повернути товар")

    def test_receive_result_page_is_simple_for_tablet(self):
        movement = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.RETURN,
            item=self.item,
            qty=Decimal("2.000"),
            destination_location=self.location,
            recipient=self.recipient,
            department=self.usage_place.name,
            comment="",
            occurred_at=timezone.datetime(
                2026, 5, 13, 10, 6, 32, tzinfo=timezone.get_current_timezone()
            ),
        )

        response = self.client.get(reverse("stock_receive_result", args=[movement.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Повернення товару")
        self.assertContains(response, "✓")
        self.assertContains(response, "Товар повернено")
        self.assertContains(response, self.item.name)
        self.assertContains(response, "2,000")
        self.assertContains(response, "Хто повертає")
        self.assertContains(response, self.recipient.name)
        self.assertContains(response, "Місце використання")
        self.assertContains(response, self.usage_place.name)
        self.assertContains(response, "Дата і час операції")
        self.assertContains(response, "2026")
        self.assertContains(response, "Новий прихід товару")
        self.assertContains(response, "На головний екран")
        self.assertContains(response, reverse("dashboard"))
        self.assertContains(response, "Друкувати контрольний талон")
        self.assertContains(
            response,
            f'{reverse("stock_movement_print", kwargs={"pk": movement.pk})}?autoprint=1',
        )
        html = response.content.decode()
        self.assertNotIn(">Склад</dt>", html)
        self.assertNotIn(">Локація</dt>", html)
        self.assertNotIn("До рухів товарів", html)
        self.assertNotIn("До залишків", html)
        self.assertNotIn(">Документ</dt>", html)
        self.assertNotIn(">Коментар</dt>", html)
        self.assertNotIn("До рухів товарів</a>", html)
        self.assertNotIn("До залишків</a>", html)

    def test_english_receive_result_page_has_no_ukrainian_tablet_phrases(self):
        movement = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.RETURN,
            item=self.item,
            qty=Decimal("2.000"),
            destination_location=self.location,
            recipient=self.recipient,
            department="Sales",
            comment="",
        )

        response = self.client.get(f"/en/stock/receive/{movement.pk}/")
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("Return item", html)
        self.assertIn("Item returned", html)
        self.assertIn("✓", html)
        self.assertIn("Who returns", html)
        self.assertIn("Place of use", html)
        self.assertIn("Print control slip", html)
        self.assertIn("New stock receipt", html)
        self.assertIn("Home", html)
        for phrase in ["Товар повернено", "Хто повертає", "Місце використання", "Новий прихід товару"]:
            self.assertNotIn(phrase, html)

    def test_english_receive_page_has_no_ukrainian_tablet_phrases(self):
        response = self.client.get(
            f'/en/stock/receive/?barcode={self.item.barcode.barcode}'
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Scan item")
        self.assertContains(response, "Found item")
        self.assertContains(response, "Quantity")
        self.assertNotContains(response, "Recipient")
        self.assertContains(response, "Warehouse")
        self.assertContains(response, "Location")
        self.assertContains(response, "Stock receipt")
        self.assertNotContains(response, "Return data was selected automatically.")
        self.assertContains(response, 'data-qty-decrement')
        self.assertContains(response, 'data-qty-increment')
        self.assertContains(response, 'inputmode="numeric"')
