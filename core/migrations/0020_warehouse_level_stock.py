from django.db import migrations, models
import django.db.models.deletion
from django.db.models import Q, Sum


def migrate_stock_to_warehouses(apps, schema_editor):
    StockBalance = apps.get_model("core", "StockBalance")
    StockMovement = apps.get_model("core", "StockMovement")

    for balance in StockBalance.objects.select_related("location").filter(warehouse__isnull=True):
        if balance.location_id:
            balance.warehouse_id = balance.location.warehouse_id
            balance.save(update_fields=["warehouse"])

    grouped = (
        StockBalance.objects.exclude(warehouse__isnull=True)
        .values("item_id", "warehouse_id")
        .annotate(total_qty=Sum("qty"), row_count=models.Count("id"))
        .filter(row_count__gt=1)
    )
    for group in grouped:
        duplicates = list(
            StockBalance.objects.filter(
                item_id=group["item_id"], warehouse_id=group["warehouse_id"]
            ).order_by("id")
        )
        keeper = duplicates[0]
        keeper.qty = group["total_qty"]
        keeper.is_active = True
        keeper.save(update_fields=["qty", "is_active", "updated_at"])
        for duplicate in duplicates[1:]:
            duplicate.qty = 0
            duplicate.is_active = False
            duplicate.save(update_fields=["qty", "is_active", "updated_at"])

    for movement in StockMovement.objects.select_related(
        "source_location", "destination_location"
    ).filter(Q(source_warehouse__isnull=True) | Q(destination_warehouse__isnull=True)):
        update_fields = []
        if movement.source_warehouse_id is None and movement.source_location_id:
            movement.source_warehouse_id = movement.source_location.warehouse_id
            update_fields.append("source_warehouse")
        if movement.destination_warehouse_id is None and movement.destination_location_id:
            movement.destination_warehouse_id = movement.destination_location.warehouse_id
            update_fields.append("destination_warehouse")
        if update_fields:
            movement.save(update_fields=update_fields)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0019_user_warehouse_access"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="stockbalance",
            options={
                "ordering": ["item__name", "warehouse__name"],
                "verbose_name": "Залишок",
                "verbose_name_plural": "Залишки",
            },
        ),
        migrations.RemoveConstraint(
            model_name="stockbalance",
            name="core_stock_balance_unique_item_location",
        ),
        migrations.AddField(
            model_name="stockbalance",
            name="warehouse",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="stock_balances",
                to="core.warehouse",
                verbose_name="Склад",
            ),
        ),
        migrations.AlterField(
            model_name="stockbalance",
            name="location",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="stock_balances",
                to="core.location",
                verbose_name="Локація",
            ),
        ),
        migrations.AddField(
            model_name="stockmovement",
            name="source_warehouse",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="outgoing_stock_movements",
                to="core.warehouse",
                verbose_name="Склад-відправник",
            ),
        ),
        migrations.AddField(
            model_name="stockmovement",
            name="destination_warehouse",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="incoming_stock_movements",
                to="core.warehouse",
                verbose_name="Склад-отримувач",
            ),
        ),
        migrations.RunPython(migrate_stock_to_warehouses, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="stockbalance",
            name="warehouse",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="stock_balances",
                to="core.warehouse",
                verbose_name="Склад",
            ),
        ),
        migrations.AddConstraint(
            model_name="stockbalance",
            constraint=models.UniqueConstraint(
                condition=Q(("is_active", True)),
                fields=("item", "warehouse"),
                name="core_stock_balance_unique_active_item_warehouse",
            ),
        ),
    ]
