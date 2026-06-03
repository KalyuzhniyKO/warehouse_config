"""Helpers for optional warehouse locations."""

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
    """Return/create the legacy default location for explicit legacy callers.

    Normal stock operations no longer call this helper, so default locations are
    not created during receive/issue/return/write-off/transfer workflows.
    """
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
    """Legacy no-op: default technical locations are no longer created."""
    return []
