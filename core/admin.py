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
    InventoryCount,
    InventoryCountLine,
    Item,
    LabelTemplate,
    Location,
    PrintJob,
    Printer,
    Recipient,
    StockBalance,
    UsagePlace,
    StockMovement,
    Unit,
    Warehouse,
)


def superuser_admin_has_permission(request):
    return request.user.is_active and request.user.is_superuser


admin.site.has_permission = superuser_admin_has_permission


admin.site.site_header = "YANTOS Warehouse Admin"
admin.site.site_title = "YANTOS Warehouse"
admin.site.index_title = "Панель керування складом"


@admin.action(description="Активувати вибрані записи")
def make_active(modeladmin, request, queryset):
    queryset.update(is_active=True)


@admin.action(description="Архівувати вибрані записи")
def make_inactive(modeladmin, request, queryset):
    queryset.update(is_active=False)


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
    actions = [make_active, make_inactive]
    list_display = ("name", "symbol", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "symbol")


@admin.register(Category)
class CategoryAdmin(IncludeCurrentRelationsAdminMixin, admin.ModelAdmin):
    actions = [make_active, make_inactive]
    form = CategoryForm
    list_display = ("name", "parent", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "parent__name")


@admin.register(Recipient)
class RecipientAdmin(admin.ModelAdmin):
    actions = [make_active, make_inactive]
    list_display = ("name", "contact_name", "phone", "email", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "contact_name", "phone", "email")


@admin.register(UsagePlace)
class UsagePlaceAdmin(admin.ModelAdmin):
    actions = [make_active, make_inactive]
    list_display = ("name", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name",)
    ordering = ("name",)


@admin.register(BarcodeRegistry)
class BarcodeRegistryAdmin(admin.ModelAdmin):
    actions = [make_active, make_inactive]
    list_display = ("barcode", "prefix", "is_active")
    list_filter = ("prefix", "is_active")
    search_fields = ("barcode", "description")


@admin.register(BarcodeSequence)
class BarcodeSequenceAdmin(admin.ModelAdmin):
    actions = [make_active, make_inactive]
    list_display = ("prefix", "next_number", "padding", "is_active")
    list_filter = ("prefix", "is_active")
    search_fields = ("prefix",)


@admin.register(Item)
class ItemAdmin(IncludeCurrentRelationsAdminMixin, admin.ModelAdmin):
    actions = [make_active, make_inactive]
    form = ItemForm
    list_per_page = 30
    list_select_related = ("category", "unit", "barcode")
    list_display = ("name", "internal_code", "category", "unit", "barcode", "is_active")
    list_filter = ("category", "unit", "is_active")
    search_fields = ("name", "internal_code", "barcode__barcode")
    autocomplete_fields = ("barcode",)


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    actions = [make_active, make_inactive]
    list_select_related = ("barcode",)
    list_display = ("name", "barcode", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "barcode__barcode", "address")
    autocomplete_fields = ("barcode",)


@admin.register(Location)
class LocationAdmin(IncludeCurrentRelationsAdminMixin, admin.ModelAdmin):
    actions = [make_active, make_inactive]
    form = LocationForm
    list_select_related = ("warehouse", "barcode")
    list_display = ("name", "warehouse", "location_type", "barcode", "is_active")
    list_filter = ("warehouse", "location_type", "is_active")
    search_fields = ("name", "warehouse__name", "barcode__barcode")
    autocomplete_fields = ("barcode",)


@admin.register(InventoryCount)
class InventoryCountAdmin(admin.ModelAdmin):
    list_per_page = 30
    list_select_related = ("warehouse", "location", "created_by")
    list_display = (
        "number",
        "warehouse",
        "location",
        "status",
        "started_at",
        "completed_at",
        "created_by",
    )
    list_filter = ("status", "warehouse", "started_at")
    search_fields = ("number", "warehouse__name", "location__name", "comment")


@admin.register(InventoryCountLine)
class InventoryCountLineAdmin(admin.ModelAdmin):
    list_per_page = 30
    list_select_related = ("inventory_count", "item", "location")
    list_display = (
        "inventory_count",
        "item",
        "location",
        "expected_qty",
        "actual_qty",
        "difference_qty",
    )
    list_filter = ("inventory_count__status", "location__warehouse")
    search_fields = (
        "inventory_count__number",
        "item__name",
        "item__internal_code",
        "location__name",
        "barcode",
    )


@admin.register(StockBalance)
class StockBalanceAdmin(IncludeCurrentRelationsAdminMixin, admin.ModelAdmin):
    actions = [make_active, make_inactive]
    form = StockBalanceAdminForm
    list_per_page = 30
    list_select_related = ("item", "location")
    list_display = ("item", "location", "qty", "is_active")
    list_filter = ("location__warehouse", "is_active")
    search_fields = ("item__name", "item__internal_code", "location__name")


@admin.register(StockMovement)
class StockMovementAdmin(IncludeCurrentRelationsAdminMixin, admin.ModelAdmin):
    actions = [make_active, make_inactive]
    form = StockMovementAdminForm
    list_per_page = 30
    list_select_related = (
        "item",
        "source_location",
        "destination_location",
        "recipient",
    )
    list_display = (
        "movement_type",
        "item",
        "qty",
        "source_location",
        "destination_location",
        "recipient",
        "issue_reason",
        "department",
        "document_number",
        "occurred_at",
        "is_active",
    )
    list_filter = ("movement_type", "issue_reason", "is_active", "occurred_at")
    search_fields = (
        "item__name",
        "item__internal_code",
        "source_location__name",
        "destination_location__name",
        "recipient__name",
        "department",
        "document_number",
        "comment",
    )
    date_hierarchy = "occurred_at"


@admin.register(Printer)
class PrinterAdmin(admin.ModelAdmin):
    actions = [make_active, make_inactive]
    form = PrinterForm
    list_display = ("name", "system_name", "is_default", "is_active")
    list_filter = ("is_default", "is_active")
    search_fields = ("name", "system_name")


@admin.register(LabelTemplate)
class LabelTemplateAdmin(admin.ModelAdmin):
    actions = [make_active, make_inactive]
    form = LabelTemplateForm
    list_display = ("name", "width_mm", "height_mm", "barcode_type", "is_default", "is_active")
    list_filter = ("is_default", "is_active", "barcode_type")
    search_fields = ("name",)


@admin.register(PrintJob)
class PrintJobAdmin(admin.ModelAdmin):
    list_per_page = 30
    list_select_related = ("item", "printer", "label_template", "user")
    list_display = ("item", "printer", "copies", "status", "created_at", "printed_at")
    list_filter = ("status", "printer", "created_at")
    search_fields = ("item__name", "barcode", "printer__name", "error_message")
    readonly_fields = ("created_at", "printed_at")
