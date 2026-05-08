from django import template
from django.conf import settings

register = template.Library()

_LANGUAGE_FLAGS = {
    "uk": "🇺🇦",
    "ru": "🇷🇺",
    "en": "🇬🇧",
    "de": "🇩🇪",
    "pl": "🇵🇱",
    "fr": "🇫🇷",
    "es": "🇪🇸",
    "it": "🇮🇹",
    "pt": "🇵🇹",
    "tr": "🇹🇷",
}


def _supported_language_codes():
    return {language_code for language_code, _language_name in settings.LANGUAGES}


def switch_language_url(request, language_code):
    """Return the current URL with its leading language prefix switched."""
    supported_language_codes = _supported_language_codes()
    if language_code not in supported_language_codes:
        language_code = settings.LANGUAGE_CODE

    path = getattr(request, "path_info", None) or getattr(request, "path", "") or "/"
    if not path.startswith("/"):
        path = f"/{path}"

    segments = path.split("/")
    if len(segments) > 1 and segments[1] in supported_language_codes:
        segments[1] = language_code
        localized_path = "/".join(segments)
    elif path == "/":
        localized_path = f"/{language_code}/"
    else:
        localized_path = f"/{language_code}{path}"

    query_string = getattr(request, "META", {}).get("QUERY_STRING", "")
    return f"{localized_path}?{query_string}" if query_string else localized_path


@register.simple_tag(name="switch_language_url")
def switch_language_url_tag(request, language_code):
    return switch_language_url(request, language_code)


@register.simple_tag
def language_flag(language_code):
    return _LANGUAGE_FLAGS.get(language_code, "🌐")
