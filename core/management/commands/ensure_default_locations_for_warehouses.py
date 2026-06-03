from django.core.management.base import BaseCommand

from core.services.locations import ensure_default_locations_for_warehouses


class Command(BaseCommand):
    help = "Legacy no-op: warehouse stock no longer needs default locations."

    def handle(self, *args, **options):
        locations = ensure_default_locations_for_warehouses()
        self.stdout.write(
            self.style.WARNING(
                "Legacy no-op: no default warehouse locations were created. "
                f"Existing legacy records found/changed: {len(locations)}."
            )
        )
