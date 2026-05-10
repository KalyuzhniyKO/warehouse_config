"""Helpers for warehouse locations."""

from core.models import Location

DEFAULT_LOCATION_NAME = "Основна локація"


def get_default_location_for_warehouse(warehouse):
    """Return the service default location for *warehouse*, creating it if needed."""
    existing_location = (
        Location.objects.filter(
            warehouse=warehouse,
            name=DEFAULT_LOCATION_NAME,
            is_active=True,
        )
        .order_by("id")
        .first()
    )
    if existing_location is not None:
        return existing_location

    return Location.objects.create(
        warehouse=warehouse,
        name=DEFAULT_LOCATION_NAME,
        location_type=Location.LocationType.LOCATION,
        is_active=True,
    )
