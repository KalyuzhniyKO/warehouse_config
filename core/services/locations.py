"""Helpers for warehouse locations."""

from django.utils.translation import gettext_lazy as _

from core.models import Location, Warehouse

DEFAULT_LOCATION_NAME = "Основна локація"
DEFAULT_LOCATION_NAMES = (
    "Основна локація",
    "Основная локация",
    "Main location",
)
DEFAULT_LOCATION_NAME_LABEL = _("Основна локація")
DEFAULT_LOCATION_RU_LABEL = _("Основная локация")
DEFAULT_LOCATION_EN_LABEL = _("Main location")


def get_default_location_for_warehouse(warehouse):
    """Return the service default location for *warehouse*, creating it if needed."""
    existing_location = (
        Location.objects.filter(
            warehouse=warehouse,
            name__in=DEFAULT_LOCATION_NAMES,
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


def ensure_default_locations_for_warehouses():
    """Ensure every active warehouse has an active default technical location."""
    ensured_locations = []
    for warehouse in Warehouse.objects.filter(is_active=True).order_by("name", "id"):
        ensured_locations.append(get_default_location_for_warehouse(warehouse))
    return ensured_locations
