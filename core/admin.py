from django.contrib import admin

from .models import (
    BarcodeRegistry,
    BarcodeSequence,
    Category,
    Item,
    Location,
    Recipient,
    StockBalance,
    StockMovement,
    Unit,
    Warehouse,
)


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ("name", "symbol", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "symbol")


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
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
class ItemAdmin(admin.ModelAdmin):
    list_display = ("name", "internal_code", "category", "unit", "barcode", "is_active")
    list_filter = ("category", "unit", "is_active")
    search_fields = ("name", "internal_code", "barcode__barcode")
    autocomplete_fields = ("category", "unit", "barcode")


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ("name", "barcode", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "barcode__barcode", "address")
    autocomplete_fields = ("barcode",)


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ("name", "warehouse", "location_type", "barcode", "is_active")
    list_filter = ("warehouse", "location_type", "is_active")
    search_fields = ("name", "warehouse__name", "barcode__barcode")
    autocomplete_fields = ("warehouse", "barcode")


@admin.register(StockBalance)
class StockBalanceAdmin(admin.ModelAdmin):
    list_display = ("item", "location", "qty", "is_active")
    list_filter = ("location__warehouse", "is_active")
    search_fields = ("item__name", "item__internal_code", "location__name")
    autocomplete_fields = ("item", "location")


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
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
    autocomplete_fields = ("item", "source_location", "destination_location", "recipient")
    date_hierarchy = "occurred_at"
