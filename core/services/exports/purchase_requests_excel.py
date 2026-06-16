from django.utils.timezone import localtime
from django.utils.translation import gettext_lazy as _


def _display_user(user):
    if not user:
        return ""
    return user.get_full_name() or user.get_username()


def _local_datetime(value):
    if not value:
        return ""
    return localtime(value).replace(tzinfo=None)


def build_purchase_requests_workbook(purchase_requests):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    headers = [
        _("Дата"),
        _("Назва товару"),
        _("Опис потреби"),
        _("Кількість"),
        _("Одиниця виміру"),
        _("Вартість за одиницю"),
        _("Сума"),
        _("Тип замовлення"),
        _("Статус погодження"),
        _("Статус оплати"),
        _("Статус доставки"),
        _("Заявник"),
        _("Ким погоджено"),
        _("Дата погодження"),
        _("Ким відхилено"),
        _("Дата відхилення"),
        _("Коментар відхилення"),
        _("Посилання на товар"),
    ]
    widths = [14, 34, 42, 12, 16, 20, 16, 18, 20, 24, 20, 24, 24, 21, 24, 21, 34, 38]

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Purchase requests"
    sheet.append([str(header) for header in headers])

    for purchase_request in purchase_requests:
        sheet.append(
            [
                purchase_request.request_date,
                purchase_request.title,
                purchase_request.need_description,
                purchase_request.requested_qty,
                purchase_request.unit,
                purchase_request.unit_price_uah or "",
                purchase_request.total_price_uah or "",
                purchase_request.get_order_type_display(),
                purchase_request.get_approval_status_display(),
                purchase_request.get_payment_status_display(),
                purchase_request.get_delivery_status_display(),
                _display_user(purchase_request.requested_by),
                _display_user(purchase_request.approved_by),
                _local_datetime(purchase_request.approved_at),
                _display_user(purchase_request.rejected_by),
                _local_datetime(purchase_request.rejected_at),
                purchase_request.rejection_comment,
                purchase_request.product_url,
            ]
        )

    header_fill = PatternFill("solid", fgColor="D4AC00")
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="101828")
        cell.fill = header_fill
        cell.alignment = Alignment(wrap_text=True, vertical="top")

    for index, width in enumerate(widths, start=1):
        column_letter = sheet.cell(row=1, column=index).column_letter
        sheet.column_dimensions[column_letter].width = width

    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions

    for row in sheet.iter_rows(min_row=2):
        row[0].number_format = "yyyy-mm-dd"
        row[1].alignment = Alignment(wrap_text=True, vertical="top")
        row[2].alignment = Alignment(wrap_text=True, vertical="top")
        row[3].number_format = "#,##0.###"
        row[5].number_format = "#,##0.00"
        row[6].number_format = "#,##0.00"
        row[13].number_format = "yyyy-mm-dd hh:mm:ss"
        row[15].number_format = "yyyy-mm-dd hh:mm:ss"
        row[16].alignment = Alignment(wrap_text=True, vertical="top")

    return workbook
