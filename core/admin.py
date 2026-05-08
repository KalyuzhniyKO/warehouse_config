from django.contrib import admin

from .forms import active_records_queryset
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


class ActiveRelatedAdminMixin:
    """Prevent archived records from being offered as related choices."""

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if hasattr(db_field.remote_field.model, "is_active"):
            kwargs["queryset"] = active_records_queryset(db_field.remote_field.model.objects.all())
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if hasattr(db_field.remote_field.model, "is_active"):
            kwargs["queryset"] = active_records_queryset(db_field.remote_field.model.objects.all())
        return super().formfield_for_manytomany(db_field, request, **kwargs)

    def get_search_results(self, request, queryset, search_term):
        queryset, use_distinct = super().get_search_results(request, queryset, search_term)
        if {"app_label", "model_name", "field_name"}.issubset(request.GET) and hasattr(self.model, "is_active"):
            queryset = active_records_queryset(queryset)
        return queryset, use_distinct


@admin.register(Unit)
class UnitAdmin(ActiveRelatedAdminMixin, admin.ModelAdmin):
    list_display = ("name", "symbol", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "symbol")


@admin.register(Category)
class CategoryAdmin(ActiveRelatedAdminMixin, admin.ModelAdmin):
    list_display = ("name", "parent", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "parent__name")


@admin.register(Recipient)
class RecipientAdmin(ActiveRelatedAdminMixin, admin.ModelAdmin):
    list_display = ("name", "contact_name", "phone", "email", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "contact_name", "phone", "email")


@admin.register(BarcodeRegistry)
class BarcodeRegistryAdmin(ActiveRelatedAdminMixin, admin.ModelAdmin):
    list_display = ("barcode", "prefix", "is_active")
    list_filter = ("prefix", "is_active")
    search_fields = ("barcode", "description")


@admin.register(BarcodeSequence)
class BarcodeSequenceAdmin(ActiveRelatedAdminMixin, admin.ModelAdmin):
    list_display = ("prefix", "next_number", "padding", "is_active")
    list_filter = ("prefix", "is_active")
    search_fields = ("prefix",)


@admin.register(Item)
class ItemAdmin(ActiveRelatedAdminMixin, admin.ModelAdmin):
    list_display = ("name", "internal_code", "category", "unit", "barcode", "is_active")
    list_filter = ("category", "unit", "is_active")
    search_fields = ("name", "internal_code", "barcode__barcode")
    autocomplete_fields = ("category", "unit", "barcode")


@admin.register(Warehouse)
class WarehouseAdmin(ActiveRelatedAdminMixin, admin.ModelAdmin):
    list_display = ("name", "barcode", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "barcode__barcode", "address")
    autocomplete_fields = ("barcode",)


@admin.register(Location)
class LocationAdmin(ActiveRelatedAdminMixin, admin.ModelAdmin):
    list_display = ("name", "warehouse", "location_type", "barcode", "is_active")
    list_filter = ("warehouse", "location_type", "is_active")
    search_fields = ("name", "warehouse__name", "barcode__barcode")
    autocomplete_fields = ("warehouse", "barcode")


@admin.register(StockBalance)
class StockBalanceAdmin(ActiveRelatedAdminMixin, admin.ModelAdmin):
    list_display = ("item", "location", "qty", "is_active")
    list_filter = ("location__warehouse", "is_active")
    search_fields = ("item__name", "item__internal_code", "location__name")
    autocomplete_fields = ("item", "location")


@admin.register(StockMovement)
class StockMovementAdmin(ActiveRelatedAdminMixin, admin.ModelAdmin):
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
