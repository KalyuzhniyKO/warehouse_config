from core.models import UserWarehouseAccess


def grant_warehouse_access(user, warehouses, can_delegate=False):
    if warehouses is None:
        return
    if not isinstance(warehouses, (list, tuple, set)):
        warehouses = [warehouses]
    for warehouse in warehouses:
        UserWarehouseAccess.objects.update_or_create(
            user=user,
            warehouse=warehouse,
            defaults={"is_active": True, "can_delegate": can_delegate},
        )
