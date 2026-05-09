"""PDF label generation and CUPS print helpers."""

import os
import subprocess
import tempfile
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import LabelTemplate, PrintJob
from core.services.barcodes import ensure_item_barcode

MM_TO_PT = 72 / 25.4
UNICODE_FONT_ERROR = (
    "Unicode font for PDF labels was not found. Install fonts-dejavu-core."
)
REGULAR_FONT_PATHS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
)
BOLD_FONT_PATHS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
)
WAREHOUSE_FONT_REGULAR = "WarehouseSans"
WAREHOUSE_FONT_BOLD = "WarehouseSansBold"
ASCII_FONT_REGULAR = "Helvetica"
ASCII_FONT_BOLD = "Helvetica-Bold"


def _contains_non_ascii(value):
    return any(ord(ch) > 127 for ch in str(value or ""))


def _first_existing_font(paths):
    for font_path in paths:
        path = Path(font_path)
        if path.exists():
            return str(path)
    return None


@lru_cache(maxsize=1)
def _discover_label_ttf_fonts():
    regular = _first_existing_font(REGULAR_FONT_PATHS)
    bold = _first_existing_font(BOLD_FONT_PATHS) or regular
    return regular, bold


@lru_cache(maxsize=1)
def _register_label_fonts():
    regular_path, bold_path = _discover_label_ttf_fonts()
    if not regular_path:
        return None

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    pdfmetrics.registerFont(TTFont(WAREHOUSE_FONT_REGULAR, regular_path))
    pdfmetrics.registerFont(TTFont(WAREHOUSE_FONT_BOLD, bold_path or regular_path))
    return WAREHOUSE_FONT_REGULAR, WAREHOUSE_FONT_BOLD


def _get_label_font_names(*, needs_unicode=False):
    registered_fonts = _register_label_fonts()
    if registered_fonts:
        return registered_fonts
    if needs_unicode:
        raise ImproperlyConfigured(UNICODE_FONT_ERROR)
    return ASCII_FONT_REGULAR, ASCII_FONT_BOLD


def _wrap_text_to_lines(pdf, text, font_name, font_size, max_width, max_lines=2):
    words = str(text or "").split()
    lines = []
    current = ""
    for word in words or [str(text or "")]:
        candidate = f"{current} {word}".strip()
        if not current or pdf.stringWidth(candidate, font_name, font_size) <= max_width:
            current = candidate
            continue
        lines.append(current)
        current = word
        if len(lines) == max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)

    if not lines:
        return []

    trimmed = lines[:max_lines]
    last = trimmed[-1]
    while pdf.stringWidth(last, font_name, font_size) > max_width and last:
        last = last[:-1]
    if len(lines) > max_lines or current not in trimmed or last != trimmed[-1]:
        suffix = "..."
        while last and pdf.stringWidth(last + suffix, font_name, font_size) > max_width:
            last = last[:-1]
        last = (last + suffix) if last else suffix
    trimmed[-1] = last
    return trimmed


def get_default_label_template():
    template = LabelTemplate.objects.filter(is_active=True, is_default=True).first()
    if template:
        return template
    template = LabelTemplate.objects.filter(is_active=True).order_by("id").first()
    if template:
        return template
    return LabelTemplate.objects.create(name=_("Стандартна 58×40 мм"), is_default=True)


def _pdf_escape(value):
    return str(value).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _fallback_pdf(item, template, barcode):
    if _contains_non_ascii(item.name):
        raise ImproperlyConfigured(UNICODE_FONT_ERROR)

    width = float(template.width_mm) * MM_TO_PT
    height = float(template.height_mm) * MM_TO_PT
    bars = []
    x = 8
    y = 17
    for idx, ch in enumerate(barcode):
        if (ord(ch) + idx) % 2 == 0:
            bars.append(f"{x:.2f} {y:.2f} 1.2 34 re f")
        x += 2.1
        if x > width - 8:
            break
    commands = [
        "BT /F1 8 Tf 6 %.2f Td (%s) Tj ET"
        % (height - 12, _pdf_escape(item.name[:45]))
    ]
    if template.show_internal_code and item.internal_code:
        commands.append(
            "BT /F1 6 Tf 6 %.2f Td (%s) Tj ET"
            % (height - 22, _pdf_escape(item.internal_code))
        )
    commands.extend(bars)
    if template.show_barcode_text:
        commands.append("BT /F1 7 Tf 6 6 Td (%s) Tj ET" % _pdf_escape(barcode))
    stream = "\n".join(commands).encode("utf-8")
    objects = []
    objects.append(b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n")
    objects.append(b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n")
    objects.append(
        (
            f"3 0 obj << /Type /Page /Parent 2 0 R "
            f"/MediaBox [0 0 {width:.2f} {height:.2f}] "
            "/Resources << /Font << /F1 4 0 R >> >> "
            "/Contents 5 0 R >> endobj\n"
        ).encode()
    )
    objects.append(b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n")
    objects.append((f"5 0 obj << /Length {len(stream)} >> stream\n").encode() + stream + b"\nendstream endobj\n")
    pdf = BytesIO()
    pdf.write(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(pdf.tell())
        pdf.write(obj)
    xref = pdf.tell()
    pdf.write(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        pdf.write(f"{offset:010d} 00000 n \n".encode())
    pdf.write(
        f"trailer << /Size {len(objects)+1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF".encode()
    )
    return pdf.getvalue()


def generate_item_label_pdf(item, template=None):
    template = template or get_default_label_template()
    barcode_registry = ensure_item_barcode(item)
    barcode_value = barcode_registry.barcode
    needs_unicode = _contains_non_ascii(item.name)
    try:
        from reportlab.graphics.barcode import code128
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas

        regular_font, bold_font = _get_label_font_names(needs_unicode=needs_unicode)
    except ImproperlyConfigured:
        raise
    except Exception:
        return _fallback_pdf(item, template, barcode_value)

    buffer = BytesIO()
    width = float(template.width_mm) * mm
    height = float(template.height_mm) * mm
    pdf = canvas.Canvas(buffer, pagesize=(width, height))
    margin_x = 3 * mm
    content_width = width - 2 * margin_x
    y = height - 5 * mm

    if template.show_item_name:
        name_font_size = 8
        pdf.setFont(bold_font, name_font_size)
        for line in _wrap_text_to_lines(
            pdf, item.name, bold_font, name_font_size, content_width, max_lines=2
        ):
            pdf.drawString(margin_x, y, line)
            y -= 4 * mm
        y -= 1 * mm

    if template.show_internal_code and item.internal_code:
        code_font_size = 6
        pdf.setFont(regular_font, code_font_size)
        code = str(item.internal_code)
        while pdf.stringWidth(code, regular_font, code_font_size) > content_width and code:
            code = code[:-1]
        pdf.drawString(margin_x, y, code)
        y -= 4 * mm

    barcode = code128.Code128(barcode_value, barHeight=16 * mm, barWidth=0.33 * mm)
    barcode_x = max(margin_x, (width - barcode.width) / 2)
    barcode_y = max(8 * mm, min(y - 17 * mm, height - 26 * mm))
    barcode.drawOn(pdf, barcode_x, barcode_y)

    if template.show_barcode_text:
        pdf.setFont(regular_font, 7)
        pdf.drawCentredString(width / 2, 3 * mm, barcode_value)

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def download_item_label_pdf(item):
    pdf = generate_item_label_pdf(item)
    response = HttpResponse(pdf, content_type="application/pdf")
    barcode = item.barcode.barcode if item.barcode_id else "label"
    response["Content-Disposition"] = f'attachment; filename="{barcode}.pdf"'
    return response


def print_item_label(*, item, printer, label_template, copies=1, user=None):
    barcode_registry = ensure_item_barcode(item)
    job = PrintJob.objects.create(
        printer=printer,
        item=item,
        barcode=barcode_registry.barcode,
        label_template=label_template,
        copies=copies,
        user=user if getattr(user, "is_authenticated", False) else None,
    )
    pdf_bytes = generate_item_label_pdf(item, label_template)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name
        result = subprocess.run(
            ["lp", "-d", printer.system_name, "-n", str(copies), tmp_path],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            job.status = PrintJob.Status.PRINTED
            job.printed_at = timezone.now()
            job.error_message = ""
        else:
            job.status = PrintJob.Status.FAILED
            job.error_message = (result.stderr or result.stdout or _("Невідома помилка друку.")).strip()
    except Exception as exc:
        job.status = PrintJob.Status.FAILED
        job.error_message = str(exc)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
    job.save(update_fields=["status", "error_message", "printed_at"])
    return job
