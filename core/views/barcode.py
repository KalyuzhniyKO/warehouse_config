import csv
import json

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.forms.models import model_to_dict
from django.db.models import Count, Q, Sum
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.html import format_html, linebreaks, urlize
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, FormView, ListView, TemplateView, UpdateView, View

from ..forms import (
    AnalyticsFilterForm,
    CategoryForm,
    ItemForm,
    InitialBalanceForm,
    InventoryCountCreateForm,
    InventoryCountLineForm,
    LabelTemplateForm,
    LocationForm,
    PrintLabelForm,
    PrinterForm,
    RecipientForm,
    StockBalanceFilterForm,
    StockIssueForm,
    StockMovementFilterForm,
    StockReceiveForm,
    StockTransferForm,
    UnitForm,
    WarehouseForm,
)
from ..models import (
    Category,
    InventoryCount,
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
from ..permissions import (
    ANALYTICS_GROUPS,
    MANAGEMENT_GROUPS,
    DIRECTORY_EDIT_GROUPS,
    PRINT_GROUPS,
    SETTINGS_GROUPS,
    STOCK_EDIT_GROUPS,
    STOCK_VIEW_GROUPS,
    USER_MANAGEMENT_GROUPS,
    GroupRequiredMixin,
    user_in_groups,
)
from ..services import analytics as analytics_service
from ..services.inventory import (
    InventoryServiceError,
    complete_inventory_count,
    create_inventory_count,
    update_inventory_line_actual_qty,
)
from ..services.labels import download_item_label_pdf, get_default_label_template, print_item_label
from ..services.stock import (
    InsufficientStockError,
    SameLocationTransferError,
    StockServiceError,
    create_initial_balance,
    issue_stock,
    receive_stock,
    transfer_stock,
)



@login_required
def barcode_lookup(request):
    barcode = request.GET.get("barcode", "").strip()
    not_found = {"found": False, "message": str(_("Штрихкод не знайдено."))}
    if not barcode:
        return JsonResponse(not_found)

    item = (
        Item.objects.select_related("barcode")
        .filter(is_active=True, barcode__barcode=barcode)
        .first()
    )
    if item:
        return JsonResponse(
            {
                "found": True,
                "type": "item",
                "id": item.pk,
                "name": item.name,
                "internal_code": item.internal_code or "",
                "barcode": item.barcode.barcode,
            }
        )

    warehouse = (
        Warehouse.objects.select_related("barcode")
        .filter(is_active=True, barcode__barcode=barcode)
        .first()
    )
    if warehouse:
        return JsonResponse(
            {
                "found": True,
                "type": "warehouse",
                "id": warehouse.pk,
                "name": warehouse.name,
                "barcode": warehouse.barcode.barcode,
            }
        )

    location = (
        Location.objects.select_related("barcode", "warehouse")
        .filter(is_active=True, warehouse__is_active=True, barcode__barcode=barcode)
        .first()
    )
    if location:
        return JsonResponse(
            {
                "found": True,
                "type": "location",
                "id": location.pk,
                "name": location.name,
                "warehouse_id": location.warehouse_id,
                "warehouse_name": location.warehouse.name,
                "barcode": location.barcode.barcode,
            }
        )

    return JsonResponse(not_found)
