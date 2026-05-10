from django.test import TestCase

from core.models import Location, Warehouse
from core.services.locations import (
    DEFAULT_LOCATION_NAME,
    get_default_location_for_warehouse,
)


class DefaultLocationHelperTests(TestCase):
    def test_get_default_location_for_warehouse_creates_location(self):
        warehouse = Warehouse.objects.create(name="Main warehouse")

        location = get_default_location_for_warehouse(warehouse)

        self.assertEqual(location.name, DEFAULT_LOCATION_NAME)
        self.assertEqual(location.warehouse, warehouse)
        self.assertTrue(location.is_active)
        self.assertEqual(location.location_type, Location.LocationType.LOCATION)
        self.assertIsNotNone(location.barcode)
        self.assertTrue(location.barcode.barcode.startswith("LOC"))

    def test_get_default_location_for_warehouse_reuses_existing_location(self):
        warehouse = Warehouse.objects.create(name="Main warehouse")

        location = get_default_location_for_warehouse(warehouse)
        repeated_location = get_default_location_for_warehouse(warehouse)

        self.assertEqual(repeated_location, location)
        self.assertEqual(
            Location.objects.filter(
                warehouse=warehouse,
                name=DEFAULT_LOCATION_NAME,
                is_active=True,
            ).count(),
            1,
        )

    def test_get_default_location_for_warehouse_creates_one_per_warehouse(self):
        first_warehouse = Warehouse.objects.create(name="First warehouse")
        second_warehouse = Warehouse.objects.create(name="Second warehouse")

        first_location = get_default_location_for_warehouse(first_warehouse)
        second_location = get_default_location_for_warehouse(second_warehouse)

        self.assertNotEqual(first_location, second_location)
        self.assertEqual(first_location.warehouse, first_warehouse)
        self.assertEqual(second_location.warehouse, second_warehouse)
        self.assertEqual(
            Location.objects.filter(name=DEFAULT_LOCATION_NAME, is_active=True).count(),
            2,
        )

    def test_get_default_location_for_warehouse_returns_existing_location(self):
        warehouse = Warehouse.objects.create(name="Main warehouse")
        existing_location = Location.objects.create(
            warehouse=warehouse,
            name=DEFAULT_LOCATION_NAME,
            location_type=Location.LocationType.LOCATION,
            is_active=True,
        )

        location = get_default_location_for_warehouse(warehouse)

        self.assertEqual(location, existing_location)
        self.assertEqual(
            Location.objects.filter(
                warehouse=warehouse,
                name=DEFAULT_LOCATION_NAME,
                is_active=True,
            ).count(),
            1,
        )

    def test_get_default_location_for_warehouse_returns_first_duplicate(self):
        warehouse = Warehouse.objects.create(name="Main warehouse")
        first_location = Location.objects.create(
            warehouse=warehouse,
            name=DEFAULT_LOCATION_NAME,
            location_type=Location.LocationType.LOCATION,
            is_active=True,
        )
        Location.objects.create(
            warehouse=warehouse,
            name=DEFAULT_LOCATION_NAME,
            location_type=Location.LocationType.LOCATION,
            is_active=True,
        )

        location = get_default_location_for_warehouse(warehouse)

        self.assertEqual(location, first_location)
        self.assertEqual(
            Location.objects.filter(
                warehouse=warehouse,
                name=DEFAULT_LOCATION_NAME,
                is_active=True,
            ).count(),
            2,
        )
