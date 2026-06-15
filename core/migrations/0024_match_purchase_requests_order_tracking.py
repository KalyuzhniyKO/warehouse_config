import django.core.validators
from django.db import migrations, models
from django.utils import timezone


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
        migrations.RenameField(
            model_name="purchaserequest",
            old_name="description",
            new_name="need_description",
        ),
        migrations.RenameField(
            model_name="purchaserequest",
            old_name="estimated_unit_price",
            new_name="unit_price_uah",
        ),
        migrations.RenameField(
            model_name="purchaserequest",
            old_name="supplier_url",
            new_name="product_url",
        ),
        migrations.RemoveConstraint(
            model_name="purchaserequest",
            name="purchase_request_estimated_price_non_negative",
        ),
        migrations.AddField(
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
        migrations.AddField(
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
        migrations.AddField(
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
        migrations.AddField(
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
        migrations.AddField(
            model_name="purchaserequest",
            name="request_date",
            field=models.DateField(default=timezone.localdate, verbose_name="Дата"),
        ),
        migrations.AlterField(
            model_name="purchaserequest",
            name="need_description",
            field=models.TextField(blank=True, verbose_name="Опис потреби"),
        ),
        migrations.AlterField(
            model_name="purchaserequest",
            name="product_url",
            field=models.URLField(blank=True, verbose_name="Посилання на товар"),
        ),
        migrations.AlterField(
            model_name="purchaserequest",
            name="supplier_name",
            field=models.CharField(blank=True, max_length=255, verbose_name="Постачальник"),
        ),
        migrations.AlterField(
            model_name="purchaserequest",
            name="title",
            field=models.CharField(max_length=255, verbose_name="Назва товару"),
        ),
        migrations.AlterField(
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
        migrations.AddConstraint(
            model_name="purchaserequest",
            constraint=models.CheckConstraint(
                condition=models.Q(("unit_price_uah__gte", 0))
                | models.Q(("unit_price_uah__isnull", True)),
                name="purchase_request_unit_price_uah_non_negative",
            ),
        ),
        migrations.RunPython(populate_tracking_fields, migrations.RunPython.noop),
    ]
