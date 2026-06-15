import django.core.validators
from django.db import migrations, models
from django.utils import timezone


def mysql_columns(schema_editor, table_name):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT COLUMN_NAME
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
            """,
            [table_name],
        )
        return {row[0] for row in cursor.fetchall()}


def mysql_constraint_exists(schema_editor, table_name, constraint_name):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT 1
            FROM information_schema.TABLE_CONSTRAINTS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = %s
              AND CONSTRAINT_NAME = %s
            LIMIT 1
            """,
            [table_name, constraint_name],
        )
        return cursor.fetchone() is not None


class MySQLSafeRenameField(migrations.RenameField):
    """Rename, merge, or restore a column after a partially applied MySQL DDL."""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor != "mysql":
            return super().database_forwards(
                app_label, schema_editor, from_state, to_state
            )

        from_model = from_state.apps.get_model(app_label, self.model_name)
        to_model = to_state.apps.get_model(app_label, self.model_name)
        table_name = from_model._meta.db_table
        columns = mysql_columns(schema_editor, table_name)
        old_field = from_model._meta.get_field(self.old_name)
        new_field = to_model._meta.get_field(self.new_name)
        old_column = old_field.column
        new_column = new_field.column

        if old_column in columns and new_column not in columns:
            return super().database_forwards(
                app_label, schema_editor, from_state, to_state
            )
        if old_column not in columns and new_column not in columns:
            schema_editor.add_field(from_model, new_field)
            return
        if old_column not in columns:
            return

        quote = schema_editor.quote_name
        empty_target = f"{quote(new_column)} IS NULL"
        if new_field.get_internal_type() in {
            "CharField",
            "TextField",
            "URLField",
        }:
            empty_target += f" OR {quote(new_column)} = ''"
        schema_editor.execute(
            f"UPDATE {quote(table_name)} "
            f"SET {quote(new_column)} = {quote(old_column)} "
            f"WHERE ({empty_target}) AND {quote(old_column)} IS NOT NULL"
        )
        schema_editor.execute(
            f"ALTER TABLE {quote(table_name)} DROP COLUMN {quote(old_column)}"
        )


class MySQLSafeAddField(migrations.AddField):
    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor == "mysql":
            model = to_state.apps.get_model(app_label, self.model_name)
            field = model._meta.get_field(self.name)
            if field.column in mysql_columns(schema_editor, model._meta.db_table):
                return
        return super().database_forwards(app_label, schema_editor, from_state, to_state)


class MySQLSafeAlterField(migrations.AlterField):
    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor == "mysql":
            from_model = from_state.apps.get_model(app_label, self.model_name)
            to_model = to_state.apps.get_model(app_label, self.model_name)
            to_field = to_model._meta.get_field(self.name)
            if to_field.column not in mysql_columns(
                schema_editor, to_model._meta.db_table
            ):
                schema_editor.add_field(from_model, to_field)
                return
        return super().database_forwards(app_label, schema_editor, from_state, to_state)


class MySQLSafeRemoveConstraint(migrations.RemoveConstraint):
    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor == "mysql":
            model = to_state.apps.get_model(app_label, self.model_name)
            if not mysql_constraint_exists(
                schema_editor, model._meta.db_table, self.name
            ):
                return
        return super().database_forwards(app_label, schema_editor, from_state, to_state)


class MySQLSafeAddConstraint(migrations.AddConstraint):
    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor == "mysql":
            model = to_state.apps.get_model(app_label, self.model_name)
            if mysql_constraint_exists(
                schema_editor, model._meta.db_table, self.constraint.name
            ):
                return
        return super().database_forwards(app_label, schema_editor, from_state, to_state)


def populate_tracking_fields(apps, schema_editor):
    PurchaseRequest = apps.get_model("core", "PurchaseRequest")
    PurchaseRequest.objects.filter(status="approved").update(approval_status="approved")
    PurchaseRequest.objects.filter(status="rejected").update(approval_status="rejected")
    PurchaseRequest.objects.filter(
        status__in=["ordered", "partially_received", "received"]
    ).update(approval_status="approved")


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0023_stockmovement_purchase_request_and_more"),
    ]

    operations = [
        MySQLSafeRemoveConstraint(
            model_name="purchaserequest",
            name="purchase_request_estimated_price_non_negative",
        ),
        MySQLSafeRenameField(
            model_name="purchaserequest",
            old_name="description",
            new_name="need_description",
        ),
        MySQLSafeRenameField(
            model_name="purchaserequest",
            old_name="estimated_unit_price",
            new_name="unit_price_uah",
        ),
        MySQLSafeRenameField(
            model_name="purchaserequest",
            old_name="supplier_url",
            new_name="product_url",
        ),
        MySQLSafeAddField(
            model_name="purchaserequest",
            name="approval_status",
            field=models.CharField(
                choices=[
                    ("pending", "Очікування"),
                    ("approved", "Погоджено"),
                    ("rejected", "Відхилено"),
                ],
                default="pending",
                max_length=16,
                verbose_name="Статус погодження",
            ),
        ),
        MySQLSafeAddField(
            model_name="purchaserequest",
            name="delivery_status",
            field=models.CharField(
                choices=[
                    ("not_shipped", "Не відправлено"),
                    ("in_transit", "В дорозі"),
                    ("delivered", "Отримано"),
                    ("cancelled", "Не актуально"),
                ],
                default="not_shipped",
                max_length=16,
                verbose_name="Статус доставки",
            ),
        ),
        MySQLSafeAddField(
            model_name="purchaserequest",
            name="order_type",
            field=models.CharField(
                choices=[
                    ("emergency", "Аварійний"),
                    ("urgent", "Терміновий"),
                    ("planned", "Плановий"),
                ],
                default="planned",
                max_length=16,
                verbose_name="Тип замовлення",
            ),
        ),
        MySQLSafeAddField(
            model_name="purchaserequest",
            name="payment_status",
            field=models.CharField(
                choices=[
                    ("invoice_not_received", "Рахунок не отримано"),
                    ("invoice_received", "Рахунок отримано"),
                    ("sent_for_payment", "Передано на оплату"),
                    ("paid", "Оплачено"),
                    ("not_required", "Не потребує оплати"),
                ],
                default="invoice_not_received",
                max_length=24,
                verbose_name="Статус оплати",
            ),
        ),
        MySQLSafeAddField(
            model_name="purchaserequest",
            name="request_date",
            field=models.DateField(default=timezone.localdate, verbose_name="Дата"),
        ),
        MySQLSafeAlterField(
            model_name="purchaserequest",
            name="need_description",
            field=models.TextField(blank=True, verbose_name="Опис потреби"),
        ),
        MySQLSafeAlterField(
            model_name="purchaserequest",
            name="product_url",
            field=models.URLField(blank=True, verbose_name="Посилання на товар"),
        ),
        MySQLSafeAlterField(
            model_name="purchaserequest",
            name="supplier_name",
            field=models.CharField(blank=True, max_length=255, verbose_name="Постачальник"),
        ),
        MySQLSafeAlterField(
            model_name="purchaserequest",
            name="title",
            field=models.CharField(max_length=255, verbose_name="Назва товару"),
        ),
        MySQLSafeAlterField(
            model_name="purchaserequest",
            name="unit_price_uah",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=18,
                null=True,
                validators=[django.core.validators.MinValueValidator(0)],
                verbose_name="Вартість за одиницю (грн)",
            ),
        ),
        MySQLSafeAddConstraint(
            model_name="purchaserequest",
            constraint=models.CheckConstraint(
                condition=models.Q(("unit_price_uah__gte", 0))
                | models.Q(("unit_price_uah__isnull", True)),
                name="purchase_request_unit_price_uah_non_negative",
            ),
        ),
        migrations.RunPython(populate_tracking_fields, migrations.RunPython.noop),
    ]
