from django.db import migrations


USAGE_PLACE_NAMES = [
    "Стан волочіння",
    "Цех волочіння",
    "Територія виробництва",
    "Протяжка",
    "Інше",
    "Цех секцій",
    "Цех сітки",
    "Цех фарбування",
    "Цех цинкування",
    "СГП",
]


def seed_usage_places(apps, schema_editor):
    UsagePlace = apps.get_model("core", "UsagePlace")
    existing_names = set(
        UsagePlace.objects.filter(name__in=USAGE_PLACE_NAMES).values_list(
            "name", flat=True
        )
    )
    UsagePlace.objects.bulk_create(
        [
            UsagePlace(name=name, is_active=True)
            for name in USAGE_PLACE_NAMES
            if name not in existing_names
        ]
    )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0010_usageplace"),
    ]

    operations = [
        migrations.RunPython(seed_usage_places, migrations.RunPython.noop),
    ]
