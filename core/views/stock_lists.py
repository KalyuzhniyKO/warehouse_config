from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.views.generic import ListView

from ..forms import StockBalanceFilterForm
from ..models import StockBalance
from ..permissions import STOCK_VIEW_GROUPS, GroupRequiredMixin
from ..services.warehouse_access import get_accessible_warehouses


class StockBalanceListView(LoginRequiredMixin, GroupRequiredMixin, ListView):
    group_names = STOCK_VIEW_GROUPS
    model = StockBalance
    template_name = "core/stockbalance_list.html"
    context_object_name = "balances"
    paginate_by = 50

    def get_filter_form(self):
        return StockBalanceFilterForm(self.request.GET or None, request_user=self.request.user)

    def get_queryset(self):
        queryset = (
            StockBalance.objects.select_related(
                "item",
                "item__unit",
                "item__barcode",
                "location",
                "warehouse",
            )
            .filter(
                is_active=True,
                item__is_active=True,
                qty__gt=0,
                warehouse__is_active=True,
                warehouse__in=get_accessible_warehouses(self.request.user),
            )
            .order_by("item__name", "warehouse__name", "location__name")
        )
        form = self.get_filter_form()
        if not form.is_valid():
            return queryset

        warehouse = form.cleaned_data.get("warehouse")
        location = form.cleaned_data.get("location")
        item = form.cleaned_data.get("item")
        query = form.cleaned_data.get("q")

        if warehouse:
            queryset = queryset.filter(warehouse=warehouse)
        if location:
            queryset = queryset.filter(location=location)
        if item:
            queryset = queryset.filter(item=item)
        if query:
            queryset = queryset.filter(
                Q(item__name__icontains=query)
                | Q(item__internal_code__icontains=query)
                | Q(item__barcode__barcode__icontains=query)
            )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.get_filter_form()
        context["used_remembered_filters"] = getattr(self, "used_remembered_filters", False)
        return context
