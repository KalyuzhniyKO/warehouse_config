from core.models import AuditLog


def get_client_ip(request):
    if request is None:
        return None
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None


def build_object_repr(obj):
    if obj is None:
        return ""
    return str(obj)


def log_action(actor, action, obj=None, changes=None, request=None):
    if actor is not None and not getattr(actor, "is_authenticated", True):
        actor = None
    object_type = ""
    object_id = ""
    object_repr = ""
    if obj is not None:
        object_type = obj.__class__.__name__
        object_id = str(getattr(obj, "pk", "") or "")
        object_repr = build_object_repr(obj)
    return AuditLog.objects.create(
        actor=actor,
        action=action,
        object_type=object_type,
        object_id=object_id,
        object_repr=object_repr,
        changes=changes or {},
        ip_address=get_client_ip(request),
        user_agent=(
            request.META.get("HTTP_USER_AGENT", "") if request is not None else ""
        ),
    )
