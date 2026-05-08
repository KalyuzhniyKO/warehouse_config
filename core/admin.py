from django.contrib import admin

from .forms import (
    CategoryForm,
    ItemForm,
    LabelTemplateForm,
    LocationForm,
    StockBalanceAdminForm,
    StockMovementAdminForm,
    PrinterForm,
)
from .models import (
    BarcodeRegistry,
    BarcodeSequence,
    Category,
    Item,
    LabelTemplate,
    Location,
    PrintJob,
    Printer,
    Recipient,
    StockBalance,
    StockMovement,
    Unit,
    Warehouse,
)


class IncludeCurrentRelationsAdminMixin:
    """Pass current archived relations to admin forms so existing records remain editable."""

    def get_form(self, request, obj=None, change=False, **kwargs):
        form_class = super().get_form(request, obj, change, **kwargs)

        class AdminForm(form_class):
            def __init__(self, *args, **form_kwargs):
                form_kwargs["include_current_relations"] = True
                super().__init__(*args, **form_kwargs)

        return AdminForm


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ("name", "symbol", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "symbol")


@admin.register(Category)
class CategoryAdmin(IncludeCurrentRelationsAdminMixin, admin.ModelAdmin):
    form = CategoryForm
    list_display = ("name", "parent", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "parent__name")


@admin.register(Recipient)
class RecipientAdmin(admin.ModelAdmin):
    list_display = ("name", "contact_name", "phone", "email", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "contact_name", "phone", "email")


@admin.register(BarcodeRegistry)
class BarcodeRegistryAdmin(admin.ModelAdmin):
    list_display = ("barcode", "prefix", "is_active")
    list_filter = ("prefix", "is_active")
    search_fields = ("barcode", "description")


@admin.register(BarcodeSequence)
class BarcodeSequenceAdmin(admin.ModelAdmin):
    list_display = ("prefix", "next_number", "padding", "is_active")
    list_filter = ("prefix", "is_active")
    search_fields = ("prefix",)


@admin.register(Item)
class ItemAdmin(IncludeCurrentRelationsAdminMixin, admin.ModelAdmin):
    form = ItemForm
    list_display = ("name", "internal_code", "category", "unit", "barcode", "is_active")
    list_filter = ("category", "unit", "is_active")
    search_fields = ("name", "internal_code", "barcode__barcode")
    autocomplete_fields = ("barcode",)


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ("name", "barcode", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "barcode__barcode", "address")
    autocomplete_fields = ("barcode",)


@admin.register(Location)
class LocationAdmin(IncludeCurrentRelationsAdminMixin, admin.ModelAdmin):
    form = LocationForm
    list_display = ("name", "warehouse", "location_type", "barcode", "is_active")
    list_filter = ("warehouse", "location_type", "is_active")
    search_fields = ("name", "warehouse__name", "barcode__barcode")
    autocomplete_fields = ("barcode",)


@admin.register(StockBalance)
class StockBalanceAdmin(IncludeCurrentRelationsAdminMixin, admin.ModelAdmin):
    form = StockBalanceAdminForm
    list_display = ("item", "location", "qty", "is_active")
    list_filter = ("location__warehouse", "is_active")
    search_fields = ("item__name", "item__internal_code", "location__name")


@admin.register(StockMovement)
class StockMovementAdmin(IncludeCurrentRelationsAdminMixin, admin.ModelAdmin):
    form = StockMovementAdminForm
    list_display = (
        "movement_type",
        "item",
        "qty",
        "source_location",
        "destination_location",
        "recipient",
        "occurred_at",
        "is_active",
    )
    list_filter = ("movement_type", "is_active", "occurred_at")
    search_fields = (
        "item__name",
        "item__internal_code",
        "source_location__name",
        "destination_location__name",
        "recipient__name",
        "comment",
    )
    date_hierarchy = "occurred_at"


@admin.register(Printer)
class PrinterAdmin(admin.ModelAdmin):
    form = PrinterForm
    list_display = ("name", "system_name", "is_default", "is_active")
    list_filter = ("is_default", "is_active")
    search_fields = ("name", "system_name")


@admin.register(LabelTemplate)
class LabelTemplateAdmin(admin.ModelAdmin):
    form = LabelTemplateForm
    list_display = ("name", "width_mm", "height_mm", "barcode_type", "is_default", "is_active")
    list_filter = ("is_default", "is_active", "barcode_type")
    search_fields = ("name",)


@admin.register(PrintJob)
class PrintJobAdmin(admin.ModelAdmin):
    list_display = ("item", "printer", "copies", "status", "created_at", "printed_at")
    list_filter = ("status", "printer", "created_at")
    search_fields = ("item__name", "barcode", "printer__name", "error_message")
    readonly_fields = ("created_at", "printed_at")
