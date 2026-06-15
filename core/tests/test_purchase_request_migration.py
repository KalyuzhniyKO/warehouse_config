from importlib import import_module
from types import SimpleNamespace
from unittest import mock

from django.db import migrations, models
from django.test import SimpleTestCase


migration = import_module("core.migrations.0024_match_purchase_requests_order_tracking")


class FakeField:
    def __init__(self, column, internal_type="TextField"):
        self.column = column
        self.internal_type = internal_type

    def get_internal_type(self):
        return self.internal_type


class FakeMeta:
    db_table = "core_purchaserequest"

    def __init__(self, fields):
        self.fields = fields

    def get_field(self, name):
        return self.fields[name]


class FakeApps:
    def __init__(self, model):
        self.model = model

    def get_model(self, app_label, model_name):
        return self.model


class FakeSchemaEditor:
    connection = SimpleNamespace(vendor="mysql")

    def __init__(self):
        self.executed = []
        self.added_fields = []

    def quote_name(self, name):
        return f"`{name}`"

    def execute(self, sql):
        self.executed.append(sql)

    def add_field(self, model, field):
        self.added_fields.append(field.column)


def migration_states(old_name, new_name, internal_type="TextField"):
    old_model = SimpleNamespace(
        _meta=FakeMeta({old_name: FakeField(old_name, internal_type)})
    )
    new_model = SimpleNamespace(
        _meta=FakeMeta({new_name: FakeField(new_name, internal_type)})
    )
    return (
        SimpleNamespace(apps=FakeApps(old_model)),
        SimpleNamespace(apps=FakeApps(new_model)),
    )


class PurchaseRequestMySQLMigrationTests(SimpleTestCase):
    def test_old_price_constraint_is_removed_before_price_rename(self):
        operations = migration.Migration.operations

        self.assertIsInstance(operations[0], migration.MySQLSafeRemoveConstraint)
        self.assertEqual(
            operations[0].name, "purchase_request_estimated_price_non_negative"
        )
        self.assertEqual(operations[2].old_name, "estimated_unit_price")

    def test_rename_runs_normally_when_only_old_column_exists(self):
        operation = migration.MySQLSafeRenameField(
            "purchaserequest", "description", "need_description"
        )
        schema_editor = FakeSchemaEditor()
        from_state, to_state = migration_states("description", "need_description")

        with (
            mock.patch.object(
                migration, "mysql_columns", return_value={"description"}
            ),
            mock.patch.object(
                migrations.RenameField, "database_forwards"
            ) as normal_rename,
        ):
            operation.database_forwards("core", schema_editor, from_state, to_state)

        normal_rename.assert_called_once()

    def test_rename_is_skipped_when_only_new_column_exists(self):
        operation = migration.MySQLSafeRenameField(
            "purchaserequest", "description", "need_description"
        )
        schema_editor = FakeSchemaEditor()
        from_state, to_state = migration_states("description", "need_description")

        with mock.patch.object(
            migration, "mysql_columns", return_value={"need_description"}
        ):
            operation.database_forwards("core", schema_editor, from_state, to_state)

        self.assertEqual(schema_editor.executed, [])
        self.assertEqual(schema_editor.added_fields, [])

    def test_rename_merges_data_and_removes_old_column_when_both_exist(self):
        operation = migration.MySQLSafeRenameField(
            "purchaserequest", "estimated_unit_price", "unit_price_uah"
        )
        schema_editor = FakeSchemaEditor()
        from_state, to_state = migration_states(
            "estimated_unit_price", "unit_price_uah", "DecimalField"
        )

        with mock.patch.object(
            migration,
            "mysql_columns",
            return_value={"estimated_unit_price", "unit_price_uah"},
        ):
            operation.database_forwards("core", schema_editor, from_state, to_state)

        self.assertIn(
            "SET `unit_price_uah` = `estimated_unit_price`",
            schema_editor.executed[0],
        )
        self.assertIn(
            "DROP COLUMN `estimated_unit_price`", schema_editor.executed[1]
        )

    def test_rename_restores_new_column_when_both_columns_are_missing(self):
        operation = migration.MySQLSafeRenameField(
            "purchaserequest", "description", "need_description"
        )
        schema_editor = FakeSchemaEditor()
        from_state, to_state = migration_states("description", "need_description")

        with mock.patch.object(migration, "mysql_columns", return_value=set()):
            operation.database_forwards("core", schema_editor, from_state, to_state)

        self.assertEqual(schema_editor.added_fields, ["need_description"])

    def test_remove_constraint_handles_existing_and_missing_mysql_constraint(self):
        operation = migration.MySQLSafeRemoveConstraint(
            "purchaserequest", "purchase_request_estimated_price_non_negative"
        )
        model = SimpleNamespace(_meta=FakeMeta({}))
        state = SimpleNamespace(apps=FakeApps(model))

        with (
            mock.patch.object(
                migration, "mysql_constraint_exists", side_effect=[False, True]
            ),
            mock.patch.object(
                migrations.RemoveConstraint, "database_forwards"
            ) as normal_remove,
        ):
            operation.database_forwards("core", FakeSchemaEditor(), state, state)
            operation.database_forwards("core", FakeSchemaEditor(), state, state)

        normal_remove.assert_called_once()

    def test_add_field_skips_column_created_by_partial_mysql_migration(self):
        operation = migration.MySQLSafeAddField(
            "purchaserequest",
            "approval_status",
            models.CharField(max_length=16),
        )
        model = SimpleNamespace(
            _meta=FakeMeta({"approval_status": FakeField("approval_status")})
        )
        state = SimpleNamespace(apps=FakeApps(model))

        with (
            mock.patch.object(
                migration, "mysql_columns", return_value={"approval_status"}
            ),
            mock.patch.object(
                migrations.AddField, "database_forwards"
            ) as normal_add,
        ):
            operation.database_forwards("core", FakeSchemaEditor(), state, state)

        normal_add.assert_not_called()

    def test_add_constraint_skips_constraint_created_by_partial_mysql_migration(self):
        constraint = models.CheckConstraint(
            condition=models.Q(unit_price_uah__gte=0),
            name="purchase_request_unit_price_uah_non_negative",
        )
        operation = migration.MySQLSafeAddConstraint(
            "purchaserequest", constraint
        )
        model = SimpleNamespace(_meta=FakeMeta({}))
        state = SimpleNamespace(apps=FakeApps(model))

        with (
            mock.patch.object(
                migration, "mysql_constraint_exists", return_value=True
            ),
            mock.patch.object(
                migrations.AddConstraint, "database_forwards"
            ) as normal_add,
        ):
            operation.database_forwards("core", FakeSchemaEditor(), state, state)

        normal_add.assert_not_called()
