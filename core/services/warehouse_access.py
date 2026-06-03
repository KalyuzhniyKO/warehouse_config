from django.db.models import Q

from core.models import StockMovement, UserWarehouseAccess, Warehouse


def _is_authenticated(user):
    return bool(getattr(user, "is_authenticated", False))


def get_accessible_warehouses(user, include_inactive=False):
    queryset = Warehouse.objects.all()
    if not include_inactive:
        queryset = queryset.filter(is_active=True)
    if not _is_authenticated(user):
        return queryset.none()
    if user.is_superuser:
        return queryset.order_by("name")
    return (
        queryset.filter(user_accesses__user=user, user_accesses__is_active=True)
        .distinct()
        .order_by("name")
    )


def user_can_access_warehouse(user, warehouse):
    if warehouse is None or not _is_authenticated(user):
        return False
    if user.is_superuser:
        return True
    if not getattr(warehouse, "is_active", False):
        return False
    return UserWarehouseAccess.objects.filter(
        user=user,
        warehouse=warehouse,
        is_active=True,
    ).exists()


def get_delegatable_warehouses(user):
    queryset = Warehouse.objects.filter(is_active=True)
    if not _is_authenticated(user):
        return queryset.none()
    if user.is_superuser:
        return queryset.order_by("name")
    return (
        queryset.filter(
            user_accesses__user=user,
            user_accesses__is_active=True,
            user_accesses__can_delegate=True,
        )
        .distinct()
        .order_by("name")
    )


def user_can_delegate_warehouse(user, warehouse):
    if warehouse is None or not _is_authenticated(user):
        return False
    if user.is_superuser:
        return getattr(warehouse, "is_active", False)
    if not getattr(warehouse, "is_active", False):
        return False
    return UserWarehouseAccess.objects.filter(
        user=user,
        warehouse=warehouse,
        is_active=True,
        can_delegate=True,
    ).exists()


def restrict_warehouse_queryset_for_user(user, queryset):
    if not _is_authenticated(user):
        return queryset.none()
    if user.is_superuser:
        return queryset
    return queryset.filter(
        user_accesses__user=user,
        user_accesses__is_active=True,
    ).distinct()


def get_single_accessible_warehouse_or_none(user):
    warehouses = list(get_accessible_warehouses(user)[:2])
    if len(warehouses) == 1:
        return warehouses[0]
    return None


def restrict_stock_movement_queryset_for_user(user, queryset=None):
    queryset = queryset if queryset is not None else StockMovement.objects.all()
    if not _is_authenticated(user):
        return queryset.none()
    if user.is_superuser:
        return queryset
    accessible_warehouses = get_accessible_warehouses(user)
    return queryset.filter(
        Q(source_warehouse__in=accessible_warehouses)
        | Q(destination_warehouse__in=accessible_warehouses)
        | Q(source_location__warehouse__in=accessible_warehouses)
        | Q(destination_location__warehouse__in=accessible_warehouses)
    )


def user_can_access_stock_movement(user, movement):
    if movement is None or not _is_authenticated(user):
        return False
    if user.is_superuser:
        return True
    source_warehouse = movement.resolved_source_warehouse
    destination_warehouse = movement.resolved_destination_warehouse
    return any(
        user_can_access_warehouse(user, warehouse)
        for warehouse in (source_warehouse, destination_warehouse)
    )
