from django.core.management.base import BaseCommand

from core.services.locations import ensure_default_locations_for_warehouses


class Command(BaseCommand):
    help = "Ensure every active warehouse has an active default location."

    def handle(self, *args, **options):
        locations = ensure_default_locations_for_warehouses()
        self.stdout.write(
            self.style.SUCCESS(f"Ensured {len(locations)} default warehouse locations.")
        )
