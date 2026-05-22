from django.db import models
from django.utils.translation import gettext_lazy as _

from .base import ActiveModel


class Printer(ActiveModel):
    name = models.CharField(_("name"), max_length=150)
    system_name = models.CharField(_("system name"), max_length=150, unique=True)
    description = models.TextField(_("description"), blank=True)
    is_default = models.BooleanField(_("default"), default=False)

    class Meta:
        verbose_name = _("Принтер")
        verbose_name_plural = _("Принтери")
        ordering = ["name"]

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        self.system_name = self.system_name.strip()
        super().save(*args, **kwargs)
        if self.is_default:
            Printer.objects.exclude(pk=self.pk).update(is_default=False)

    def __str__(self):
        return self.name


class LabelTemplate(ActiveModel):
    class BarcodeType(models.TextChoices):
        CODE128 = "code128", _("Code 128")

    name = models.CharField(_("name"), max_length=150)
    width_mm = models.PositiveSmallIntegerField(_("width, mm"), default=58)
    height_mm = models.PositiveSmallIntegerField(_("height, mm"), default=40)
    show_item_name = models.BooleanField(_("show item name"), default=True)
    show_internal_code = models.BooleanField(_("show internal code"), default=True)
    show_barcode_text = models.BooleanField(_("show barcode text"), default=True)
    barcode_type = models.CharField(
        _("barcode type"), max_length=32, choices=BarcodeType.choices, default=BarcodeType.CODE128
    )
    is_default = models.BooleanField(_("default"), default=False)

    class Meta:
        verbose_name = _("Шаблон етикеток")
        verbose_name_plural = _("Шаблони етикеток")
        ordering = ["name"]

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        super().save(*args, **kwargs)
        if self.is_default:
            LabelTemplate.objects.exclude(pk=self.pk).update(is_default=False)

    def __str__(self):
        return self.name


class PrintJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", _("pending")
        PRINTED = "printed", _("printed")
        FAILED = "failed", _("failed")

    printer = models.ForeignKey(
        Printer, verbose_name=_("Принтер"), on_delete=models.PROTECT, related_name="print_jobs"
    )
    item = models.ForeignKey(
        "core.Item", verbose_name=_("Номенклатура"), on_delete=models.PROTECT, related_name="print_jobs"
    )
    barcode = models.CharField(_("barcode"), max_length=64)
    label_template = models.ForeignKey(
        LabelTemplate, verbose_name=_("Шаблон етикеток"), on_delete=models.PROTECT, related_name="print_jobs"
    )
    copies = models.PositiveSmallIntegerField(_("copies"), default=1)
    status = models.CharField(
        _("status"), max_length=20, choices=Status.choices, default=Status.PENDING
    )
    error_message = models.TextField(_("error message"), blank=True)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    printed_at = models.DateTimeField(_("printed at"), blank=True, null=True)
    user = models.ForeignKey(
        "auth.User", verbose_name=_("user"), on_delete=models.SET_NULL, blank=True, null=True, related_name="print_jobs"
    )

    class Meta:
        verbose_name = _("Завдання друку")
        verbose_name_plural = _("Завдання друку")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.item} × {self.copies} ({self.get_status_display()})"
