from django.db import migrations


OLD_PLACE_NAME = "Протяжка"
NEW_PLACE_NAME = "ТП-506"
WIRE_DRAWING_STAND_NAME = "Стан волочіння"
WIRE_DRAWING_SHOP_NAME = "Цех волочіння"


def update_usage_places(apps, schema_editor):
    UsagePlace = apps.get_model("core", "UsagePlace")

    tp_506 = UsagePlace.objects.filter(name=NEW_PLACE_NAME).first()
    protozhka = UsagePlace.objects.filter(name=OLD_PLACE_NAME).first()

    if protozhka:
        if tp_506 is None:
            protozhka.name = NEW_PLACE_NAME
            protozhka.is_active = True
            protozhka.save(update_fields=["name", "is_active"])
            tp_506 = protozhka
        else:
            if protozhka.is_active:
                protozhka.is_active = False
                protozhka.save(update_fields=["is_active"])

    if tp_506 is None:
        tp_506 = UsagePlace.objects.create(name=NEW_PLACE_NAME, is_active=True)
    elif not tp_506.is_active:
        tp_506.is_active = True
        tp_506.save(update_fields=["is_active"])

    wire_drawing_stand = UsagePlace.objects.filter(name=WIRE_DRAWING_STAND_NAME).first()
    if wire_drawing_stand and wire_drawing_stand.is_active:
        wire_drawing_stand.is_active = False
        wire_drawing_stand.save(update_fields=["is_active"])

    wire_drawing_shop = UsagePlace.objects.filter(name=WIRE_DRAWING_SHOP_NAME).first()
    if wire_drawing_shop and not wire_drawing_shop.is_active:
        wire_drawing_shop.is_active = True
        wire_drawing_shop.save(update_fields=["is_active"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0012_labeltemplate_barcode_bar_width_mm_and_more"),
    ]

    operations = [
        migrations.RunPython(update_usage_places, noop_reverse),
    ]
