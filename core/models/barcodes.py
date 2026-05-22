from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from .base import ActiveModel


class BarcodeRegistry(ActiveModel):
    class Prefix(models.TextChoices):
        ITEM = "ITM", _("Номенклатура")
        WAREHOUSE = "WH", _("Склад")
        RACK = "RCK", _("Стелаж")
        LOCATION = "LOC", _("Локація")

    barcode = models.CharField(_("barcode"), max_length=64, unique=True)
    prefix = models.CharField(_("prefix"), max_length=3, choices=Prefix.choices)
    description = models.CharField(_("description"), max_length=255, blank=True)

    class Meta:
        verbose_name = _("Реєстр штрихкодів")
        verbose_name_plural = _("Реєстр штрихкодів")
        ordering = ["barcode"]

    def clean(self):
        super().clean()
        if self.barcode and self.prefix and not self.barcode.startswith(self.prefix):
            raise ValidationError(
                {"barcode": _("Barcode must start with the selected prefix.")}
            )

    def __str__(self):
        return self.barcode


class BarcodeSequence(ActiveModel):
    prefix = models.CharField(
        _("prefix"), max_length=3, choices=BarcodeRegistry.Prefix.choices, unique=True
    )
    next_number = models.PositiveBigIntegerField(_("next number"), default=1)
    padding = models.PositiveSmallIntegerField(_("padding"), default=10)

    class Meta:
        verbose_name = _("Послідовність штрихкодів")
        verbose_name_plural = _("Послідовності штрихкодів")
        ordering = ["prefix"]

    def __str__(self):
        return f"{self.prefix}: {self.next_number}"
