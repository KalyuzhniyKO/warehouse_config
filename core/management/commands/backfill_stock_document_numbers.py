from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from core.models import StockMovement
from core.services.stock import generate_stock_document_number


class Command(BaseCommand):
    help = "Assign document numbers to stock movements that do not have one."

    def handle(self, *args, **options):
        queryset = (
            StockMovement.objects.filter(Q(document_number__isnull=True) | Q(document_number=""))
            .order_by("occurred_at", "id")
        )
        updated = 0
        with transaction.atomic():
            for movement in queryset.select_for_update():
                movement.document_number = generate_stock_document_number(
                    movement_type=movement.movement_type,
                    occurred_at=movement.occurred_at,
                )
                movement.save(update_fields=["document_number", "updated_at"])
                updated += 1
        self.stdout.write(self.style.SUCCESS(f"Backfilled {updated} stock document numbers."))
