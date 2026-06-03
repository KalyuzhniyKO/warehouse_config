import secrets

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import FormView

from ..forms import (
    InitialBalanceForm,
    StockIssueForm,
    StockReceiveForm,
    StockReturnForm,
    StockTransferForm,
    StockWriteOffForm,
)
from ..models import StockBalance, StockMovement
from ..permissions import STOCK_EDIT_GROUPS, GroupRequiredMixin
from ..services.items import find_item_by_barcode
from ..services.stock import (
    InsufficientStockError,
    SameLocationTransferError,
    StockServiceError,
    create_initial_balance,
    find_best_stock_balance_for_issue,
    find_default_stock_return_location,
    issue_stock,
    receive_stock,
    return_stock,
    transfer_stock,
    writeoff_stock,
)


SELF_SERVICE_OPERATION_TOKEN_FIELD = "operation_token"
SELF_SERVICE_OPERATION_TOKENS_SESSION_KEY = "self_service_operation_tokens"
SELF_SERVICE_OPERATION_TOKEN_LIMIT = 20


class SelfServiceOperationTokenMixin:
    duplicate_submission_message = _("Операція вже була збережена.")
    operation_token_field = SELF_SERVICE_OPERATION_TOKEN_FIELD
    operation_tokens_session_key = SELF_SERVICE_OPERATION_TOKENS_SESSION_KEY
    operation_token_limit = SELF_SERVICE_OPERATION_TOKEN_LIMIT
    result_url_name = None

    def get_operation_tokens(self):
        return dict(self.request.session.get(self.operation_tokens_session_key, {}))

    def save_operation_tokens(self, tokens):
        while len(tokens) > self.operation_token_limit:
            tokens.pop(next(iter(tokens)))
        self.request.session[self.operation_tokens_session_key] = tokens
        self.request.session.modified = True

    def create_operation_token(self):
        tokens = self.get_operation_tokens()
        token = secrets.token_urlsafe(32)
        tokens[token] = {"status": "pending"}
        self.save_operation_tokens(tokens)
        return token

    def get_posted_operation_token(self):
        return self.request.POST.get(self.operation_token_field, "").strip()

    def mark_operation_token_used(self, movement):
        token = self.get_posted_operation_token()
        if not token:
            return
        tokens = self.get_operation_tokens()
        tokens[token] = {"status": "used", "movement_pk": movement.pk}
        self.save_operation_tokens(tokens)

    def redirect_if_operation_token_used(self):
        token = self.get_posted_operation_token()
        if not token or self.result_url_name is None:
            return None
        token_data = self.get_operation_tokens().get(token) or {}
        movement_pk = token_data.get("movement_pk")
        if token_data.get("status") == "used" and movement_pk:
            messages.info(self.request, self.duplicate_submission_message)
            return redirect(self.result_url_name, pk=movement_pk)
        return None

    def get_operation_token_for_context(self, should_create):
        if self.request.method == "POST":
            return self.get_posted_operation_token()
        if should_create:
            return self.create_operation_token()
        return ""


def is_self_service_storekeeper(user):
    is_storekeeper = user.groups.filter(name="Комірник").exists()
    is_warehouse_admin = user.groups.filter(name="Адміністратор складу").exists()
    return is_storekeeper and not user.is_superuser and not is_warehouse_admin


class SelfServiceShellContextMixin:
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["is_storekeeper_workplace"] = is_self_service_storekeeper(self.request.user)
        return context


class RequestUserFormKwargsMixin:
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request_user"] = self.request.user
        return kwargs


def stock_operation_barcode_context(item, user=None):
    if item is None:
        return None
    queryset = StockBalance.objects.filter(item=item, is_active=True)
    if user is not None and not user.is_superuser:
        from ..services.warehouse_access import get_accessible_warehouses

        queryset = queryset.filter(warehouse__in=get_accessible_warehouses(user))
    available_qty = queryset.aggregate(total=Sum("qty"))["total"] or 0
    return {"item": item, "available_qty": available_qty}


class BarcodePrefillMixin:
    barcode_param = "barcode"
    barcode_not_found_message = _("Товар за цим штрихкодом не знайдено.")

    def dispatch(self, request, *args, **kwargs):
        self.scanned_barcode = request.GET.get(self.barcode_param, "").strip()
        self.scanned_item = None
        if request.method == "GET" and self.scanned_barcode:
            self.scanned_item = find_item_by_barcode(self.scanned_barcode)
            if self.scanned_item is None:
                messages.warning(request, self.barcode_not_found_message)
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        if self.scanned_item is not None:
            initial["item"] = self.scanned_item
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["barcode_query"] = self.scanned_barcode
        context["scanned_item"] = self.scanned_item
        context["scanned_item_context"] = stock_operation_barcode_context(
            self.scanned_item, self.request.user
        )
        return context


class StockReceiveView(
    LoginRequiredMixin,
    RequestUserFormKwargsMixin,
    SelfServiceShellContextMixin,
    GroupRequiredMixin,
    BarcodePrefillMixin,
    SelfServiceOperationTokenMixin,
    FormView,
):
    group_names = STOCK_EDIT_GROUPS
    template_name = "core/stock_receive_form.html"
    form_class = StockReceiveForm
    result_url_name = "stock_receive_result"

    def get_initial(self):
        initial = super().get_initial()
        initial["occurred_at"] = timezone.localtime(timezone.now()).strftime(
            "%Y-%m-%dT%H:%M"
        )
        initial["comment"] = ""
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["can_submit_receive"] = self.scanned_item is not None
        context["operation_token"] = self.get_operation_token_for_context(
            context["can_submit_receive"]
        )
        context["operation_token_field"] = self.operation_token_field
        return context

    def form_valid(self, form):
        duplicate_redirect = self.redirect_if_operation_token_used()
        if duplicate_redirect is not None:
            return duplicate_redirect
        try:
            movement = receive_stock(
                item=form.cleaned_data["item"],
                warehouse=form.cleaned_data["warehouse"],
                location=form.cleaned_data.get("location"),
                qty=form.cleaned_data["qty"],
                comment=form.cleaned_data.get("comment", ""),
                occurred_at=form.cleaned_data.get("occurred_at"),
                performed_by=self.request.user,
                request=self.request,
            )
        except StockServiceError as exc:
            message = str(exc)
            messages.error(self.request, message)
            form.add_error(None, message)
            return self.form_invalid(form)
        self.mark_operation_token_used(movement)
        url = reverse("stock_receive_result", kwargs={"pk": movement.pk})
        return redirect(url)




class StockReturnView(
    LoginRequiredMixin,
    RequestUserFormKwargsMixin,
    SelfServiceShellContextMixin,
    GroupRequiredMixin,
    BarcodePrefillMixin,
    SelfServiceOperationTokenMixin,
    FormView,
):
    group_names = STOCK_EDIT_GROUPS
    template_name = "core/stock_return_form.html"
    form_class = StockReturnForm
    auto_selected_message = _("Дані для повернення визначено автоматично.")
    no_return_warehouse_message = _("Товар знайдено, але локацію для повернення не налаштовано.")
    result_url_name = "stock_receive_result"

    def get_return_warehouse(self):
        if not hasattr(self, "return_warehouse"):
            self.return_warehouse = find_default_stock_return_location(self.request.user)
        return self.return_warehouse

    def get_initial(self):
        initial = super().get_initial()
        initial["occurred_at"] = timezone.localtime(timezone.now()).strftime(
            "%Y-%m-%dT%H:%M"
        )
        initial["comment"] = ""
        return_warehouse = self.get_return_warehouse()
        if self.scanned_item is not None and return_warehouse is not None:
            initial["warehouse"] = return_warehouse.warehouse
            initial["location"] = return_warehouse
        return initial

    def get(self, request, *args, **kwargs):
        if self.scanned_item is not None:
            if self.get_return_warehouse() is not None:
                messages.success(request, self.auto_selected_message)
            else:
                messages.error(request, self.no_return_warehouse_message)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["return_warehouse"] = self.get_return_warehouse()
        context["can_submit_receive"] = (
            self.scanned_item is not None and self.get_return_warehouse() is not None
        )
        context["operation_token"] = self.get_operation_token_for_context(
            context["can_submit_receive"]
        )
        context["operation_token_field"] = self.operation_token_field
        return context

    def form_valid(self, form):
        duplicate_redirect = self.redirect_if_operation_token_used()
        if duplicate_redirect is not None:
            return duplicate_redirect
        try:
            movement = return_stock(
                item=form.cleaned_data["item"],
                warehouse=form.cleaned_data["warehouse"],
                location=form.cleaned_data.get("location"),
                qty=form.cleaned_data["qty"],
                recipient=form.cleaned_data["recipient"],
                department=form.cleaned_data["department"],
                comment=form.cleaned_data.get("comment", ""),
                occurred_at=form.cleaned_data.get("occurred_at"),
                performed_by=self.request.user,
                request=self.request,
            )
        except StockServiceError as exc:
            message = str(exc)
            messages.error(self.request, message)
            form.add_error(None, message)
            return self.form_invalid(form)
        self.mark_operation_token_used(movement)
        return redirect(reverse("stock_receive_result", kwargs={"pk": movement.pk}))


class StockIssueView(
    LoginRequiredMixin,
    RequestUserFormKwargsMixin,
    SelfServiceShellContextMixin,
    GroupRequiredMixin,
    BarcodePrefillMixin,
    SelfServiceOperationTokenMixin,
    FormView,
):
    group_names = STOCK_EDIT_GROUPS
    template_name = "core/stock_issue_form.html"
    form_class = StockIssueForm
    auto_selected_message = _("Дані для видачі визначено автоматично.")
    no_available_stock_message = _(
        "Товар знайдено, але доступного залишку для видачі немає."
    )
    result_url_name = "stock_issue_result"

    def get_best_stock_balance(self):
        if not hasattr(self, "best_stock_balance"):
            self.best_stock_balance = find_best_stock_balance_for_issue(
                self.scanned_item, self.request.user
            )
        return self.best_stock_balance

    def get_initial(self):
        initial = super().get_initial()
        initial["occurred_at"] = timezone.localtime(timezone.now()).strftime(
            "%Y-%m-%dT%H:%M"
        )
        initial["issue_reason"] = StockMovement.IssueReason.OTHER
        initial["document_number"] = ""
        initial["comment"] = ""
        best_balance = self.get_best_stock_balance()
        if best_balance is not None:
            initial["warehouse"] = best_balance.warehouse
            initial["location"] = best_balance.location
        return initial

    def get(self, request, *args, **kwargs):
        if self.scanned_item is not None:
            if self.get_best_stock_balance() is not None:
                messages.success(request, self.auto_selected_message)
            else:
                messages.warning(request, self.no_available_stock_message)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["best_stock_balance"] = self.get_best_stock_balance()
        context["show_issue_form"] = (
            self.request.method == "POST"
            or (
                self.scanned_item is not None
                and self.get_best_stock_balance() is not None
            )
        )
        context["operation_token"] = self.get_operation_token_for_context(
            context["show_issue_form"]
        )
        context["operation_token_field"] = self.operation_token_field
        return context

    def form_valid(self, form):
        duplicate_redirect = self.redirect_if_operation_token_used()
        if duplicate_redirect is not None:
            return duplicate_redirect
        try:
            movement = issue_stock(
                item=form.cleaned_data["item"],
                warehouse=form.cleaned_data["warehouse"],
                location=form.cleaned_data.get("location"),
                qty=form.cleaned_data["qty"],
                recipient=form.cleaned_data["recipient"],
                issue_reason=(
                    form.cleaned_data["issue_reason"] or StockMovement.IssueReason.OTHER
                ),
                department=form.cleaned_data["department"],
                document_number=form.cleaned_data["document_number"],
                comment=form.cleaned_data["comment"],
                occurred_at=form.cleaned_data["occurred_at"],
                performed_by=self.request.user,
                request=self.request,
            )
        except InsufficientStockError:
            message = _(
                "Недостатньо залишку для видачі. Перевірте залишки перед видачею."
            )
            messages.error(self.request, message)
            form.add_error(None, message)
            return self.form_invalid(form)
        except StockServiceError as exc:
            message = str(exc)
            messages.error(self.request, message)
            form.add_error(None, message)
            return self.form_invalid(form)
        self.mark_operation_token_used(movement)
        return redirect("stock_issue_result", pk=movement.pk)


def _format_writeoff_comment(*, reason, document_number, comment):
    lines = [_("Причина списання: %(reason)s") % {"reason": reason}]
    if document_number:
        lines.append(_("Номер документа: %(document_number)s") % {"document_number": document_number})
    if comment:
        lines.append(_("Коментар: %(comment)s") % {"comment": comment})
    return "\n".join(lines)


class StockWriteOffView(LoginRequiredMixin, RequestUserFormKwargsMixin, GroupRequiredMixin, FormView):
    group_names = STOCK_EDIT_GROUPS
    template_name = "core/stock_writeoff_form.html"
    form_class = StockWriteOffForm

    def get_initial(self):
        initial = super().get_initial()
        initial["occurred_at"] = timezone.localtime(timezone.now()).strftime(
            "%Y-%m-%dT%H:%M"
        )
        return initial

    def form_valid(self, form):
        reason = dict(form.fields["writeoff_reason"].choices).get(
            form.cleaned_data["writeoff_reason"], form.cleaned_data["writeoff_reason"]
        )
        comment = _format_writeoff_comment(
            reason=reason,
            document_number=form.cleaned_data["document_number"],
            comment=form.cleaned_data["comment"],
        )
        try:
            movement = writeoff_stock(
                item=form.cleaned_data["item"],
                warehouse=form.cleaned_data["warehouse"],
                location=form.cleaned_data.get("location"),
                qty=form.cleaned_data["qty"],
                comment=comment,
                occurred_at=form.cleaned_data["occurred_at"],
                performed_by=self.request.user,
                request=self.request,
            )
        except InsufficientStockError:
            message = _(
                "Недостатньо залишку для списання. Перевірте залишки перед списанням."
            )
            messages.error(self.request, message)
            form.add_error(None, message)
            return self.form_invalid(form)
        except StockServiceError as exc:
            message = str(exc)
            messages.error(self.request, message)
            form.add_error(None, message)
            return self.form_invalid(form)
        return redirect("stock_writeoff_result", pk=movement.pk)


class StockTransferView(LoginRequiredMixin, RequestUserFormKwargsMixin, GroupRequiredMixin, FormView):
    group_names = STOCK_EDIT_GROUPS
    template_name = "core/stock_transfer_form.html"
    form_class = StockTransferForm

    def get_initial(self):
        initial = super().get_initial()
        initial["occurred_at"] = timezone.localtime(timezone.now()).strftime(
            "%Y-%m-%dT%H:%M"
        )
        return initial

    def form_valid(self, form):
        try:
            movement = transfer_stock(
                item=form.cleaned_data["item"],
                source_warehouse=form.cleaned_data["source_warehouse"],
                destination_warehouse=form.cleaned_data["destination_warehouse"],
                source_location=form.cleaned_data.get("source_location"),
                destination_location=form.cleaned_data.get("destination_location"),
                qty=form.cleaned_data["qty"],
                comment=form.cleaned_data["comment"],
                occurred_at=form.cleaned_data["occurred_at"],
                performed_by=self.request.user,
                request=self.request,
            )
        except InsufficientStockError:
            message = _(
                "Недостатньо залишку на локації-відправнику. Перевірте залишки перед переміщенням."
            )
            messages.error(self.request, message)
            form.add_error(None, message)
            return self.form_invalid(form)
        except SameLocationTransferError:
            message = _(
                "Неможливо перемістити товар у ту саму локацію. Виберіть іншу локацію-отримувач."
            )
            messages.error(self.request, message)
            form.add_error(None, message)
            return self.form_invalid(form)
        except StockServiceError as exc:
            message = str(exc)
            messages.error(self.request, message)
            form.add_error(None, message)
            return self.form_invalid(form)
        return redirect("stock_transfer_result", pk=movement.pk)


class InitialBalanceView(LoginRequiredMixin, RequestUserFormKwargsMixin, GroupRequiredMixin, FormView):
    group_names = STOCK_EDIT_GROUPS
    template_name = "core/initial_balance_form.html"
    form_class = InitialBalanceForm

    def get_initial(self):
        initial = super().get_initial()
        initial["occurred_at"] = timezone.localtime(timezone.now()).strftime(
            "%Y-%m-%dT%H:%M"
        )
        return initial

    def form_valid(self, form):
        try:
            create_initial_balance(
                item=form.cleaned_data["item"],
                warehouse=form.cleaned_data["warehouse"],
                location=form.cleaned_data.get("location"),
                qty=form.cleaned_data["qty"],
                comment=form.cleaned_data["comment"],
                occurred_at=form.cleaned_data["occurred_at"],
                performed_by=self.request.user,
                request=self.request,
            )
        except StockServiceError as exc:
            message = str(exc)
            messages.error(self.request, message)
            form.add_error(None, message)
            return self.form_invalid(form)
        messages.success(self.request, _("Початковий залишок збережено."))
        return redirect("movement_list")
