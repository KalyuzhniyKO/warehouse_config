from django.db import models
from django.utils.translation import gettext_lazy as _

from .base import ActiveModel


class Unit(ActiveModel):
    name = models.CharField(_("name"), max_length=100)
    symbol = models.CharField(_("symbol"), max_length=20)

    class Meta:
        verbose_name = _("Одиниця виміру")
        verbose_name_plural = _("Одиниці виміру")
        ordering = ["name"]

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        self.symbol = self.symbol.strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.symbol


class Category(ActiveModel):
    name = models.CharField(_("name"), max_length=150)
    parent = models.ForeignKey(
        "self",
        verbose_name=_("parent category"),
        on_delete=models.PROTECT,
        related_name="children",
        blank=True,
        null=True,
    )

    class Meta:
        verbose_name = _("Категорія")
        verbose_name_plural = _("Категорії")
        ordering = ["name"]

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class UsagePlace(ActiveModel):
    name = models.CharField(_("name"), max_length=200, unique=True)
    note = models.TextField(_("note"), blank=True)

    class Meta:
        verbose_name = _("Цех / місце використання")
        verbose_name_plural = _("Цехи / місця використання")
        ordering = ["name"]

    def __str__(self):
        return self.name


class Recipient(ActiveModel):
    name = models.CharField(_("name"), max_length=200)
    contact_name = models.CharField(_("contact name"), max_length=150, blank=True)
    phone = models.CharField(_("phone"), max_length=50, blank=True)
    email = models.EmailField(_("email"), blank=True)
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        verbose_name = _("Отримувач")
        verbose_name_plural = _("Отримувачі")
        ordering = ["name"]

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        self.contact_name = self.contact_name.strip()
        self.phone = self.phone.strip()
        self.email = self.email.strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name
