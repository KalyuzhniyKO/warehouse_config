from django.contrib.auth.mixins import UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext_lazy as _

WAREHOUSE_ADMIN_GROUP = "Адміністратор складу"
STOREKEEPER_GROUP = "Комірник"
AUDITOR_GROUP = "Перегляд / аудитор"

ROLE_DISPLAY_NAMES = {
    WAREHOUSE_ADMIN_GROUP: _("Адміністратор"),
    STOREKEEPER_GROUP: _("Користувач"),
}

ROLE_DESCRIPTIONS = {
    WAREHOUSE_ADMIN_GROUP: _("Керує складом і користувачами"),
    STOREKEEPER_GROUP: _("Простий складський інтерфейс"),
}

MANAGEMENT_GROUPS = {WAREHOUSE_ADMIN_GROUP}
ANALYTICS_GROUPS = {WAREHOUSE_ADMIN_GROUP}
DIRECTORY_EDIT_GROUPS = {WAREHOUSE_ADMIN_GROUP}
USER_MANAGEMENT_GROUPS = {WAREHOUSE_ADMIN_GROUP}
STOCK_EDIT_GROUPS = {WAREHOUSE_ADMIN_GROUP, STOREKEEPER_GROUP}
STOCK_VIEW_GROUPS = {WAREHOUSE_ADMIN_GROUP, STOREKEEPER_GROUP, AUDITOR_GROUP}
PRINT_GROUPS = {WAREHOUSE_ADMIN_GROUP, STOREKEEPER_GROUP}
SETTINGS_GROUPS = {WAREHOUSE_ADMIN_GROUP}

WAREHOUSE_ACCESS_PERMISSION = "core.can_access_warehouse"
PURCHASE_REQUEST_VIEW_PERMISSION = "core.can_view_purchase_requests"
PURCHASE_REQUEST_CREATE_PERMISSION = "core.can_create_purchase_requests"
PURCHASE_REQUEST_APPROVE_PERMISSION = "core.can_approve_purchase_requests"
PURCHASE_REQUEST_TRACKING_PERMISSION = "core.can_update_purchase_request_tracking"

EXPLICIT_USER_PERMISSION_CODENAMES = {
    "can_access_warehouse",
    "can_view_purchase_requests",
    "can_create_purchase_requests",
    "can_approve_purchase_requests",
    "can_update_purchase_request_tracking",
}


def user_in_groups(user, group_names):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=group_names).exists()


def can_manage_users(user):
    return user_in_groups(user, USER_MANAGEMENT_GROUPS)


def can_view_audit(user):
    return bool(getattr(user, "is_authenticated", False) and user.is_superuser)


def can_cancel_movement(user, movement=None):
    return bool(getattr(user, "is_authenticated", False) and user.is_superuser)


def can_assign_warehouse_access(user, warehouse=None):
    if not getattr(user, "is_authenticated", False):
        return False
    from core.services.warehouse_access import (  # noqa: PLC0415
        get_delegatable_warehouses,
        user_can_delegate_warehouse,
    )

    if warehouse is not None:
        return user_can_delegate_warehouse(user, warehouse)
    return get_delegatable_warehouses(user).exists()


def can_view_warehouse_data(user, warehouse=None):
    if not getattr(user, "is_authenticated", False):
        return False
    from core.services.warehouse_access import (  # noqa: PLC0415
        get_accessible_warehouses,
        user_can_access_warehouse,
    )

    if warehouse is not None:
        return user_can_access_warehouse(user, warehouse)
    return get_accessible_warehouses(user).exists()


def can_view_analytics(user):
    return user_in_groups(user, ANALYTICS_GROUPS)


def can_manage_purchase_requests(user):
    return user_in_groups(user, MANAGEMENT_GROUPS)


def has_explicit_permission(user, permission):
    return bool(
        getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
        and (getattr(user, "is_superuser", False) or user.has_perm(permission))
    )


def can_access_warehouse(user):
    if not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    if user.has_perm(WAREHOUSE_ACCESS_PERMISSION):
        return True
    # Compatibility: existing warehouse roles and delegated warehouse access keep working.
    return user_in_groups(user, STOCK_VIEW_GROUPS) or can_view_warehouse_data(user)


def has_purchase_request_view_permission(user):
    return has_explicit_permission(user, PURCHASE_REQUEST_VIEW_PERMISSION)


def can_create_purchase_requests(user):
    return (
        can_manage_purchase_requests(user)
        or has_explicit_permission(user, PURCHASE_REQUEST_CREATE_PERMISSION)
        or can_view_warehouse_data(user)
    )


def can_view_purchase_requests(user):
    return (
        can_manage_purchase_requests(user)
        or has_purchase_request_view_permission(user)
        or can_create_purchase_requests(user)
    )


def can_approve_purchase_requests(user):
    return can_manage_purchase_requests(user) or has_explicit_permission(
        user, PURCHASE_REQUEST_APPROVE_PERMISSION
    )


def can_update_purchase_request_tracking(user):
    return can_manage_purchase_requests(user) or has_explicit_permission(
        user, PURCHASE_REQUEST_TRACKING_PERMISSION
    )


def can_manage_directories(user):
    return user_in_groups(user, DIRECTORY_EDIT_GROUPS)


def can_print_labels(user):
    return user_in_groups(user, PRINT_GROUPS)


def can_manage_settings(user):
    return user_in_groups(user, SETTINGS_GROUPS)


class GroupRequiredMixin(UserPassesTestMixin):
    group_names = set()
    permission_denied_message = _("У вас немає прав для перегляду цієї сторінки.")

    def test_func(self):
        return user_in_groups(self.request.user, self.group_names)

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            raise PermissionDenied(self.get_permission_denied_message())
        return super().handle_no_permission()
