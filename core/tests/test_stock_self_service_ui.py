from .stock_operations_ui_utils import *  # noqa: F403


class StockIssueInterfaceTests(StockIssueInterfaceTestBase):
    def test_storekeeper_self_service_stock_pages_hide_sidebar_and_admin_links(self):
        self.client.force_login(self.storekeeper)
        out_movement = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.OUT,
            item=self.item,
            qty=Decimal("1.000"),
            source_location=self.location,
            recipient=self.recipient,
            department=self.usage_place.name,
        )
        return_movement = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.RETURN,
            item=self.item,
            qty=Decimal("1.000"),
            destination_location=self.location,
            recipient=self.recipient,
            department=self.usage_place.name,
        )
        pages = [
            reverse("dashboard"),
            reverse("stock_issue"),
            reverse("stock_return"),
            reverse("stock_issue_result", kwargs={"pk": out_movement.pk}),
            reverse("stock_receive_result", kwargs={"pk": return_movement.pk}),
        ]
        for path in pages:
            with self.subTest(path=path):
                self.assert_self_service_shell(self.client.get(path))

        print_response = self.client.get(
            reverse("stock_movement_print", kwargs={"pk": out_movement.pk})
        )
        print_html = print_response.content.decode()
        self.assertEqual(print_response.status_code, 200)
        self.assertNotIn('class="sidebar-link', print_html)
        self.assertNotIn("Навігація", print_html)
        self.assertNotIn(reverse("management_dashboard"), print_html)

    def test_storekeeper_tablet_issue_and_receive_controls_remain_touch_friendly(self):
        self.client.force_login(self.storekeeper)
        for url_name in ["stock_issue", "stock_return"]:
            with self.subTest(url_name=url_name):
                response = self.client.get(
                    f'{reverse(url_name)}?barcode={self.item.barcode.barcode}'
                )
                html = response.content.decode()

                self.assertEqual(response.status_code, 200)
                self.assertIn('name="barcode"', html)
                self.assertIn('autocomplete="off"', html)
                self.assertNotIn('autofocus', html)
                self.assertIn('data-qty-stepper', html)
                self.assertIn('data-qty-decrement', html)
                self.assertIn('data-qty-increment', html)
                self.assertIn('class="form-select form-select-lg"', html)
                self.assertIn('name="recipient"', html)
                self.assertIn('name="department"', html)
                self.assertIn('data-disable-on-submit', html)
                self.assertIn('data-submit-button', html)
                self.assertIn('data-saving-label="Збереження..."', html)

    def test_pr17_stock_pages_available_to_storekeeper(self):
        self.client.force_login(self.storekeeper)
        for url_name in [
            "stock_receive",
            "stock_issue",
            "stock_initial",
            "movement_list",
            "stockbalance_list",
            "item_list",
            "help",
        ]:
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 200, url_name)

    def test_storekeeper_sees_stock_issue_but_not_recipients_in_main_menu(self):
        self.client.force_login(self.storekeeper)
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Взяти товар")
        self.assertNotContains(response, "Працівники / отримувачі")

    def test_storekeeper_dashboard_focuses_on_issue_and_return(self):
        self.client.force_login(self.storekeeper)
        response = self.client.get("/uk/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Взяти товар")
        self.assertContains(response, "Повернути товар")
        main_html = response.content.decode().split('<main class="col-12">', 1)[1]
        self.assertEqual(main_html.count('<a class="card self-service-action-card'), 2)
        self.assertNotIn("Списання товару", main_html)
        self.assertNotIn("Переміщення товару", main_html)
        self.assertNotIn("Журнал операцій", main_html)
        self.assertNotIn("Залишки на складі", main_html)
        self.assertNotIn("Інвентаризація", main_html)
        self.assertNotIn("Робоче місце комірника", main_html)
        self.assertNotIn("Комірник", main_html)

    def test_auditor_does_not_see_stock_writeoff_on_dashboard(self):
        self.client.force_login(self.auditor)
        response = self.client.get("/uk/")

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Списання товару")

    def test_stock_movement_print_page_is_read_only_and_contains_control_data(self):
        self.client.force_login(self.storekeeper)
        movement = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.OUT,
            item=self.item,
            qty=Decimal("1.250"),
            source_location=self.location,
            recipient=self.recipient,
            document_number="CAM-1",
            comment="Camera check",
            occurred_at=timezone.datetime(
                2026, 5, 13, 10, 6, 32, tzinfo=timezone.get_current_timezone()
            ),
        )
        movement_count = StockMovement.objects.count()
        movement_qty = movement.qty
        balance_qty = self.balance.qty

        response = self.client.get(
            reverse("stock_movement_print", kwargs={"pk": movement.pk})
        )
        self.balance.refresh_from_db()
        movement.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Контрольний талон складської операції")
        self.assertContains(response, self.item.name)
        self.assertContains(response, "1,250")
        self.assertContains(response, "2026-05-13 10:06:32")
        self.assertContains(response, "Хто взяв товар")
        self.assertContains(response, self.recipient.name)
        self.assertContains(response, "Час для перевірки по відео:")
        self.assertNotContains(response, ">Склад</dt>")
        self.assertNotContains(response, ">Локація</dt>")
        self.assertNotContains(response, "CAM-1")
        self.assertNotContains(response, "Camera check")
        self.assertNotContains(response, "Коментар / документ")
        self.assertNotContains(response, "Видав")
        self.assertNotContains(response, "Отримав")
        self.assertNotContains(response, "Перевірив")
        self.assertEqual(StockMovement.objects.count(), movement_count)
        self.assertEqual(movement.qty, movement_qty)
        self.assertEqual(self.balance.qty, balance_qty)

    def test_russian_stock_movement_print_page_uses_russian_control_labels(self):
        self.client.force_login(self.storekeeper)
        movement = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.IN,
            item=self.item,
            qty=Decimal("1.000"),
            destination_location=self.location,
            occurred_at=timezone.datetime(
                2026, 5, 13, 10, 6, 32, tzinfo=timezone.get_current_timezone()
            ),
        )

        response = self.client.get(
            f"/ru/stock/movements/{movement.pk}/print/?autoprint=1"
        )
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("Время для проверки по видео", html)
        self.assertIn("Принял на склад", html)
        self.assertIn("Ответственный", html)
        self.assertNotIn("Час для перевірки по відео", html)
        self.assertNotIn("Прийняв на склад", html)
        self.assertNotIn("Відповідальний", html)

    def test_stock_movement_print_page_autoprint_is_opt_in(self):
        self.client.force_login(self.storekeeper)
        movement = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.OUT,
            item=self.item,
            qty=Decimal("1.000"),
            source_location=self.location,
            recipient=self.recipient,
            department="Монтаж",
            occurred_at=timezone.datetime(
                2026, 5, 13, 10, 6, 32, tzinfo=timezone.get_current_timezone()
            ),
        )
        print_url = reverse("stock_movement_print", kwargs={"pk": movement.pk})

        response = self.client.get(print_url)
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn('onclick="window.print()"', html)
        self.assertNotIn('window.addEventListener("load"', html)

        response = self.client.get(f"{print_url}?autoprint=1")
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn('window.addEventListener("load"', html)
        self.assertIn("window.print();", html)

    def test_return_stock_movement_print_page_autoprint_is_opt_in(self):
        self.client.force_login(self.storekeeper)
        movement = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.RETURN,
            item=self.item,
            qty=Decimal("1.000"),
            destination_location=self.location,
            recipient=self.recipient,
            department="Монтаж",
            occurred_at=timezone.datetime(
                2026, 5, 13, 10, 6, 32, tzinfo=timezone.get_current_timezone()
            ),
        )
        print_url = reverse("stock_movement_print", kwargs={"pk": movement.pk})

        response = self.client.get(print_url)
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn('onclick="window.print()"', html)
        self.assertNotIn('window.addEventListener("load"', html)

        response = self.client.get(f"{print_url}?autoprint=1")
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn('window.addEventListener("load"', html)
        self.assertIn("window.print();", html)

    def test_auditor_can_open_stock_movement_print_page(self):
        self.client.force_login(self.auditor)
        movement = StockMovement.objects.filter(movement_type=StockMovement.MovementType.IN).first()

        response = self.client.get(
            reverse("stock_movement_print", kwargs={"pk": movement.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Контрольний талон складської операції")

    def test_english_stock_movement_print_page_uses_english_only_control_labels(self):
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

        response = self.client.get(f"/en/stock/movements/{movement.pk}/print/")
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("Warehouse operation control slip", html)
        self.assertIn("Who takes the item", html)
        self.assertIn(self.recipient.name, html)
        self.assertTrue("Department / place of use" in html or "Місце використання" in html)
        self.assertIn("Assembly", html)
        self.assertIn("Video check time:", html)
        self.assertNotIn("Контрольний талон складської операції", html)
        self.assertNotIn("Час для перевірки по відео", html)
        self.assertNotIn("Друкувати контрольний талон", html)

    def test_movement_list_formats_date_and_time_compactly(self):
        movement = StockMovement.objects.create(
            movement_type=StockMovement.MovementType.IN,
            item=self.item,
            qty=Decimal("2.000"),
            destination_location=self.location,
            occurred_at=timezone.datetime(
                2026, 5, 26, 17, 15, tzinfo=timezone.get_current_timezone()
            ),
        )
        self.client.force_login(self.storekeeper)

        response = self.client.get(reverse("movement_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "26.05.2026")
        self.assertContains(response, "17:15")
        self.assertContains(response, 'class="movement-date-cell"')
        self.assertContains(response, f'>{movement.occurred_at.strftime("%Y-%m-%d")}<', count=0)

    def test_movement_list_shows_document_number_or_dash(self):
        StockMovement.objects.create(
            movement_type=StockMovement.MovementType.OUT,
            item=self.item,
            qty=Decimal("1.000"),
            source_location=self.location,
            recipient=self.recipient,
            document_number="INV-2026-15",
        )
        StockMovement.objects.create(
            movement_type=StockMovement.MovementType.TRANSFER,
            item=self.item,
            qty=Decimal("1.000"),
            source_location=self.location,
            destination_location=self.other_location,
            document_number="",
        )
        self.client.force_login(self.storekeeper)

        response = self.client.get(reverse("movement_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="movement-document-cell">INV-2026-15<')
        self.assertContains(response, 'class="movement-document-cell">—<')

    def test_movement_list_includes_readability_css_classes(self):
        self.client.force_login(self.storekeeper)

        response = self.client.get(reverse("movement_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "movement-date-cell")
        self.assertContains(response, "movement-document-cell")
        self.assertContains(response, "movement-code-cell")
        self.assertContains(response, "movement-qty-cell")

class StockOperationWorkflowTests(StockOperationWorkflowTestBase):
    def test_english_self_service_home_has_only_two_clean_actions(self):
        storekeeper = get_user_model().objects.create_user(
            "workflow_storekeeper", password="pass"
        )
        storekeeper.groups.add(Group.objects.get(name="Комірник"))
        grant_warehouse_access(storekeeper, self.warehouse)
        self.client.force_login(storekeeper)

        response = self.client.get("/en/")
        html = response.content.decode()
        main_html = html.split('<main class="col-12">', 1)[1]

        self.assertEqual(response.status_code, 200)
        self.assertIn("Warehouse self-service", main_html)
        self.assertIn("Choose an action", main_html)
        self.assertIn("Take item", main_html)
        self.assertIn("Return item", main_html)
        self.assertIn("Scan an item and record stock issue.", main_html)
        self.assertIn("Scan an item and record stock return.", main_html)
        self.assertIn(
            f'<a class="card self-service-action-card text-decoration-none text-reset" href="{reverse("stock_issue")}"',
            main_html,
        )
        self.assertIn(
            f'<a class="card self-service-action-card text-decoration-none text-reset" href="{reverse("stock_return")}"',
            main_html,
        )
        self.assertEqual(main_html.count('<a class="card self-service-action-card'), 2)
        for phrase in [
            "Взяти товар",
            "Повернути товар",
            "Журнал операцій",
            "Залишки на складі",
            "Інвентаризація",
            "Налаштування складу",
            "Зіскануйте товар і зафіксуйте видачу зі складу.",
            "Зіскануйте товар і зафіксуйте повернення на склад.",
        ]:
            self.assertNotIn(phrase, main_html)

    def test_unknown_barcode_shows_ukrainian_warning_on_issue_and_receive(self):
        for url_name in ["stock_issue", "stock_return"]:
            with self.subTest(url_name=url_name):
                response = self.client.get(f'{reverse(url_name)}?barcode=UNKNOWN')

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Товар за цим штрихкодом не знайдено.")
                self.assertNotContains(response, "Item with this barcode was not found.")

    def test_unknown_barcode_shows_english_warning_on_issue_and_receive(self):
        for path in ["/en/stock/issue/", "/en/stock/receive/"]:
            with self.subTest(path=path):
                response = self.client.get(f"{path}?barcode=UNKNOWN")

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Item with this barcode was not found.")
                self.assertNotContains(response, "Товар за цим штрихкодом не знайдено.")

    def test_english_stock_pages_show_english_scanner_labels(self):
        issue_response = self.client.get("/en/stock/issue/")
        receive_response = self.client.get("/en/stock/receive/")

        self.assertContains(issue_response, "Scan item")
        self.assertContains(issue_response, "Find item")
        self.assertNotContains(issue_response, "Сканування товару")
        self.assertContains(receive_response, "Stock receipt")
        self.assertContains(receive_response, "Scan item")
        self.assertContains(receive_response, "Find item")

    def test_unauthorized_user_redirects_to_login(self):
        self.client.logout()
        response = self.client.get(reverse("stock_return"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])
