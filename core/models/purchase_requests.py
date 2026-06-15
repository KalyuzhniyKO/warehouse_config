from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class PurchaseRequest(models.Model):
    class OrderType(models.TextChoices):
        EMERGENCY = "emergency", _("Аварійний")
        URGENT = "urgent", _("Терміновий")
        PLANNED = "planned", _("Плановий")

    class ApprovalStatus(models.TextChoices):
        PENDING = "pending", _("Очікування")
        APPROVED = "approved", _("Погоджено")
        REJECTED = "rejected", _("Відхилено")

    class PaymentStatus(models.TextChoices):
        INVOICE_NOT_RECEIVED = "invoice_not_received", _("Рахунок не отримано")
        INVOICE_RECEIVED = "invoice_received", _("Рахунок отримано")
        SENT_FOR_PAYMENT = "sent_for_payment", _("Передано на оплату")
        PAID = "paid", _("Оплачено")
        NOT_REQUIRED = "not_required", _("Не потребує оплати")

    class DeliveryStatus(models.TextChoices):
        NOT_SHIPPED = "not_shipped", _("Не відправлено")
        IN_TRANSIT = "in_transit", _("В дорозі")
        DELIVERED = "delivered", _("Отримано")
        CANCELLED = "cancelled", _("Не актуально")

    class Status(models.TextChoices):
        DRAFT = "draft", _("Чернетка")
        PENDING_APPROVAL = "pending_approval", _("Очікує погодження")
        APPROVED = "approved", _("Погоджено")
        REJECTED = "rejected", _("Відхилено")
        ORDERED = "ordered", _("Замовлено")
        PARTIALLY_RECEIVED = "partially_received", _("Частково отримано")
        RECEIVED = "received", _("Отримано")
        CANCELLED = "cancelled", _("Скасовано")

    request_date = models.DateField(_("Дата"), default=timezone.localdate)
    title = models.CharField(_("Назва товару"), max_length=255)
    need_description = models.TextField(_("Опис потреби"), blank=True)
    requested_qty = models.DecimalField(
        _("Запитана кількість"),
        max_digits=18,
        decimal_places=3,
        validators=[MinValueValidator(0.001)],
    )
    unit = models.CharField(_("Одиниця виміру"), max_length=64)
    unit_price_uah = models.DecimalField(
        _("Вартість за одиницю (грн)"),
        max_digits=18,
        decimal_places=2,
        blank=True,
        null=True,
        validators=[MinValueValidator(0)],
    )
    order_type = models.CharField(
        _("Тип замовлення"),
        max_length=16,
        choices=OrderType.choices,
        default=OrderType.PLANNED,
    )
    approval_status = models.CharField(
        _("Статус погодження"),
        max_length=16,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.PENDING,
    )
    payment_status = models.CharField(
        _("Статус оплати"),
        max_length=24,
        choices=PaymentStatus.choices,
        default=PaymentStatus.INVOICE_NOT_RECEIVED,
    )
    delivery_status = models.CharField(
        _("Статус доставки"),
        max_length=16,
        choices=DeliveryStatus.choices,
        default=DeliveryStatus.NOT_SHIPPED,
    )
    currency = models.CharField(_("Валюта"), max_length=8, default="UAH")
    supplier_name = models.CharField(_("Постачальник"), max_length=255, blank=True)
    product_url = models.URLField(_("Посилання на товар"), blank=True)
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
                condition=models.Q(unit_price_uah__gte=0)
                | models.Q(unit_price_uah__isnull=True),
                name="purchase_request_unit_price_uah_non_negative",
            ),
        ]

    @property
    def total_price_uah(self):
        if self.unit_price_uah is None:
            return None
        return (self.requested_qty * self.unit_price_uah).quantize(Decimal("0.01"))

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
