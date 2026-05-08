from django.contrib.auth.mixins import UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext_lazy as _

WAREHOUSE_ADMIN_GROUP = "Адміністратор складу"
STOREKEEPER_GROUP = "Комірник"
AUDITOR_GROUP = "Перегляд / аудитор"

ANALYTICS_GROUPS = {WAREHOUSE_ADMIN_GROUP, AUDITOR_GROUP}
DIRECTORY_EDIT_GROUPS = {WAREHOUSE_ADMIN_GROUP}
USER_MANAGEMENT_GROUPS = {WAREHOUSE_ADMIN_GROUP}
STOCK_EDIT_GROUPS = {WAREHOUSE_ADMIN_GROUP, STOREKEEPER_GROUP}
STOCK_VIEW_GROUPS = {WAREHOUSE_ADMIN_GROUP, STOREKEEPER_GROUP, AUDITOR_GROUP}
PRINT_GROUPS = {WAREHOUSE_ADMIN_GROUP, STOREKEEPER_GROUP}
SETTINGS_GROUPS = {WAREHOUSE_ADMIN_GROUP}


def user_in_groups(user, group_names):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=group_names).exists()


class GroupRequiredMixin(UserPassesTestMixin):
    group_names = set()
    permission_denied_message = _("У вас немає прав для перегляду цієї сторінки.")

    def test_func(self):
        return user_in_groups(self.request.user, self.group_names)

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            raise PermissionDenied(self.get_permission_denied_message())
        return super().handle_no_permission()
