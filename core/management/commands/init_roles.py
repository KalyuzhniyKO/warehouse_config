from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

from core.models import (
    Category,
    Item,
    Location,
    Recipient,
    StockBalance,
    StockMovement,
    Unit,
    Warehouse,
)
from core.permissions import AUDITOR_GROUP, STOREKEEPER_GROUP, WAREHOUSE_ADMIN_GROUP


class Command(BaseCommand):
    help = "Create warehouse user roles and assign base Django model permissions."

    def handle(self, *args, **options):
        admin_group, _ = Group.objects.get_or_create(name=WAREHOUSE_ADMIN_GROUP)
        storekeeper_group, _ = Group.objects.get_or_create(name=STOREKEEPER_GROUP)
        auditor_group, _ = Group.objects.get_or_create(name=AUDITOR_GROUP)

        directory_models = [Unit, Category, Recipient, Item, Warehouse, Location]
        stock_models = [StockBalance, StockMovement]
        admin_models = directory_models + stock_models + [get_user_model(), Group]
        all_models = directory_models + stock_models

        admin_group.permissions.set(
            self.permissions_for(admin_models, ["view", "add", "change", "delete"])
        )
        storekeeper_group.permissions.set(
            self.permissions_for(
                stock_models + [Item, Warehouse, Location, Recipient],
                ["view", "add", "change"],
            )
        )
        auditor_group.permissions.set(self.permissions_for(all_models, ["view"]))

        self.stdout.write(
            self.style.SUCCESS(
                "Створено/оновлено групи: Адміністратор складу, Комірник, Перегляд / аудитор."
            )
        )

    def permissions_for(self, models, actions):
        permissions = []
        for model in models:
            content_type = ContentType.objects.get_for_model(model)
            codenames = [f"{action}_{model._meta.model_name}" for action in actions]
            permissions.extend(
                Permission.objects.filter(
                    content_type=content_type, codename__in=codenames
                )
            )
        return permissions
