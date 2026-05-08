from collections import defaultdict

from django.core.management.base import BaseCommand

from core.models import Category, Item, Location, Recipient, Unit, Warehouse


def normalize(value):
    return (value or "").strip().casefold()


class Command(BaseCommand):
    help = "Find potential duplicate active directory records without changing data."

    def handle(self, *args, **options):
        total_groups = 0
        total_groups += self.report_category_duplicates()
        total_groups += self.report_unit_duplicates()
        total_groups += self.report_simple_duplicates(Warehouse, "Warehouse", lambda obj: normalize(obj.name))
        total_groups += self.report_simple_duplicates(Recipient, "Recipient", lambda obj: normalize(obj.name))
        total_groups += self.report_location_duplicates()
        total_groups += self.report_item_duplicates()
        if total_groups == 0:
            self.stdout.write(self.style.SUCCESS("Дублікатів не знайдено."))
        else:
            self.stdout.write(self.style.WARNING(f"Знайдено груп дублікатів: {total_groups}"))

    def report_groups(self, label, groups):
        count = 0
        for key, objects in groups.items():
            if len(objects) < 2:
                continue
            count += 1
            ids = ", ".join(str(obj.pk) for obj in objects)
            names = "; ".join(str(obj) for obj in objects)
            self.stdout.write(f"{label}: key={key!r}; ids={ids}; values={names}")
        return count

    def report_simple_duplicates(self, model, label, key_func):
        groups = defaultdict(list)
        for obj in model.objects.all().order_by("pk"):
            key = key_func(obj)
            if key:
                groups[key].append(obj)
        return self.report_groups(label, groups)

    def report_category_duplicates(self):
        groups = defaultdict(list)
        for obj in Category.objects.select_related("parent").order_by("pk"):
            groups[(obj.parent_id, normalize(obj.name))].append(obj)
        return self.report_groups("Category", groups)

    def report_unit_duplicates(self):
        groups = defaultdict(list)
        for obj in Unit.objects.all().order_by("pk"):
            if normalize(obj.name):
                groups[("name", normalize(obj.name))].append(obj)
            if normalize(obj.symbol):
                groups[("symbol", normalize(obj.symbol))].append(obj)
        return self.report_groups("Unit", groups)

    def report_location_duplicates(self):
        groups = defaultdict(list)
        for obj in Location.objects.select_related("warehouse").order_by("pk"):
            groups[(obj.warehouse_id, normalize(obj.name))].append(obj)
        return self.report_groups("Location", groups)

    def report_item_duplicates(self):
        groups = defaultdict(list)
        for obj in Item.objects.all().order_by("pk"):
            code = normalize(obj.internal_code)
            if code:
                groups[code].append(obj)
        return self.report_groups("Item", groups)
