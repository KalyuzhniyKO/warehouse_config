from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum
from django.utils.translation import gettext_lazy as _


class PurchaseRequest(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Чернетка")
        PENDING_APPROVAL = "pending_approval", _("Очікує погодження")
        APPROVED = "approved", _("Погоджено")
        REJECTED = "rejected", _("Відхилено")
        ORDERED = "ordered", _("Замовлено")
        PARTIALLY_RECEIVED = "partially_received", _("Частково отримано")
        RECEIVED = "received", _("Отримано")
        CANCELLED = "cancelled", _("Скасовано")

    title = models.CharField(_("Назва / товар"), max_length=255)
    description = models.TextField(_("Опис"), blank=True)
    requested_qty = models.DecimalField(
        _("Запитана кількість"),
        max_digits=18,
        decimal_places=3,
        validators=[MinValueValidator(0.001)],
    )
    unit = models.CharField(_("Одиниця виміру"), max_length=64)
    estimated_unit_price = models.DecimalField(
        _("Орієнтовна ціна за одиницю"),
        max_digits=18,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    currency = models.CharField(_("Валюта"), max_length=8, default="UAH")
    supplier_name = models.CharField(_("Постачальник"), max_length=255)
    supplier_url = models.URLField(_("Посилання постачальника"), blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Заявник"),
        on_delete=models.PROTECT,
        related_name="purchase_requests",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Погодив"),
        on_delete=models.SET_NULL,
        related_name="approved_purchase_requests",
        blank=True,
        null=True,
    )
    approved_at = models.DateTimeField(_("Дата погодження"), blank=True, null=True)
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("Відхилив"),
        on_delete=models.SET_NULL,
        related_name="rejected_purchase_requests",
        blank=True,
        null=True,
    )
    rejected_at = models.DateTimeField(_("Дата відхилення"), blank=True, null=True)
    status = models.CharField(
        _("Статус"),
        max_length=24,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    receiving_base_status = models.CharField(
        max_length=24,
        choices=[
            (Status.APPROVED, Status.APPROVED.label),
            (Status.ORDERED, Status.ORDERED.label),
        ],
        blank=True,
    )
    comment = models.TextField(_("Коментар"), blank=True)
    created_at = models.DateTimeField(_("Створено"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Оновлено"), auto_now=True)

    class Meta:
        verbose_name = _("Заявка на закупівлю")
        verbose_name_plural = _("Заявки на закупівлю")
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(requested_qty__gt=0),
                name="purchase_request_requested_qty_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(estimated_unit_price__gte=0),
                name="purchase_request_estimated_price_non_negative",
            ),
        ]

    @property
    def estimated_total(self):
        return self.requested_qty * self.estimated_unit_price

    @property
    def received_qty(self):
        return self.linked_receive_movements.filter(
            movement_type="in",
            is_cancelled=False,
            reversal_of__isnull=True,
        ).aggregate(total=Sum("qty"))["total"] or Decimal("0")

    @property
    def remaining_qty(self):
        return max(self.requested_qty - self.received_qty, Decimal("0"))

    def __str__(self):
        return self.title
