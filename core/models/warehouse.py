from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from .base import ActiveModel
from .barcodes import BarcodeRegistry


class Item(ActiveModel):
    name = models.CharField(_("name"), max_length=200)
    internal_code = models.CharField(
        _("internal code"), max_length=64, blank=True, null=True
    )
    category = models.ForeignKey(
        "core.Category",
        verbose_name=_("Категорія"),
        on_delete=models.PROTECT,
        related_name="items",
        blank=True,
        null=True,
    )
    unit = models.ForeignKey(
        "core.Unit",
        verbose_name=_("Одиниця виміру"),
        on_delete=models.PROTECT,
        related_name="items",
    )
    barcode = models.OneToOneField(
        BarcodeRegistry,
        verbose_name=_("barcode"),
        on_delete=models.PROTECT,
        related_name="item",
        blank=True,
        null=True,
        limit_choices_to={"prefix": BarcodeRegistry.Prefix.ITEM},
    )
    description = models.TextField(_("description"), blank=True)

    class Meta:
        verbose_name = _("Номенклатура")
        verbose_name_plural = _("Номенклатура")
        ordering = ["name"]

    def clean(self):
        super().clean()
        if self.barcode_id and self.barcode.prefix != BarcodeRegistry.Prefix.ITEM:
            raise ValidationError({"barcode": _("Item barcode must use the ITM prefix.")})

    def save(self, *args, **kwargs):
        generate_barcode = kwargs.pop("generate_barcode", True)
        self.name = self.name.strip()
        if self.internal_code is not None:
            self.internal_code = self.internal_code.strip() or None
        super().save(*args, **kwargs)
        if generate_barcode and not self.barcode_id:
            from core.services.barcodes import ensure_item_barcode

            ensure_item_barcode(self)

    @property
    def barcode_value(self):
        return self.barcode.barcode if self.barcode_id else ""

    def __str__(self):
        return self.name


class Warehouse(ActiveModel):
    name = models.CharField(_("name"), max_length=150)
    barcode = models.OneToOneField(
        BarcodeRegistry,
        verbose_name=_("barcode"),
        on_delete=models.PROTECT,
        related_name="warehouse",
        blank=True,
        null=True,
        limit_choices_to={"prefix": BarcodeRegistry.Prefix.WAREHOUSE},
    )
    address = models.TextField(_("address"), blank=True)

    class Meta:
        verbose_name = _("Склад")
        verbose_name_plural = _("Склади")
        ordering = ["name"]

    def clean(self):
        super().clean()
        if self.barcode_id and self.barcode.prefix != BarcodeRegistry.Prefix.WAREHOUSE:
            raise ValidationError({"barcode": _("Warehouse barcode must use the WH prefix.")})

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        super().save(*args, **kwargs)
        if not self.barcode_id:
            from core.services.barcodes import ensure_warehouse_barcode

            ensure_warehouse_barcode(self)

    @property
    def barcode_value(self):
        return self.barcode.barcode if self.barcode_id else ""

    def __str__(self):
        return self.name


class Location(ActiveModel):
    class LocationType(models.TextChoices):
        LOCATION = "location", _("Локація")
        RACK = "rack", _("Стелаж")

    warehouse = models.ForeignKey(
        Warehouse,
        verbose_name=_("Склад"),
        on_delete=models.PROTECT,
        related_name="locations",
    )
    name = models.CharField(_("name"), max_length=150)
    location_type = models.CharField(
        _("location type"),
        max_length=20,
        choices=LocationType.choices,
        default=LocationType.LOCATION,
    )
    barcode = models.OneToOneField(
        BarcodeRegistry,
        verbose_name=_("barcode"),
        on_delete=models.PROTECT,
        related_name="location",
        blank=True,
        null=True,
        limit_choices_to={"prefix__in": [BarcodeRegistry.Prefix.LOCATION, BarcodeRegistry.Prefix.RACK]},
    )

    class Meta:
        verbose_name = _("Локація")
        verbose_name_plural = _("Локації")
        ordering = ["warehouse__name", "name"]

    def clean(self):
        super().clean()
        if not self.barcode_id:
            return
        expected_prefix = (
            BarcodeRegistry.Prefix.RACK
            if self.location_type == self.LocationType.RACK
            else BarcodeRegistry.Prefix.LOCATION
        )
        if self.barcode.prefix != expected_prefix:
            raise ValidationError(
                {"barcode": _("Location barcode prefix does not match its type.")}
            )

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        super().save(*args, **kwargs)
        if not self.barcode_id:
            from core.services.barcodes import ensure_location_barcode

            ensure_location_barcode(self)

    @property
    def barcode_value(self):
        return self.barcode.barcode if self.barcode_id else ""

    def __str__(self):
        return f"{self.warehouse} / {self.name}"
