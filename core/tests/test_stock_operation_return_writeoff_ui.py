from .stock_operations_ui_utils import *  # noqa: F403


class StockIssueInterfaceTests(StockIssueInterfaceTestBase):
    def test_stock_receive_result_page_is_simple_for_tablet(self):
        self.client.force_login(self.storekeeper)
        response = self.client.post(
            reverse("stock_return"),
            {
                "item": self.item.pk,
                "warehouse": self.warehouse.pk,
                "location": self.location.pk,
                "qty": "2.000",
                "recipient": self.recipient.pk,
                "department": self.usage_place.pk,
                "comment": "",
                "occurred_at": "2026-05-13T10:06",
            },
            follow=True,
        )

        movement = StockMovement.objects.get(department=self.usage_place.name)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(movement.movement_type, StockMovement.MovementType.RETURN)
        self.assertEqual(movement.recipient, self.recipient)
        self.assertEqual(movement.department, self.usage_place.name)
        self.assertEqual(movement.comment, "")
        self.assertContains(response, "Повернення товару")
        self.assertContains(response, "✓")
        self.assertContains(response, "Товар повернено")
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

    def test_stock_writeoff_rejects_quantity_greater_than_balance_with_alert(self):
        self.client.force_login(self.storekeeper)
        movement_count = StockMovement.objects.count()
        response = self.client.post(
            "/uk/stock/writeoff/",
            {
                "item": self.item.pk,
                "warehouse": self.warehouse.pk,
                "location": self.location.pk,
                "qty": "99.000",
                "writeoff_reason": "other",
                "document_number": "",
                "comment": "",
                "occurred_at": "2026-01-15T12:00",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Недостатньо залишку для списання")
        self.assertContains(response, "alert-danger")
        self.assertEqual(StockMovement.objects.count(), movement_count)
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.qty, Decimal("7.000"))

    def test_stock_writeoff_page_available_to_storekeeper(self):
        self.client.force_login(self.storekeeper)
        response = self.client.get("/uk/stock/writeoff/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Списання товару")
        self.assertContains(response, "writeoff-barcode-scanner")

    def test_stock_writeoff_post_decreases_balance_and_creates_writeoff_movement(self):
        self.client.force_login(self.storekeeper)
        response = self.client.post(
            "/uk/stock/writeoff/",
            {
                "item": self.item.pk,
                "warehouse": self.warehouse.pk,
                "location": self.location.pk,
                "qty": "2.000",
                "writeoff_reason": "damaged",
                "document_number": "WO-1",
                "comment": "Damaged cable",
                "occurred_at": "2026-01-15T13:00",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.balance.refresh_from_db()
        movement = StockMovement.objects.latest("id")
        self.assertEqual(self.balance.qty, Decimal("5.000"))
        self.assertEqual(movement.movement_type, StockMovement.MovementType.WRITEOFF)
        self.assertEqual(movement.source_location, self.location)
        self.assertIsNone(movement.destination_location)
        self.assertIn("Причина списання: Зіпсовано", movement.comment)
        self.assertIn("Номер документа: WO-1", movement.comment)
        self.assertIn("Коментар: Damaged cable", movement.comment)

    def test_stock_writeoff_result_page_shows_item_quantity_and_location(self):
        self.client.force_login(self.storekeeper)
        movement = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.WRITEOFF,
            item=self.item,
            qty=Decimal("2.000"),
            source_location=self.location,
            comment="Причина списання: Зіпсовано",
        )

        response = self.client.get(f"/uk/stock/writeoff/{movement.pk}/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Кабель ВВГ")
        self.assertContains(response, "2,000")
        self.assertContains(response, "A1")

    def test_auditor_cannot_access_stock_writeoff_form(self):
        self.client.force_login(self.auditor)
        response = self.client.get("/uk/stock/writeoff/")

        self.assertEqual(response.status_code, 403)

class StockOperationWorkflowTests(StockOperationWorkflowTestBase):
    def test_writeoff_uses_default_location_when_locations_disabled(self):
        from ..services.stock import receive_stock

        self.disable_locations()
        default_location = get_default_location_for_warehouse(self.warehouse)
        receive_stock(item=self.item, location=default_location, qty=Decimal("5.000"))

        response = self.client.post(
            reverse("stock_writeoff"),
            {
                "item": self.item.pk,
                "warehouse": self.warehouse.pk,
                "qty": "2.000",
                "writeoff_reason": "other",
                "document_number": "",
                "comment": "Default writeoff",
                "occurred_at": timezone.now().strftime("%Y-%m-%dT%H:%M"),
            },
        )

        self.assertEqual(response.status_code, 302)
        movement = StockMovement.objects.latest("id")
        self.assertEqual(movement.movement_type, StockMovement.MovementType.WRITEOFF)
        self.assertEqual(movement.source_location, default_location)
        self.assertEqual(
            StockBalance.objects.get(item=self.item, location=default_location).qty,
            Decimal("3.000"),
        )

    def test_return_form_lists_only_active_usage_places_and_touch_fields(self):
        form = StockReturnForm()
        choices = list(form.fields["department"].queryset)

        self.assertIn("recipient", form.fields)
        self.assertIn("department", form.fields)
        self.assertTrue(form.fields["recipient"].required)
        self.assertTrue(form.fields["department"].required)
        self.assertIn(self.usage_place, choices)
        self.assertNotIn(self.inactive_usage_place, choices)

    def test_return_form_requires_recipient_and_department(self):
        form = StockReturnForm(
            data={
                "item": self.item.pk,
                "warehouse": self.warehouse.pk,
                "location": self.location.pk,
                "qty": "1.000",
                "recipient": "",
                "department": "",
                "comment": "",
                "occurred_at": "2026-01-15T10:00",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("recipient", form.errors)
        self.assertIn("department", form.errors)

    def test_return_form_cleans_department_to_usage_place_name(self):
        form = StockReturnForm(
            data={
                "item": self.item.pk,
                "warehouse": self.warehouse.pk,
                "location": self.location.pk,
                "qty": "1.000",
                "recipient": self.recipient.pk,
                "department": self.usage_place.pk,
                "comment": "",
                "occurred_at": "2026-01-15T10:00",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["department"], "Sales")

    def test_control_slip_shows_return_recipient_and_department(self):
        movement = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.RETURN,
            item=self.item,
            qty=Decimal("1.000"),
            destination_location=self.location,
            recipient=self.recipient,
            department="Компресорна",
            comment="Legacy comment place",
        )

        response = self.client.get(
            reverse("stock_movement_print", kwargs={"pk": movement.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Контрольний талон складської операції")
        self.assertContains(response, "ID операції")
        self.assertContains(response, "Тип операції")
        self.assertContains(response, "Дата і час операції")
        self.assertContains(response, "Товар")
        self.assertContains(response, "Внутрішній код")
        if self.item.barcode_id:
            self.assertContains(response, "Штрихкод")
        self.assertContains(response, "Кількість")
        self.assertContains(response, "Хто повернув товар")
        self.assertContains(response, self.recipient.name)
        self.assertContains(response, "Цех / місце використання")
        self.assertContains(response, "Компресорна")
        self.assertNotContains(response, "Legacy comment place")
        self.assertNotContains(response, "Коментар / документ")

    def test_english_return_control_slip_has_no_ukrainian_return_labels(self):
        movement = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.RETURN,
            item=self.item,
            qty=Decimal("1.000"),
            destination_location=self.location,
            recipient=self.recipient,
            department="Sales",
            comment="",
        )

        response = self.client.get(f"/en/stock/movements/{movement.pk}/print/")
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("Warehouse operation control slip", html)
        self.assertIn("Operation ID", html)
        self.assertIn("Operation type", html)
        self.assertIn("Operation date and time", html)
        self.assertIn("Item", html)
        self.assertIn("Internal code", html)
        self.assertIn("Quantity", html)
        self.assertIn("Who returned the item", html)
        self.assertTrue("Department / place of use" in html or "Місце використання" in html)
