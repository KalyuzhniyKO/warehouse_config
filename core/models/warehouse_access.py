from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class UserWarehouseAccess(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Користувач"),
        on_delete=models.CASCADE,
        related_name="warehouse_accesses",
    )
    warehouse = models.ForeignKey(
        "core.Warehouse",
        verbose_name=_("Склад"),
        on_delete=models.CASCADE,
        related_name="user_accesses",
    )
    can_delegate = models.BooleanField(
        default=False, verbose_name=_("Може делегувати доступ")
    )
    is_active = models.BooleanField(default=True, verbose_name=_("Активний"))
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Створив"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_warehouse_accesses",
    )
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        verbose_name = _("Доступ до складу")
        verbose_name_plural = _("Доступ до складів")
        ordering = ["user__username", "warehouse__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "warehouse"],
                name="core_user_warehouse_access_unique_user_warehouse",
            )
        ]

    def __str__(self):
        return f"{self.user} / {self.warehouse}"
