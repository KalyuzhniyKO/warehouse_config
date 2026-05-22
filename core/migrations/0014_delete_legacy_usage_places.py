from django.db import migrations


TP_506_NAME = "ТП-506"
WIRE_DRAWING_SHOP_NAME = "Цех волочіння"
WIRE_DRAWING_STAND_NAME = "Стан волочіння"
PROTOZHKA_NAME = "Протяжка"


def delete_legacy_usage_places(apps, schema_editor):
    UsagePlace = apps.get_model("core", "UsagePlace")

    UsagePlace.objects.update_or_create(
        name=TP_506_NAME, defaults={"is_active": True}
    )
    UsagePlace.objects.update_or_create(
        name=WIRE_DRAWING_SHOP_NAME, defaults={"is_active": True}
    )
    UsagePlace.objects.filter(name=WIRE_DRAWING_STAND_NAME).delete()
    UsagePlace.objects.filter(name=PROTOZHKA_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0013_update_usage_places_tp506"),
    ]

    operations = [
        migrations.RunPython(delete_legacy_usage_places, migrations.RunPython.noop),
    ]
