from django.db import IntegrityError, models
from django.utils.translation import gettext_lazy as _


class SystemSettings(models.Model):
    use_locations = models.BooleanField(
        _("Використовувати локації"),
        default=True,
    )
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        verbose_name = _("Налаштування системи")
        verbose_name_plural = _("Налаштування системи")

    @classmethod
    def get_solo(cls):
        instance = cls.objects.order_by("id").first()
        if instance is not None:
            return instance

        try:
            return cls.objects.create(pk=1, use_locations=True)
        except IntegrityError:
            instance = cls.objects.order_by("id").first()
            if instance is None:
                raise
            return instance

    def __str__(self):
        return str(_("Налаштування системи"))


class ActiveModel(models.Model):
    is_active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        abstract = True
