from .stock_operations_ui_utils import *  # noqa: F403


class StockTransferFormTests(StockTransferFormTestBase):
    def test_source_location_must_belong_to_source_warehouse(self):
        form = StockTransferForm(
            data=self.form_data(source_location=self.other_location.pk)
        )

        self.assertFalse(form.is_valid())
        self.assertIn("source_location", form.errors)

    def test_destination_location_must_belong_to_destination_warehouse(self):
        form = StockTransferForm(
            data=self.form_data(destination_location=self.source_location.pk)
        )

        self.assertFalse(form.is_valid())
        self.assertIn("destination_location", form.errors)

    def test_same_source_and_destination_location_is_invalid(self):
        form = StockTransferForm(
            data=self.form_data(
                destination_warehouse=self.source_warehouse.pk,
                destination_location=self.source_location.pk,
            )
        )

        self.assertFalse(form.is_valid())
        self.assertIn("__all__", form.errors)

    def test_qty_must_be_positive(self):
        form = StockTransferForm(data=self.form_data(qty="0.000"))

        self.assertFalse(form.is_valid())
        self.assertIn("qty", form.errors)

class StockOperationWorkflowTests(StockOperationWorkflowTestBase):
    def test_transfer_stock_ui_creates_transfer_movement(self):
        from ..services.stock import receive_stock

        receive_stock(item=self.item, location=self.location, qty=Decimal("5.000"))
        get_response = self.client.get(reverse("stock_transfer"))
        response = self.client.post(
            reverse("stock_transfer"),
            {
                "item": self.item.pk,
                "source_warehouse": self.warehouse.pk,
                "source_location": self.location.pk,
                "destination_warehouse": self.destination_warehouse.pk,
                "destination_location": self.destination_location.pk,
                "qty": "2.000",
                "comment": "UI transfer",
                "occurred_at": get_response.context["form"]["occurred_at"].value(),
            },
        )

        self.assertEqual(response.status_code, 302)
        movement = StockMovement.objects.get(comment="UI transfer")
        self.assertEqual(movement.movement_type, StockMovement.MovementType.TRANSFER)
        self.assertEqual(movement.source_location, self.location)
        expected_destination = get_default_location_for_warehouse(
            self.destination_warehouse
        )
        self.assertEqual(movement.destination_location, expected_destination)
        self.assertEqual(
            StockBalance.objects.get(item=self.item, location=self.location).qty,
            Decimal("3.000"),
        )
        self.assertEqual(
            StockBalance.objects.get(
                item=self.item, location=expected_destination
            ).qty,
            Decimal("2.000"),
        )

    def test_transfer_form_renders_required_operation_date(self):
        response = self.client.get(reverse("stock_transfer"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="occurred_at"')
        self.assertContains(response, 'type="hidden"')

    def test_stock_operation_views_store_request_user_as_performer(self):
        from ..services.stock import receive_stock

        response = self.client.post(
            reverse("stock_receive"),
            {
                "item": self.item.pk,
                "warehouse": self.warehouse.pk,
                "location": self.location.pk,
                "qty": "2.000",
                "comment": "Authorship receive",
                "occurred_at": timezone.now().strftime("%Y-%m-%dT%H:%M"),
            },
        )
        self.assertEqual(response.status_code, 302)
        receive_movement = StockMovement.objects.get(comment="Authorship receive")
        self.assertEqual(receive_movement.performed_by, self.user)

        response = self.client.post(
            reverse("stock_issue"),
            {
                "item": self.item.pk,
                "warehouse": self.warehouse.pk,
                "location": self.location.pk,
                "qty": "1.000",
                "recipient": self.recipient.pk,
                "issue_reason": StockMovement.IssueReason.OTHER,
                "department": self.usage_place.pk,
                "document_number": "AUTH-ISSUE",
                "comment": "Authorship issue",
                "occurred_at": timezone.now().strftime("%Y-%m-%dT%H:%M"),
            },
        )
        self.assertEqual(response.status_code, 302)
        issue_movement = StockMovement.objects.get(document_number="AUTH-ISSUE")
        self.assertEqual(issue_movement.performed_by, self.user)

        receive_stock(item=self.item, location=self.location, qty=Decimal("3.000"))
        response = self.client.post(reverse("stock_transfer"), self._transfer_data(comment="Authorship transfer", qty="1.000"))
        self.assertEqual(response.status_code, 302)
        transfer_movement = StockMovement.objects.get(comment="Authorship transfer")
        self.assertEqual(transfer_movement.performed_by, self.user)

    def test_superuser_only_audit_log_page(self):
        superuser = get_user_model().objects.create_superuser(
            username="root", password="pass", email="root@example.com"
        )
        admin = get_user_model().objects.create_user("warehouse-admin", password="pass")
        storekeeper = get_user_model().objects.create_user("warehouse-user", password="pass")
        AuditLog.objects.create(
            actor=self.user,
            action="stock_movement.created",
            object_type="StockMovement",
            object_id="1",
            object_repr="Movement",
            changes={"qty": "1.000"},
            ip_address="127.0.0.1",
        )

        self.client.force_login(superuser)
        response = self.client.get(reverse("management_audit"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "audit-log-table")
        self.assertContains(response, "Movement")
        self.assertContains(response, "127.0.0.1")
        self.assertNotContains(response, ">root<")
        self.assertNotContains(response, "root@example.com")

        self.client.force_login(admin)
        self.assertEqual(self.client.get(reverse("management_audit")).status_code, 403)

        self.client.force_login(storekeeper)
        self.assertEqual(self.client.get(reverse("management_audit")).status_code, 403)

    def test_stock_movement_journal_shows_performed_by_column(self):
        movement = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.IN,
            item=self.item,
            qty=Decimal("1.000"),
            destination_location=self.location,
            performed_by=self.user,
        )
        self.user.first_name = "Workflow"
        self.user.last_name = "Performer"
        self.user.save(update_fields=["first_name", "last_name"])

        response = self.client.get(reverse("movement_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Workflow Performer")

    def test_transfer_rejects_insufficient_source_stock_with_ukrainian_alert(self):
        StockBalance.objects.create(
            item=self.item, location=self.location, qty=Decimal("1.000")
        )
        movement_count = StockMovement.objects.filter(
            movement_type=StockMovement.MovementType.TRANSFER
        ).count()

        response = self.client.post("/uk/stock/transfer/", self._transfer_data())

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/stock_transfer_form.html")
        self.assertContains(response, "alert-danger")
        self.assertEqual(
            StockMovement.objects.filter(
                movement_type=StockMovement.MovementType.TRANSFER
            ).count(),
            movement_count,
        )
        self.assertEqual(
            StockBalance.objects.get(item=self.item, location=self.location).qty,
            Decimal("1.000"),
        )
        self.assertFalse(
            StockBalance.objects.filter(
                item=self.item, location=self.destination_location
            ).exists()
        )

    def test_transfer_insufficient_stock_uses_english_message_on_english_page(self):
        StockBalance.objects.create(
            item=self.item, location=self.location, qty=Decimal("1.000")
        )

        response = self.client.post("/en/stock/transfer/", self._transfer_data())
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "Not enough stock at the source location. Check stock before transfer.",
            html,
        )
        self.assertIn("alert-danger", html)
        self.assertNotIn("Недостатньо залишку", html)
        self.assertFalse(
            StockMovement.objects.filter(
                movement_type=StockMovement.MovementType.TRANSFER,
                comment="Insufficient transfer",
            ).exists()
        )

    def test_transfer_result_page_shows_item_quantity_source_and_destination(self):
        movement = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.TRANSFER,
            item=self.item,
            qty=Decimal("2.000"),
            source_location=self.location,
            destination_location=self.destination_location,
            comment="Result transfer",
        )

        response = self.client.get(reverse("stock_transfer_result", args=[movement.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Workflow item")
        self.assertContains(response, "2")
        self.assertContains(response, "Workflow location")
        self.assertContains(response, "Workflow destination location")

    def test_initial_balance_uses_default_location_when_locations_disabled(self):
        self.disable_locations()

        response = self.client.post(
            reverse("stock_initial"),
            {
                "item": self.item.pk,
                "warehouse": self.warehouse.pk,
                "qty": "4.000",
                "comment": "Default initial",
                "occurred_at": timezone.now().strftime("%Y-%m-%dT%H:%M"),
            },
        )

        self.assertEqual(response.status_code, 302)
        default_location = get_default_location_for_warehouse(self.warehouse)
        movement = StockMovement.objects.get(comment="Default initial")
        self.assertEqual(
            movement.movement_type, StockMovement.MovementType.INITIAL_BALANCE
        )
        self.assertEqual(movement.destination_location, default_location)
        self.assertEqual(default_location.name, DEFAULT_LOCATION_NAME)
        self.assertEqual(
            StockBalance.objects.get(item=self.item, location=default_location).qty,
            Decimal("4.000"),
        )

    def test_transfer_uses_default_locations_when_locations_disabled(self):
        from ..services.stock import receive_stock

        self.disable_locations()
        source_default = get_default_location_for_warehouse(self.warehouse)
        destination_default = get_default_location_for_warehouse(
            self.destination_warehouse
        )
        receive_stock(item=self.item, location=source_default, qty=Decimal("5.000"))

        response = self.client.post(
            reverse("stock_transfer"),
            {
                "item": self.item.pk,
                "source_warehouse": self.warehouse.pk,
                "destination_warehouse": self.destination_warehouse.pk,
                "qty": "2.000",
                "comment": "Default transfer",
                "occurred_at": timezone.now().strftime("%Y-%m-%dT%H:%M"),
            },
        )

        self.assertEqual(response.status_code, 302)
        movement = StockMovement.objects.get(comment="Default transfer")
        self.assertEqual(movement.movement_type, StockMovement.MovementType.TRANSFER)
        self.assertEqual(movement.source_location, source_default)
        self.assertEqual(movement.destination_location, destination_default)
        self.assertEqual(movement.source_location.name, DEFAULT_LOCATION_NAME)
        self.assertEqual(movement.destination_location.name, DEFAULT_LOCATION_NAME)
        self.assertEqual(
            StockBalance.objects.get(item=self.item, location=source_default).qty,
            Decimal("3.000"),
        )
        self.assertEqual(
            StockBalance.objects.get(item=self.item, location=destination_default).qty,
            Decimal("2.000"),
        )

    def test_transfer_same_warehouse_is_invalid_when_locations_disabled(self):
        self.disable_locations()
        movement_count = StockMovement.objects.count()

        response = self.client.post(
            "/uk/stock/transfer/",
            {
                "item": self.item.pk,
                "source_warehouse": self.warehouse.pk,
                "destination_warehouse": self.warehouse.pk,
                "qty": "1.000",
                "comment": "Same warehouse transfer",
                "occurred_at": timezone.now().strftime("%Y-%m-%dT%H:%M"),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "alert-danger")
        self.assertEqual(StockMovement.objects.count(), movement_count)

    def test_transfer_same_warehouse_is_invalid_when_locations_enabled(self):
        other_location = self.warehouse.locations.create(name="Other same warehouse")
        movement_count = StockMovement.objects.count()

        response = self.client.post(
            "/uk/stock/transfer/",
            {
                "item": self.item.pk,
                "source_warehouse": self.warehouse.pk,
                "source_location": self.location.pk,
                "destination_warehouse": self.warehouse.pk,
                "destination_location": other_location.pk,
                "qty": "1.000",
                "comment": "Same warehouse location transfer",
                "occurred_at": timezone.now().strftime("%Y-%m-%dT%H:%M"),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "alert-danger")
        self.assertEqual(StockMovement.objects.count(), movement_count)

    def test_transfer_form_explains_when_user_has_one_accessible_warehouse(self):
        single_user = get_user_model().objects.create_user("single-warehouse", password="pass")
        single_user.groups.set(self.user.groups.all())
        grant_warehouse_access(single_user, self.warehouse, can_delegate=True)
        self.client.force_login(single_user)

        response = self.client.get(reverse("stock_transfer"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Для переміщення потрібен доступ щонайменше до двох складів.",
        )

    def test_use_locations_true_keeps_location_fields_visible_for_superuser(self):
        superuser = get_user_model().objects.create_superuser(
            "workflow-root", "root@example.com", "pass"
        )
        self.client.force_login(superuser)

        receive_response = self.client.get(reverse("stock_return"))
        transfer_response = self.client.get(reverse("stock_transfer"))

        self.assertIn("location", receive_response.context["form"].fields)
        self.assertIn("source_location", transfer_response.context["form"].fields)
        self.assertIn("destination_location", transfer_response.context["form"].fields)

    def test_initial_balance_creates_stock_movement(self):
        response = self.client.post(
            reverse("stock_initial"),
            {
                "item": self.item.pk,
                "warehouse": self.warehouse.pk,
                "location": self.location.pk,
                "qty": "3.000",
                "comment": "Initial UI",
                "occurred_at": timezone.now().strftime("%Y-%m-%dT%H:%M"),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            StockMovement.objects.filter(
                comment="Initial UI",
                movement_type=StockMovement.MovementType.INITIAL_BALANCE,
            ).exists()
        )

class StockOperationFormsSmokeTests(StockOperationFormsSmokeTestBase):
    def test_operation_forms_have_unified_card(self):
        pages = [
            reverse("stock_issue"),
            reverse("stock_return"),
            reverse("stock_receive"),
            reverse("stock_transfer"),
            reverse("stock_writeoff"),
        ]
        for page in pages:
            with self.subTest(page=page):
                response = self.client.get(page)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'operation-form-card')

    def test_primary_actions_exist(self):
        checks = [
            ("stock_issue", "Знайти товар"),
            ("stock_return", "Знайти товар"),
            ("stock_receive", "Знайти товар"),
            ("stock_transfer", "Перемістити"),
            ("stock_writeoff", "Списати"),
            ("stock_initial", "Зберегти"),
        ]
        for name, label in checks:
            with self.subTest(name=name):
                self.assertContains(self.client.get(reverse(name)), label)

class ListLayoutSmokeTests(ListLayoutSmokeTestBase):
    def test_item_list_has_unified_layout_classes(self):
        response = self.client.get(reverse("item_list"))
        self.assertContains(response, "list-page")
        self.assertContains(response, "data-table-card")

    def test_stock_lists_have_filter_and_table_cards(self):
        balance_response = self.client.get(reverse("stockbalance_list"))
        self.assertContains(balance_response, "data-table-card")
        self.assertContains(balance_response, "table-filter-heading")

        for name in ["movement_list"]:
            response = self.client.get(reverse(name))
            self.assertContains(response, "data-table-card")
            self.assertContains(response, "table-filter-toolbar")
            self.assertContains(response, "table-filter-heading")

    def test_printer_list_preserves_error_or_empty_states(self, *_):
        response = self.client.get(reverse("printer_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-table-card")

    def test_labeltemplate_list_has_edit_and_preview_actions(self):
        template = LabelTemplate.objects.create(name="Layout", is_default=True)
        response = self.client.get(reverse("labeltemplate_list"))
        self.assertContains(response, reverse("labeltemplate_update", args=[template.pk]))
        self.assertContains(response, reverse("labeltemplate_preview", args=[template.pk]))
