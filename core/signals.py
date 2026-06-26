from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from core.services.audit import log_action


@receiver(user_logged_in)
def audit_user_logged_in(sender, request, user, **kwargs):
    log_action(user, "auth.login", obj=user, request=request)


@receiver(user_logged_out)
def audit_user_logged_out(sender, request, user, **kwargs):
    log_action(user, "auth.logout", obj=user, request=request)


@receiver(user_login_failed)
def audit_user_login_failed(sender, credentials, request, **kwargs):
    username = (credentials or {}).get("username") or ""
    log_action(
        None,
        "auth.login_failed",
        changes={"username": username},
        request=request,
    )
