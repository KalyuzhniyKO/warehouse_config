from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class ActiveModel(models.Model):
    is_active = models.BooleanField(_("active"), default=True)
    created_at = models.DateTimeField(_("created at"), auto_now_add=True)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        abstract = True


class Unit(ActiveModel):
    name = models.CharField(_("name"), max_length=100)
    symbol = models.CharField(_("symbol"), max_length=20)

    class Meta:
        verbose_name = _("unit")
        verbose_name_plural = _("units")
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
        verbose_name = _("category")
        verbose_name_plural = _("categories")
        ordering = ["name"]

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Recipient(ActiveModel):
    name = models.CharField(_("name"), max_length=200)
    contact_name = models.CharField(_("contact name"), max_length=150, blank=True)
    phone = models.CharField(_("phone"), max_length=50, blank=True)
    email = models.EmailField(_("email"), blank=True)
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        verbose_name = _("recipient")
        verbose_name_plural = _("recipients")
        ordering = ["name"]

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        self.contact_name = self.contact_name.strip()
        self.phone = self.phone.strip()
        self.email = self.email.strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class BarcodeRegistry(ActiveModel):
    class Prefix(models.TextChoices):
        ITEM = "ITM", _("item")
        WAREHOUSE = "WH", _("warehouse")
        RACK = "RCK", _("rack")
        LOCATION = "LOC", _("location")

    barcode = models.CharField(_("barcode"), max_length=64, unique=True)
    prefix = models.CharField(_("prefix"), max_length=3, choices=Prefix.choices)
    description = models.CharField(_("description"), max_length=255, blank=True)

    class Meta:
        verbose_name = _("barcode registry entry")
        verbose_name_plural = _("barcode registry entries")
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
        verbose_name = _("barcode sequence")
        verbose_name_plural = _("barcode sequences")
        ordering = ["prefix"]

    def __str__(self):
        return f"{self.prefix}: {self.next_number}"


class Item(ActiveModel):
    name = models.CharField(_("name"), max_length=200)
    internal_code = models.CharField(
        _("internal code"), max_length=64, blank=True, null=True
    )
    category = models.ForeignKey(
        Category,
        verbose_name=_("category"),
        on_delete=models.PROTECT,
        related_name="items",
        blank=True,
        null=True,
    )
    unit = models.ForeignKey(
        Unit,
        verbose_name=_("unit"),
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
        verbose_name = _("item")
        verbose_name_plural = _("items")
        ordering = ["name"]

    def clean(self):
        super().clean()
        if self.barcode_id and self.barcode.prefix != BarcodeRegistry.Prefix.ITEM:
            raise ValidationError({"barcode": _("Item barcode must use the ITM prefix.")})

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        if self.internal_code is not None:
            self.internal_code = self.internal_code.strip() or None
        super().save(*args, **kwargs)
        if not self.barcode_id:
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
        verbose_name = _("warehouse")
        verbose_name_plural = _("warehouses")
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
        LOCATION = "location", _("location")
        RACK = "rack", _("rack")

    warehouse = models.ForeignKey(
        Warehouse,
        verbose_name=_("warehouse"),
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
        verbose_name = _("location")
        verbose_name_plural = _("locations")
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


class StockBalance(ActiveModel):
    item = models.ForeignKey(
        Item,
        verbose_name=_("item"),
        on_delete=models.PROTECT,
        related_name="stock_balances",
    )
    location = models.ForeignKey(
        Location,
        verbose_name=_("location"),
        on_delete=models.PROTECT,
        related_name="stock_balances",
    )
    qty = models.DecimalField(_("quantity"), max_digits=18, decimal_places=3, default=0)

    class Meta:
        verbose_name = _("stock balance")
        verbose_name_plural = _("stock balances")
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
        Item,
        verbose_name=_("item"),
        on_delete=models.PROTECT,
        related_name="stock_movements",
    )
    qty = models.DecimalField(_("quantity"), max_digits=18, decimal_places=3)
    source_location = models.ForeignKey(
        Location,
        verbose_name=_("source location"),
        on_delete=models.PROTECT,
        related_name="outgoing_stock_movements",
        blank=True,
        null=True,
    )
    destination_location = models.ForeignKey(
        Location,
        verbose_name=_("destination location"),
        on_delete=models.PROTECT,
        related_name="incoming_stock_movements",
        blank=True,
        null=True,
    )
    recipient = models.ForeignKey(
        Recipient,
        verbose_name=_("recipient"),
        on_delete=models.PROTECT,
        related_name="stock_movements",
        blank=True,
        null=True,
    )
    occurred_at = models.DateTimeField(_("occurred at"), default=timezone.now)
    comment = models.TextField(_("comment"), blank=True)

    class Meta:
        verbose_name = _("stock movement")
        verbose_name_plural = _("stock movements")
        ordering = ["-occurred_at", "-id"]

    def __str__(self):
        return f"{self.get_movement_type_display()} {self.item}: {self.qty}"


class Printer(ActiveModel):
    name = models.CharField(_("name"), max_length=150)
    system_name = models.CharField(_("system name"), max_length=150, unique=True)
    description = models.TextField(_("description"), blank=True)
    is_default = models.BooleanField(_("default"), default=False)

    class Meta:
        verbose_name = _("printer")
        verbose_name_plural = _("printers")
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
        verbose_name = _("label template")
        verbose_name_plural = _("label templates")
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
        Printer, verbose_name=_("printer"), on_delete=models.PROTECT, related_name="print_jobs"
    )
    item = models.ForeignKey(
        Item, verbose_name=_("item"), on_delete=models.PROTECT, related_name="print_jobs"
    )
    barcode = models.CharField(_("barcode"), max_length=64)
    label_template = models.ForeignKey(
        LabelTemplate, verbose_name=_("label template"), on_delete=models.PROTECT, related_name="print_jobs"
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
        verbose_name = _("print job")
        verbose_name_plural = _("print jobs")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.item} × {self.copies} ({self.get_status_display()})"
