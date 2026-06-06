from django.contrib import admin
from django.utils.html import format_html

from .forms import (
    CategoryForm,
    ItemForm,
    LabelTemplateForm,
    LocationForm,
    PrinterForm,
    StockBalanceAdminForm,
    StockMovementAdminForm,
)
from .models import (
    AuditLog,
    SystemSettings,
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
    StockMovement,
    Unit,
    UsagePlace,
    UserWarehouseAccess,
    Warehouse,
)


def superuser_admin_has_permission(request):
    return request.user.is_active and request.user.is_superuser


admin.site.has_permission = superuser_admin_has_permission
admin.site.site_header = "YANTOS Warehouse Admin"
admin.site.site_title = "YANTOS Warehouse"
admin.site.index_title = "Панель адміністрування"


@admin.action(description="Активувати вибрані записи")
def make_active(modeladmin, request, queryset):
    queryset.update(is_active=True)


@admin.action(description="Архівувати вибрані записи")
def make_inactive(modeladmin, request, queryset):
    queryset.update(is_active=False)


class IncludeCurrentRelationsAdminMixin:
    def get_form(self, request, obj=None, change=False, **kwargs):
        form_class = super().get_form(request, obj, change, **kwargs)

        class AdminForm(form_class):
            def __init__(self, *args, **form_kwargs):
                form_kwargs["include_current_relations"] = True
                super().__init__(*args, **form_kwargs)

        return AdminForm


class ActiveBadgeAdminMixin:
    @admin.display(description="Статус", ordering="is_active")
    def active_badge(self, obj):
        css = "active" if obj.is_active else "archived"
        label = "Активний" if obj.is_active else "Архів"
        return format_html('<span class="status-badge status-badge--{}">{}</span>', css, label)


@admin.register(Unit)
class UnitAdmin(ActiveBadgeAdminMixin, admin.ModelAdmin):
    actions = [make_active, make_inactive]
    list_display = ("name", "symbol", "active_badge")
    list_filter = ("is_active",)
    search_fields = ("name", "symbol")
    list_per_page = 30


@admin.register(Category)
class CategoryAdmin(ActiveBadgeAdminMixin, IncludeCurrentRelationsAdminMixin, admin.ModelAdmin):
    actions = [make_active, make_inactive]
    form = CategoryForm
    list_display = ("name", "parent", "active_badge")
    list_filter = ("is_active",)
    search_fields = ("name", "parent__name")
    list_per_page = 30


@admin.register(Recipient)
class RecipientAdmin(ActiveBadgeAdminMixin, admin.ModelAdmin):
    actions = [make_active, make_inactive]
    list_display = ("name", "contact_name", "phone", "email", "active_badge")
    list_filter = ("is_active",)
    search_fields = ("name", "contact_name", "phone", "email")
    list_per_page = 30


@admin.register(UsagePlace)
class UsagePlaceAdmin(ActiveBadgeAdminMixin, admin.ModelAdmin):
    actions = [make_active, make_inactive]
    list_display = ("name", "note", "active_badge", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name",)
    ordering = ("name",)
    readonly_fields = ("created_at", "updated_at")
    list_per_page = 30


@admin.register(BarcodeRegistry)
class BarcodeRegistryAdmin(ActiveBadgeAdminMixin, admin.ModelAdmin):
    actions = [make_active, make_inactive]
    list_display = ("barcode", "prefix", "active_badge")
    list_filter = ("prefix", "is_active")
    search_fields = ("barcode", "description")
    list_per_page = 30


@admin.register(BarcodeSequence)
class BarcodeSequenceAdmin(ActiveBadgeAdminMixin, admin.ModelAdmin):
    actions = [make_active, make_inactive]
    list_display = ("prefix", "next_number", "padding", "active_badge")
    list_filter = ("prefix", "is_active")
    search_fields = ("prefix",)
    list_per_page = 30


@admin.register(Item)
class ItemAdmin(ActiveBadgeAdminMixin, IncludeCurrentRelationsAdminMixin, admin.ModelAdmin):
    actions = [make_active, make_inactive]
    form = ItemForm
    list_per_page = 30
    list_select_related = ("category", "unit", "barcode")
    list_display = ("internal_code", "barcode", "name", "category", "unit", "active_badge")
    list_filter = ("category", "is_active")
    search_fields = ("name", "internal_code", "barcode__barcode")
    ordering = ("name",)
    autocomplete_fields = ("barcode",)
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("Основне", {"fields": ("name", "internal_code", "description")}),
        ("Класифікація", {"fields": ("category", "unit")}),
        ("Штрихкод / службове", {"fields": ("barcode", "is_active", "created_at", "updated_at")}),
    )


@admin.register(Warehouse)
class WarehouseAdmin(ActiveBadgeAdminMixin, admin.ModelAdmin):
    actions = [make_active, make_inactive]
    list_select_related = ("barcode",)
    list_display = ("name", "barcode", "active_badge")
    list_filter = ("is_active",)
    search_fields = ("name", "barcode__barcode", "address")
    autocomplete_fields = ("barcode",)
    readonly_fields = ("created_at", "updated_at")
    list_per_page = 30


@admin.register(UserWarehouseAccess)
class UserWarehouseAccessAdmin(ActiveBadgeAdminMixin, admin.ModelAdmin):
    list_per_page = 30
    list_select_related = ("user", "warehouse", "created_by")
    list_display = ("user", "warehouse", "can_delegate", "active_badge", "created_by", "updated_at")
    list_filter = ("can_delegate", "is_active", "warehouse")
    search_fields = (
        "user__username",
        "user__first_name",
        "user__last_name",
        "warehouse__name",
        "created_by__username",
    )
    autocomplete_fields = ("user", "warehouse", "created_by")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Location)
class LocationAdmin(ActiveBadgeAdminMixin, IncludeCurrentRelationsAdminMixin, admin.ModelAdmin):
    actions = [make_active, make_inactive]
    form = LocationForm
    list_select_related = ("warehouse", "barcode")
    list_display = ("name", "warehouse", "location_type", "barcode", "active_badge")
    list_filter = ("warehouse", "location_type", "is_active")
    search_fields = ("name", "warehouse__name", "barcode__barcode")
    autocomplete_fields = ("barcode",)
    readonly_fields = ("created_at", "updated_at")
    list_per_page = 30


@admin.register(InventoryCount)
class InventoryCountAdmin(admin.ModelAdmin):
    list_per_page = 30
    list_select_related = ("warehouse", "location", "created_by")
    list_display = ("number", "warehouse", "location", "status", "started_at", "completed_at", "created_by")
    list_filter = ("status", "warehouse", "started_at")
    search_fields = ("number", "warehouse__name", "location__name", "comment")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-created_at",)


@admin.register(InventoryCountLine)
class InventoryCountLineAdmin(admin.ModelAdmin):
    list_per_page = 30
    list_select_related = ("inventory_count", "item", "location")
    list_display = ("inventory_count", "item", "location", "expected_qty", "actual_qty", "difference_qty")
    list_filter = ("inventory_count__status", "location__warehouse")
    search_fields = ("inventory_count__number", "item__name", "item__internal_code", "location__name", "barcode")
    ordering = ("-id",)


@admin.register(StockBalance)
class StockBalanceAdmin(ActiveBadgeAdminMixin, IncludeCurrentRelationsAdminMixin, admin.ModelAdmin):
    actions = [make_active, make_inactive]
    form = StockBalanceAdminForm
    list_per_page = 30
    list_select_related = ("item", "warehouse", "location")
    list_display = ("item", "warehouse", "location", "qty", "active_badge")
    list_filter = ("warehouse", "location", "is_active")
    search_fields = ("item__name", "item__internal_code", "item__barcode__barcode")
    ordering = ("item__name",)


@admin.register(StockMovement)
class StockMovementAdmin(ActiveBadgeAdminMixin, IncludeCurrentRelationsAdminMixin, admin.ModelAdmin):
    actions = [make_active, make_inactive]
    form = StockMovementAdminForm
    list_per_page = 30
    list_select_related = ("item", "source_warehouse", "destination_warehouse", "source_location", "destination_location", "recipient", "performed_by")
    list_display = (
        "id",
        "movement_type_badge",
        "item",
        "qty",
        "source_warehouse",
        "source_location",
        "destination_warehouse",
        "destination_location",
        "recipient",
        "performed_by",
        "department",
        "occurred_at",
        "created_at",
        "active_badge",
    )
    list_filter = ("movement_type", "source_warehouse", "destination_warehouse", "source_location", "destination_location", "performed_by", "occurred_at", "is_active")
    search_fields = (
        "item__name",
        "item__internal_code",
        "source_location__name",
        "destination_location__name",
        "item__barcode__barcode",
        "recipient__name",
        "department",
        "document_number",
        "comment",
        "performed_by__username",
        "performed_by__first_name",
        "performed_by__last_name",
    )
    date_hierarchy = "occurred_at"
    ordering = ("-occurred_at",)
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("Операція", {"fields": ("movement_type", "occurred_at", "is_active")}),
        ("Товар і кількість", {"fields": ("item", "qty", "unit")}),
        ("Склади і локації", {"fields": ("source_warehouse", "source_location", "destination_warehouse", "destination_location")}),
        ("Отримувач / місце використання", {"fields": ("recipient", "usage_place", "issue_reason", "department")}),
        ("Авторство", {"fields": ("performed_by", "created_by", "updated_by")}),
        ("Службове", {"fields": ("document_number", "inventory_count", "comment", "created_at", "updated_at")}),
    )

    @admin.display(description="Тип руху", ordering="movement_type")
    def movement_type_badge(self, obj):
        labels = {
            "in": "Надходження",
            "out": "Видача",
            "return": "Повернення",
            "transfer": "Переміщення",
            "writeoff": "Списання",
        }
        label = labels.get(obj.movement_type, obj.movement_type)
        return format_html('<span class="status-badge status-badge--movement">{}</span>', label)


@admin.register(Printer)
class PrinterAdmin(ActiveBadgeAdminMixin, admin.ModelAdmin):
    actions = [make_active, make_inactive]
    form = PrinterForm
    list_display = ("name", "system_name", "default_badge", "active_badge")
    list_filter = ("is_default", "is_active")
    search_fields = ("name", "system_name")
    readonly_fields = ("created_at", "updated_at")
    list_per_page = 30
    fieldsets = (
        ("Основне", {"fields": ("name", "system_name", "is_default", "is_active")}),
        ("Опис", {"fields": ("description",)}),
        ("Службове", {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description="Default", ordering="is_default")
    def default_badge(self, obj):
        if obj.is_default:
            return format_html('<span class="status-badge status-badge--default">За замовчуванням</span>')
        return "—"


@admin.register(LabelTemplate)
class LabelTemplateAdmin(ActiveBadgeAdminMixin, admin.ModelAdmin):
    actions = [make_active, make_inactive]
    form = LabelTemplateForm
    list_display = ("name", "width_mm", "height_mm", "barcode_type", "barcode_height_mm", "barcode_bar_width_mm", "is_default", "active_badge")
    list_filter = ("is_default", "is_active", "barcode_type")
    search_fields = ("name",)
    readonly_fields = ("created_at", "updated_at")
    list_per_page = 30
    fieldsets = (
        ("Основне", {"fields": ("name", "width_mm", "height_mm", "is_default", "is_active")}),
        ("Макет", {"fields": (("margin_top_mm", "margin_right_mm"), ("margin_bottom_mm", "margin_left_mm"), ("item_name_font_size", "internal_code_font_size", "barcode_text_font_size"), ("barcode_height_mm", "barcode_bar_width_mm"))}),
        ("Вміст", {"fields": ("show_item_name", "show_internal_code", "show_barcode_text", "barcode_type")}),
        ("Службове", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(PrintJob)
class PrintJobAdmin(admin.ModelAdmin):
    list_per_page = 30
    list_select_related = ("item", "printer", "label_template", "user")
    list_display = ("item", "printer", "copies", "status_badge", "created_at", "error_message")
    list_filter = ("status", "printer", "created_at")
    search_fields = ("item__name", "barcode", "printer__name", "error_message")
    readonly_fields = ("barcode", "label_template", "user", "created_at", "printed_at", "error_message")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    @admin.display(description="Статус", ordering="status")
    def status_badge(self, obj):
        styles = {
            "printed": ("printed", "Надруковано"),
            "failed": ("failed", "Помилка"),
            "pending": ("pending", "Очікує"),
        }
        css, label = styles.get(obj.status, ("pending", obj.status))
        return format_html('<span class="status-badge status-badge--{}">{}</span>', css, label)


@admin.register(SystemSettings)
class SystemSettingsAdmin(admin.ModelAdmin):
    list_display = ("id", "use_locations", "created_at", "updated_at")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("Операційний режим", {"fields": ("use_locations",)}),
        ("Службове", {"fields": ("created_at", "updated_at")}),
    )

    def has_add_permission(self, request):
        return not SystemSettings.objects.exists()


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_per_page = 50
    list_select_related = ("actor",)
    list_display = ("created_at", "actor", "action", "object_type", "object_id", "ip_address")
    list_filter = ("action", "object_type", "created_at")
    search_fields = ("actor__username", "actor__first_name", "actor__last_name", "action", "object_type", "object_id", "object_repr", "ip_address")
    readonly_fields = ("actor", "action", "object_type", "object_id", "object_repr", "changes", "ip_address", "user_agent", "created_at")
    ordering = ("-created_at", "-id")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
