from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, FormView, TemplateView, UpdateView

from core.forms.management_users import (
    ManagementUserCreateForm,
    ManagementUserPasswordForm,
    ManagementUserUpdateForm,
    warehouse_role_queryset,
)
from core.models import UserWarehouseAccess
from core.permissions import (
    ROLE_DESCRIPTIONS,
    ROLE_DISPLAY_NAMES,
    USER_MANAGEMENT_GROUPS,
    GroupRequiredMixin,
)


class ManagementUsersView(LoginRequiredMixin, GroupRequiredMixin, TemplateView):
    group_names = USER_MANAGEMENT_GROUPS
    template_name = "core/management/users.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        role_names = tuple(warehouse_role_queryset().values_list("name", flat=True))
        context["users"] = (
            get_user_model()
            .objects.filter(is_superuser=False)
            .filter(Q(groups__name__in=role_names) | Q(groups__isnull=True))
            .distinct()
            .prefetch_related(
                "groups",
                Prefetch(
                    "warehouse_accesses",
                    queryset=UserWarehouseAccess.objects.filter(
                        is_active=True
                    ).select_related("warehouse"),
                    to_attr="active_warehouse_accesses",
                ),
            )
            .order_by("username")
        )
        context["groups"] = warehouse_role_queryset()
        context["role_details"] = [
            {
                "group": group,
                "name": ROLE_DISPLAY_NAMES.get(group.name, group.name),
                "description": ROLE_DESCRIPTIONS.get(group.name, ""),
            }
            for group in context["groups"]
        ]
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
        queryset = get_user_model().objects.prefetch_related("groups")
        if not self.request.user.is_superuser:
            queryset = queryset.filter(is_superuser=False)
        return queryset

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
        queryset = get_user_model().objects.all()
        if not request.user.is_superuser:
            queryset = queryset.filter(is_superuser=False)
        self.target_user = get_object_or_404(queryset, pk=kwargs["pk"])
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
