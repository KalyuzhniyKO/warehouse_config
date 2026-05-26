from urllib.parse import urlencode

from django.http import QueryDict

FILTER_MEMORY_SESSION_KEY = "remembered_filters"
RESET_FILTERS_PARAM = "reset_filters"

PAGE_ALLOWED_PARAMS = {
    "management_analytics": ["period", "date_from", "date_to", "warehouse", "location", "movement_type"],
    "management_analytics_data_quality": ["period", "date_from", "date_to", "warehouse", "location", "movement_type"],
    "movement_list": [
        "date_from",
        "date_to",
        "movement_type",
        "warehouse",
        "location",
        "item_id",
        "recipient_id",
        "usage_place_id",
        "document_number",
        "no_document",
        "missing_recipient",
        "missing_usage_place",
        "missing_destination",
        "invalid_qty",
        "q",
    ],
}


def get_filter_memory_key(request, page_key):
    return f"{FILTER_MEMORY_SESSION_KEY}:{page_key}"


def get_allowed_filter_params(page_key):
    return PAGE_ALLOWED_PARAMS.get(page_key, [])


def _clean_params(page_key, params):
    allowed = set(get_allowed_filter_params(page_key))
    cleaned = {}
    for key in allowed:
        value = params.get(key)
        if value in (None, ""):
            continue
        cleaned[key] = value
    return cleaned


def remember_filters(request, page_key, params):
    if not request.user.is_authenticated:
        return
    cleaned = _clean_params(page_key, params)
    request.session[get_filter_memory_key(request, page_key)] = cleaned
    request.session.modified = True


def get_remembered_filters(request, page_key):
    if not request.user.is_authenticated:
        return {}
    return request.session.get(get_filter_memory_key(request, page_key), {})


def clear_remembered_filters(request, page_key):
    if not request.user.is_authenticated:
        return
    request.session.pop(get_filter_memory_key(request, page_key), None)
    request.session.modified = True


def apply_remembered_filters(request, page_key, default_params=None):
    default_params = default_params or {}
    if request.GET.get(RESET_FILTERS_PARAM) == "1":
        clear_remembered_filters(request, page_key)
        return default_params, False, False

    incoming = _clean_params(page_key, request.GET)
    if incoming:
        remember_filters(request, page_key, incoming)
        merged = {**default_params, **incoming}
        return merged, False, False

    remembered = get_remembered_filters(request, page_key)
    if remembered:
        merged = {**default_params, **remembered}
        return merged, True, True

    return default_params, False, False


def build_redirect_url(path, params):
    query = urlencode(params)
    return f"{path}?{query}" if query else path


def querydict_from_params(params):
    qd = QueryDict("", mutable=True)
    for key, value in params.items():
        qd[key] = str(value)
    return qd
