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
    PurchaseRequest,
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
    can_manage_directories,
    can_access_warehouse,
    can_create_purchase_requests,
    can_view_analytics,
    can_view_purchase_requests,
    can_view_warehouse_data,
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
from ..services.warehouse_access import (
    get_accessible_warehouses,
    restrict_stock_movement_queryset_for_user,
)
from ..services.stock import (
    InsufficientStockError,
    SameLocationTransferError,
    StockServiceError,
    create_initial_balance,
    issue_stock,
    receive_stock,
    transfer_stock,
)



class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "core/dashboard.html"
    storekeeper_template_name = "core/storekeeper_workplace.html"

    def is_storekeeper_workplace(self):
        user = self.request.user
        is_storekeeper = user.groups.filter(name="Комірник").exists()
        is_warehouse_admin = user.groups.filter(name="Адміністратор складу").exists()
        return is_storekeeper and not user.is_superuser and not is_warehouse_admin

    def get_template_names(self):
        if self.is_storekeeper_workplace():
            return [self.storekeeper_template_name]
        return [self.template_name]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        accessible_warehouses = get_accessible_warehouses(self.request.user)
        context["is_storekeeper_workplace"] = self.is_storekeeper_workplace()
        context["hide_sidebar"] = not context["is_storekeeper_workplace"]
        context["show_sidebar"] = False
        context["accessible_warehouses"] = accessible_warehouses
        context["has_warehouse_access"] = can_view_warehouse_data(self.request.user)
        context["no_warehouse_access_message"] = _(
            "У вас немає доступу до жодного складу. Зверніться до адміністратора."
        )
        context["can_edit_stock"] = self.request.user.is_superuser or user_in_groups(
            self.request.user, STOCK_EDIT_GROUPS
        )
        context["can_view_stock"] = self.request.user.is_superuser or user_in_groups(
            self.request.user, STOCK_VIEW_GROUPS
        )
        context["can_edit_directories"] = can_manage_directories(self.request.user)
        context["can_view_analytics"] = can_view_analytics(self.request.user)
        context["can_view_purchase_requests"] = can_view_purchase_requests(
            self.request.user
        )
        return context


class DashboardPrototypeView(LoginRequiredMixin, TemplateView):
    template_name = "core/dashboard_prototype.html"

    def get_stock_balance_queryset(self):
        accessible_warehouses = get_accessible_warehouses(self.request.user)
        return StockBalance.objects.select_related("item", "warehouse").filter(
            is_active=True,
            warehouse__in=accessible_warehouses,
        )

    def get_stock_movement_queryset(self):
        queryset = StockMovement.objects.select_related(
            "item",
            "source_warehouse",
            "destination_warehouse",
            "source_location",
            "destination_location",
            "recipient",
            "performed_by",
        ).filter(is_active=True, is_cancelled=False, reversal_of__isnull=True)
        return restrict_stock_movement_queryset_for_user(self.request.user, queryset)

    def get_purchase_request_queryset(self):
        if not can_view_purchase_requests(self.request.user):
            return PurchaseRequest.objects.none()
        return PurchaseRequest.objects.select_related("requested_by").filter(
            archived_at__isnull=True
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        balances = self.get_stock_balance_queryset()
        movements = self.get_stock_movement_queryset()
        purchase_requests = self.get_purchase_request_queryset()
        pending_requests = purchase_requests.filter(
            status=PurchaseRequest.Status.PENDING_APPROVAL
        )
        zero_balances = balances.filter(qty=0)

        context.update(
            {
                "hide_sidebar": True,
                "show_sidebar": False,
                "can_edit_stock": self.request.user.is_superuser
                or user_in_groups(self.request.user, STOCK_EDIT_GROUPS),
                "can_access_warehouse": can_access_warehouse(self.request.user),
                "can_create_purchase_requests": can_create_purchase_requests(
                    self.request.user
                ),
                "can_view_purchase_requests": can_view_purchase_requests(
                    self.request.user
                ),
                "can_view_analytics": can_view_analytics(self.request.user),
                "can_manage_directories": can_manage_directories(self.request.user),
                "kpi_cards": [
                    {
                        "label": _("Остатки позицій"),
                        "value": balances.filter(qty__gt=0).count(),
                        "hint": _("Активні позиції з фактичним залишком"),
                    },
                    {
                        "label": _("Операції сьогодні"),
                        "value": movements.filter(occurred_at__date=today).count(),
                        "hint": _("Рухи товарів за поточний день"),
                    },
                    {
                        "label": _("Нові заявки"),
                        "value": purchase_requests.count(),
                        "hint": _("Активні заявки на закупівлю"),
                    },
                    {
                        "label": _("Очікують погодження"),
                        "value": pending_requests.count(),
                        "hint": _("Заявки, які потребують рішення"),
                    },
                    {
                        "label": _("Нульові залишки"),
                        "value": zero_balances.count(),
                        "hint": _("Позиції без доступної кількості"),
                    },
                ],
                "recent_movements": movements.order_by("-occurred_at", "-id")[:6],
                "attention_requests": pending_requests.order_by("-created_at", "-id")[
                    :6
                ],
                "zero_balances": zero_balances.order_by("item__name")[:6],
            }
        )
        return context
