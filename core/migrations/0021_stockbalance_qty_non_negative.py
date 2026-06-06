from django.db import migrations, models


def reject_negative_stock_balances(apps, schema_editor):
    StockBalance = apps.get_model("core", "StockBalance")
    negative_count = StockBalance.objects.filter(qty__lt=0).count()
    if negative_count:
        raise RuntimeError(
            "Cannot add core_stock_balance_qty_non_negative: "
            f"{negative_count} negative StockBalance row(s) exist. "
            "Review and correct them explicitly before applying this migration."
        )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0020_warehouse_level_stock"),
    ]

    operations = [
        migrations.RunPython(reject_negative_stock_balances, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="stockbalance",
            constraint=models.CheckConstraint(
                condition=models.Q(("qty__gte", 0)),
                name="core_stock_balance_qty_non_negative",
            ),
        ),
    ]
