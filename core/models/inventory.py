from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .base import ActiveModel


class InventoryCount(ActiveModel):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        IN_PROGRESS = "in_progress", _("In progress")
        COMPLETED = "completed", _("Completed")
        CANCELLED = "cancelled", _("Cancelled")

    number = models.CharField(_("number"), max_length=14, unique=True)
    warehouse = models.ForeignKey(
        "core.Warehouse",
        verbose_name=_("Склад"),
        on_delete=models.PROTECT,
        related_name="inventory_counts",
    )
    location = models.ForeignKey(
        "core.Location",
        verbose_name=_("Локація"),
        on_delete=models.PROTECT,
        related_name="inventory_counts",
        blank=True,
        null=True,
    )
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    started_at = models.DateTimeField(_("started at"), default=timezone.now)
    completed_at = models.DateTimeField(_("completed at"), blank=True, null=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("created by"),
        on_delete=models.SET_NULL,
        related_name="created_inventory_counts",
        blank=True,
        null=True,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("approved by"),
        on_delete=models.SET_NULL,
        related_name="approved_inventory_counts",
        blank=True,
        null=True,
    )
    comment = models.TextField(_("comment"), blank=True)

    class Meta:
        verbose_name = _("Inventory count")
        verbose_name_plural = _("Inventory counts")
        ordering = ["-started_at", "-id"]

    def __str__(self):
        return self.number


class InventoryCountLine(ActiveModel):
    inventory_count = models.ForeignKey(
        InventoryCount,
        verbose_name=_("Inventory count"),
        on_delete=models.CASCADE,
        related_name="lines",
    )
    item = models.ForeignKey(
        "core.Item",
        verbose_name=_("Номенклатура"),
        on_delete=models.PROTECT,
        related_name="inventory_count_lines",
    )
    location = models.ForeignKey(
        "core.Location",
        verbose_name=_("Локація"),
        on_delete=models.PROTECT,
        related_name="inventory_count_lines",
    )
    barcode = models.CharField(_("barcode"), max_length=64, blank=True)
    expected_qty = models.DecimalField(
        _("expected quantity"), max_digits=18, decimal_places=3
    )
    actual_qty = models.DecimalField(
        _("actual quantity"), max_digits=18, decimal_places=3, blank=True, null=True
    )
    difference_qty = models.DecimalField(
        _("difference quantity"), max_digits=18, decimal_places=3, default=0
    )
    comment = models.TextField(_("comment"), blank=True)
    counted_at = models.DateTimeField(_("counted at"), blank=True, null=True)
    counted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("counted by"),
        on_delete=models.SET_NULL,
        related_name="inventory_count_lines",
        blank=True,
        null=True,
    )

    class Meta:
        verbose_name = _("Inventory count line")
        verbose_name_plural = _("Inventory count lines")
        ordering = ["inventory_count", "item__name", "location__name", "id"]

    def save(self, *args, **kwargs):
        expected_qty = getattr(self, "expected_qty_at_count_time", self.expected_qty)
        self.difference_qty = (
            self.actual_qty - expected_qty if self.actual_qty is not None else 0
        )
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "actual_qty" in update_fields:
            kwargs["update_fields"] = set(update_fields) | {"difference_qty"}
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.inventory_count} / {self.item} @ {self.location}"
