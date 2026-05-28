from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class AuditLog(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Користувач"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
    )
    action = models.CharField(_("Дія"), max_length=100)
    object_type = models.CharField(_("Об'єкт"), max_length=100)
    object_id = models.CharField(_("ID об'єкта"), max_length=100, blank=True)
    object_repr = models.TextField(_("Об'єкт"), blank=True)
    changes = models.JSONField(_("Зміни"), default=dict, blank=True)
    ip_address = models.GenericIPAddressField(_("IP-адреса"), null=True, blank=True)
    user_agent = models.TextField(_("User agent"), blank=True)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)

    class Meta:
        verbose_name = _("Журнал аудиту")
        verbose_name_plural = _("Журнал аудиту")
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M:%S} {self.action}"
