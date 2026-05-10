import csv
import json

from django.contrib import messages
from django.contrib.auth import get_user_model
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
    ManagementUserCreateForm,
    ManagementUserPasswordForm,
    ManagementUserUpdateForm,
    PrintLabelForm,
    PrinterForm,
    RecipientForm,
    StockBalanceFilterForm,
    StockIssueForm,
    StockMovementFilterForm,
    StockReceiveForm,
    StockTransferForm,
    SystemSettingsForm,
    warehouse_role_queryset,
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
    SystemSettings,
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



class PlaceholderPageView(LoginRequiredMixin, TemplateView):
    template_name = "core/placeholder.html"
    title = ""
    description = ""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = self.title
        context["description"] = self.description
        return context


class ManagementDashboardView(LoginRequiredMixin, GroupRequiredMixin, TemplateView):
    group_names = MANAGEMENT_GROUPS
    template_name = "core/management/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "can_manage_users": user_in_groups(
                    self.request.user, USER_MANAGEMENT_GROUPS
                ),
                "can_manage_directories": user_in_groups(
                    self.request.user, DIRECTORY_EDIT_GROUPS
                ),
                "can_view_analytics": user_in_groups(
                    self.request.user, ANALYTICS_GROUPS
                ),
                "show_technical_admin": self.request.user.is_superuser,
                "counts": {
                    "items": Item.objects.count(),
                    "warehouses": Warehouse.objects.count(),
                    "locations": Location.objects.count(),
                    "users": get_user_model().objects.count(),
                },
            }
        )
        return context


class ManagementDirectoriesView(LoginRequiredMixin, GroupRequiredMixin, TemplateView):
    group_names = DIRECTORY_EDIT_GROUPS
    template_name = "core/management/directories.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["directories"] = [
            {
                "title": _("Номенклатура"),
                "count": Item.objects.count(),
                "url": reverse("item_list"),
            },
            {
                "title": _("Категорії"),
                "count": Category.objects.count(),
                "url": reverse("category_list"),
            },
            {
                "title": _("Одиниці виміру"),
                "count": Unit.objects.count(),
                "url": reverse("unit_list"),
            },
            {
                "title": _("Склади"),
                "count": Warehouse.objects.count(),
                "url": reverse("warehouse_list"),
            },
            {
                "title": _("Локації"),
                "count": Location.objects.count(),
                "url": reverse("location_list"),
            },
            {
                "title": _("Отримувачі"),
                "count": Recipient.objects.count(),
                "url": reverse("recipient_list"),
            },
        ]
        return context


class ManagementUsersView(LoginRequiredMixin, GroupRequiredMixin, TemplateView):
    group_names = USER_MANAGEMENT_GROUPS
    template_name = "core/management/users.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["users"] = (
            get_user_model().objects.prefetch_related("groups").order_by("username")
        )
        context["groups"] = warehouse_role_queryset()
        return context



class ManagementUserCreateView(LoginRequiredMixin, GroupRequiredMixin, CreateView):
    group_names = USER_MANAGEMENT_GROUPS
    model = get_user_model()
    form_class = ManagementUserCreateForm
    template_name = "core/management/user_form.html"
    success_url = reverse_lazy("management_users")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request_user"] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = _("Створити користувача")
        context["submit_label"] = _("Створити")
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, _("Користувача створено."))
        return response


class ManagementUserUpdateView(LoginRequiredMixin, GroupRequiredMixin, UpdateView):
    group_names = USER_MANAGEMENT_GROUPS
    model = get_user_model()
    form_class = ManagementUserUpdateForm
    template_name = "core/management/user_form.html"
    success_url = reverse_lazy("management_users")

    def get_queryset(self):
        return get_user_model().objects.prefetch_related("groups")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request_user"] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = _("Редагувати користувача")
        context["submit_label"] = _("Зберегти")
        context["is_superuser_target"] = self.object.is_superuser
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, _("Користувача оновлено."))
        return response


class ManagementUserPasswordView(LoginRequiredMixin, GroupRequiredMixin, FormView):
    group_names = USER_MANAGEMENT_GROUPS
    form_class = ManagementUserPasswordForm
    template_name = "core/management/user_password_form.html"
    success_url = reverse_lazy("management_users")

    def dispatch(self, request, *args, **kwargs):
        self.target_user = get_object_or_404(get_user_model(), pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.target_user
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["target_user"] = self.target_user
        return context

    def form_valid(self, form):
        form.save()
        messages.success(self.request, _("Пароль змінено."))
        return super().form_valid(form)


class ManagementSettingsView(LoginRequiredMixin, GroupRequiredMixin, FormView):
    group_names = USER_MANAGEMENT_GROUPS
    template_name = "core/management/settings.html"
    form_class = SystemSettingsForm
    success_url = reverse_lazy("management_settings")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = SystemSettings.get_solo()
        return kwargs

    def form_valid(self, form):
        form.save()
        messages.success(self.request, _("Налаштування збережено."))
        return super().form_valid(form)


HELP_SECTIONS = [
    {
        "title": _("Як почати склад з нуля"),
        "filename": "START_WAREHOUSE_FROM_ZERO.md",
        "admin_only": True,
    },
    {"title": _("Інструкція користувача"), "filename": "USER_GUIDE.md", "admin_only": False},
    {"title": _("Інструкція адміністратора"), "filename": "ADMIN_GUIDE.md", "admin_only": True},
    {"title": _("Типові помилки"), "filename": "ADMIN_GUIDE.md", "anchor": "Типові помилки", "admin_only": True},
    {"title": _("Backup і відновлення"), "filename": "BACKUP_AND_RESTORE.md", "admin_only": True},
    {"title": _("Принтери і друк етикеток"), "filename": "USER_GUIDE.md", "anchor": "Друк етикеток", "admin_only": True},
    {"title": _("Штрихкоди"), "filename": "USER_GUIDE.md", "anchor": "Штрихкоди", "admin_only": False},
    {"title": _("Прихід товару"), "filename": "USER_GUIDE.md", "anchor": "Прихід товару", "admin_only": False},
    {"title": _("Початковий залишок"), "filename": "USER_GUIDE.md", "anchor": "Початковий залишок", "admin_only": False},
    {"title": _("Рухи товарів"), "filename": "USER_GUIDE.md", "anchor": "Рухи товарів", "admin_only": False},
]


def render_markdown_document(filename):
    document_path = settings.BASE_DIR / "docs" / filename
    if not document_path.exists():
        return format_html("<p class='text-muted'>{}</p>", _("Документ ще не додано."))
    text = document_path.read_text(encoding="utf-8")
    return mark_safe(linebreaks(urlize(text)))


class HelpView(LoginRequiredMixin, TemplateView):
    template_name = "core/management/help.html"
    management_mode = False

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        sections = HELP_SECTIONS if self.management_mode else [HELP_SECTIONS[1]]
        context.update(
            {
                "management_mode": self.management_mode,
                "help_sections": [
                    {
                        **section,
                        "content": render_markdown_document(section["filename"]),
                    }
                    for section in sections
                ],
            }
        )
        return context


class ManagementHelpView(GroupRequiredMixin, HelpView):
    group_names = MANAGEMENT_GROUPS
    management_mode = True
