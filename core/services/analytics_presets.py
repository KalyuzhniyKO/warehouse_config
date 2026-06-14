from urllib.parse import urlencode

from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from .analytics.filters import get_analytics_filters


CATEGORY_META = {
    "operations": {
        "title": _("Операційні звіти"),
        "description": _("Щоденні рухи складу: видача, прихід, повернення та переміщення."),
    },
    "analytics": {
        "title": _("Аналітичні звіти"),
        "description": _("Підсумки по товарах, цехах, отримувачах та активності."),
    },
    "quality": {
        "title": _("Контроль якості даних"),
        "description": _("Перевірки документів, неповних рухів та проблемних залишків."),
    },
    "export": {
        "title": _("Експорт"),
        "description": _("Швидке відкриття журналів та вивантаження даних."),
    },
}


def get_analytics_report_presets():
    recent_period = get_analytics_filters({"period": "7d"})
    recent_journal_params = {
        "report_scope": "business",
        "date_from": recent_period["date_from"],
        "date_to": recent_period["date_to"],
    }
    presets = [
        {"key": "issue_7d", "title": _("Видача за 7 днів"), "description": _("Відкриває аналітику видачі зі складу за останні 7 днів."), "hint": _("Швидко перевірити короткий період активних відвантажень."), "calculation_rule": _("Сума кількості активних операцій видачі за occurred_at за останні 7 днів."), "category": "operations", "target_url": reverse("management_analytics"), "params": {"period": "7d", "movement_type": "out"}, "export_supported": True},
        {"key": "issue_30d", "title": _("Видача за 30 днів"), "description": _("Відкриває аналітику видачі зі складу за останні 30 днів."), "hint": _("Зручно для місячного огляду складських витрат."), "calculation_rule": _("Сума кількості активних операцій видачі за occurred_at за останні 30 днів."), "category": "operations", "target_url": reverse("management_analytics"), "params": {"period": "30d", "movement_type": "out"}, "export_supported": True},
        {"key": "top_items_month", "title": _("Топ товарів за місяць"), "description": _("Відкриває аналітику поточного місяця з фокусом на найбільшу видачу товарів."), "hint": _("Показує, які позиції найчастіше виходять зі складу."), "calculation_rule": _("Сума активної видачі за товаром за occurred_at у поточному місяці."), "category": "analytics", "target_url": reverse("management_analytics"), "params": {"period": "month", "movement_type": "out"}, "export_supported": True},
        {"key": "top_usage_places_month", "title": _("Топ цехів за місяць"), "description": _("Відкриває аналітику поточного місяця по цехах і місцях використання."), "hint": _("Допомагає побачити основних споживачів матеріалів."), "calculation_rule": _("Сума активної видачі за цехом за occurred_at у поточному місяці."), "category": "analytics", "target_url": reverse("management_analytics"), "params": {"period": "month", "movement_type": "out"}, "export_supported": True},
        {"key": "missing_documents", "title": _("Рухи без документа"), "description": _("Відкриває журнал рухів, відфільтрований за відсутнім номером документа."), "hint": _("Корисно для швидкого виправлення неповних операцій."), "calculation_rule": _("Активні господарські операції без номера документа; анулювання виключено."), "category": "quality", "target_url": reverse("movement_list"), "params": {"report_scope": "business", "no_document": "1"}},
        {"key": "data_quality", "title": _("Проблеми якості даних"), "description": _("Відкриває огляд перевірок цілісності даних та узгодженості рухів."), "hint": _("Зібраний контроль документів, отримувачів, кількості та залишків."), "calculation_rule": _("Перевірки активних господарських операцій та поточних залишків за вибраний період."), "category": "quality", "target_url": reverse("management_analytics_data_quality"), "params": {"period": "30d"}, "export_supported": True},
        {"key": "negative_stock", "title": _("Негативні залишки"), "description": _("Відкриває секцію контролю якості з перевіркою від’ємних залишків."), "hint": _("Підсвічує позиції, які потребують звірки рухів."), "calculation_rule": _("Кількість поточних від’ємних залишків у вибраному складі або локації."), "category": "quality", "target_url": reverse("management_analytics_data_quality"), "params": {"period": "30d"}, "anchor": "negative-stock"},
        {"key": "inactive_stock", "title": _("Неактивні товари з залишком"), "description": _("Відкриває аналітику залишків по неактивних товарах."), "hint": _("Допомагає знайти залишки, які не рухалися в останній період."), "calculation_rule": _("Поточні додатні залишки без активних господарських операцій за період."), "category": "analytics", "target_url": reverse("management_analytics"), "params": {"period": "30d"}, "anchor": "inactive-stock-items", "export_supported": True},
        {"key": "recent_movements", "title": _("Останні операції"), "description": _("Відкриває журнал складських операцій за останні 7 днів."), "hint": _("Швидкий перехід до актуального журналу рухів."), "calculation_rule": _("Активні господарські операції за occurred_at за останні 7 днів."), "category": "export", "target_url": reverse("movement_list"), "params": recent_journal_params},
    ]

    for preset in presets:
        category_meta = CATEGORY_META[preset["category"]]
        preset["category_title"] = category_meta["title"]
        preset["category_description"] = category_meta["description"]
        preset["primary_action_label"] = _("Відкрити")
        preset["export_label"] = _("Excel")
        query = urlencode(preset.get("params", {}))
        preset["url"] = f"{preset['target_url']}?{query}" if query else preset["target_url"]
        if preset.get("anchor"):
            preset["url"] = f"{preset['url']}#{preset['anchor']}"
        if preset.get("export_supported"):
            export_base = reverse("management_analytics_export_xlsx")
            preset["xlsx_url"] = f"{export_base}?{query}" if query else export_base
    return presets
