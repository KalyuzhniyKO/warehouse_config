from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .base import ActiveModel


class StockBalance(ActiveModel):
    item = models.ForeignKey(
        "core.Item",
        verbose_name=_("Номенклатура"),
        on_delete=models.PROTECT,
        related_name="stock_balances",
    )
    location = models.ForeignKey(
        "core.Location",
        verbose_name=_("Локація"),
        on_delete=models.PROTECT,
        related_name="stock_balances",
    )
    qty = models.DecimalField(_("quantity"), max_digits=18, decimal_places=3, default=0)

    class Meta:
        verbose_name = _("Залишок")
        verbose_name_plural = _("Залишки")
        ordering = ["item__name", "location__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["item", "location"],
                name="core_stock_balance_unique_item_location",
            )
        ]

    def __str__(self):
        return f"{self.item} @ {self.location}: {self.qty}"


class StockMovement(ActiveModel):
    class IssueReason(models.TextChoices):
        SALE = "sale", _("Продаж")
        REPAIR = "repair", _("Ремонтні роботи")
        PRODUCTION = "production", _("Виробничі потреби")
        OTHER = "other", _("Інше")

    class MovementType(models.TextChoices):
        INITIAL_BALANCE = "initial_balance", _("initial balance")
        IN = "in", _("in")
        OUT = "out", _("out")
        RETURN = "return", _("return")
        WRITEOFF = "writeoff", _("write-off")
        TRANSFER = "transfer", _("transfer")
        ADJUSTMENT = "adjustment", _("adjustment")

    movement_type = models.CharField(
        _("movement type"), max_length=20, choices=MovementType.choices
    )
    item = models.ForeignKey(
        "core.Item",
        verbose_name=_("Номенклатура"),
        on_delete=models.PROTECT,
        related_name="stock_movements",
    )
    qty = models.DecimalField(_("quantity"), max_digits=18, decimal_places=3)
    source_location = models.ForeignKey(
        "core.Location",
        verbose_name=_("source location"),
        on_delete=models.PROTECT,
        related_name="outgoing_stock_movements",
        blank=True,
        null=True,
    )
    destination_location = models.ForeignKey(
        "core.Location",
        verbose_name=_("destination location"),
        on_delete=models.PROTECT,
        related_name="incoming_stock_movements",
        blank=True,
        null=True,
    )
    recipient = models.ForeignKey(
        "core.Recipient",
        verbose_name=_("Отримувач"),
        on_delete=models.PROTECT,
        related_name="stock_movements",
        blank=True,
        null=True,
    )
    inventory_count = models.ForeignKey(
        "core.InventoryCount",
        verbose_name=_("Inventory count"),
        on_delete=models.SET_NULL,
        related_name="stock_movements",
        blank=True,
        null=True,
    )
    issue_reason = models.CharField(
        _("Тип видачі"),
        max_length=20,
        choices=IssueReason.choices,
        blank=True,
    )
    department = models.CharField(_("Цех / підрозділ"), max_length=200, blank=True)
    document_number = models.CharField(_("Номер документа"), max_length=100, blank=True)
    occurred_at = models.DateTimeField(_("occurred at"), default=timezone.now)
    comment = models.TextField(_("comment"), blank=True)

    class Meta:
        verbose_name = _("Рух товарів")
        verbose_name_plural = _("Рухи товарів")
        ordering = ["-occurred_at", "-id"]

    def __str__(self):
        return f"{self.get_movement_type_display()} {self.item}: {self.qty}"
