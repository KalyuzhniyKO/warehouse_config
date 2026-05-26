from urllib.parse import urlencode

from django.urls import reverse
from django.utils.translation import gettext_lazy as _


def get_analytics_report_presets():
    presets = [
        {"key": "issue_7d", "title": _("Видача за 7 днів"), "description": _("Операції видачі за останні 7 днів."), "category": "operations", "category_title": _("Операційні звіти"), "target_url": reverse("management_analytics"), "params": {"period": "7d", "movement_type": "out"}, "export_supported": True},
        {"key": "issue_30d", "title": _("Видача за 30 днів"), "description": _("Операції видачі за останні 30 днів."), "category": "operations", "category_title": _("Операційні звіти"), "target_url": reverse("management_analytics"), "params": {"period": "30d", "movement_type": "out"}, "export_supported": True},
        {"key": "top_items_month", "title": _("Топ товарів за місяць"), "description": _("Аналітика з фокусом на товари з найбільшою видачею."), "category": "analytics", "category_title": _("Аналітичні звіти"), "target_url": reverse("management_analytics"), "params": {"period": "month", "movement_type": "out"}, "export_supported": True},
        {"key": "top_usage_places_month", "title": _("Топ цехів за місяць"), "description": _("Звіт по місцях використання за поточний місяць."), "category": "analytics", "category_title": _("Аналітичні звіти"), "target_url": reverse("management_analytics"), "params": {"period": "month", "movement_type": "out"}, "export_supported": True},
        {"key": "missing_documents", "title": _("Рухи без документа"), "description": _("Журнал рухів з порожнім номером документа."), "category": "quality", "category_title": _("Контроль якості даних"), "target_url": reverse("movement_list"), "params": {"no_document": "1"}},
        {"key": "data_quality", "title": _("Проблеми якості даних"), "description": _("Огляд перевірок цілісності даних та узгодженості рухів."), "category": "quality", "category_title": _("Контроль якості даних"), "target_url": reverse("management_analytics_data_quality"), "params": {"period": "30d"}, "export_supported": True},
        {"key": "negative_stock", "title": _("Негативні залишки"), "description": _("Перевірка від’ємних залишків у секції контролю якості."), "category": "quality", "category_title": _("Контроль якості даних"), "target_url": reverse("management_analytics_data_quality"), "params": {"period": "30d"}, "anchor": "negative-stock"},
        {"key": "inactive_stock", "title": _("Неактивні товари з залишком"), "description": _("Аналітика залишків по неактивних товарах."), "category": "analytics", "category_title": _("Аналітичні звіти"), "target_url": reverse("management_analytics"), "params": {"period": "30d"}, "anchor": "inactive-stock-items", "export_supported": True},
        {"key": "recent_movements", "title": _("Останні операції"), "description": _("Журнал операцій за останні 7 днів."), "category": "export", "category_title": _("Експорт"), "target_url": reverse("movement_list"), "params": {"period": "7d"}},
    ]

    for preset in presets:
        query = urlencode(preset.get("params", {}))
        preset["url"] = f"{preset['target_url']}?{query}" if query else preset["target_url"]
        if preset.get("anchor"):
            preset["url"] = f"{preset['url']}#{preset['anchor']}"
        if preset.get("export_supported"):
            export_base = reverse("management_analytics_export_xlsx")
            preset["xlsx_url"] = f"{export_base}?{query}" if query else export_base
    return presets
