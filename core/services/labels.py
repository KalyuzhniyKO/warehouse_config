"""PDF label generation and CUPS print helpers."""

import os
import subprocess
import tempfile
from io import BytesIO

from django.http import HttpResponse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import LabelTemplate, PrintJob
from core.services.barcodes import ensure_item_barcode

MM_TO_PT = 72 / 25.4


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
    commands = ["BT /F1 8 Tf 6 %.2f Td (%s) Tj ET" % (height - 12, _pdf_escape(item.name[:45]))]
    if template.show_internal_code and item.internal_code:
        commands.append("BT /F1 6 Tf 6 %.2f Td (%s) Tj ET" % (height - 22, _pdf_escape(item.internal_code)))
    commands.extend(bars)
    if template.show_barcode_text:
        commands.append("BT /F1 7 Tf 6 6 Td (%s) Tj ET" % _pdf_escape(barcode))
    stream = "\n".join(commands).encode("utf-8")
    objects = []
    objects.append(b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n")
    objects.append(b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n")
    objects.append((f"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 {width:.2f} {height:.2f}] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n").encode())
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
    pdf.write(f"trailer << /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    return pdf.getvalue()


def generate_item_label_pdf(item, template=None):
    template = template or get_default_label_template()
    barcode_registry = ensure_item_barcode(item)
    barcode_value = barcode_registry.barcode
    try:
        from reportlab.graphics.barcode import code128
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas
    except Exception:
        return _fallback_pdf(item, template, barcode_value)

    buffer = BytesIO()
    width = float(template.width_mm) * mm
    height = float(template.height_mm) * mm
    pdf = canvas.Canvas(buffer, pagesize=(width, height))
    y = height - 5 * mm
    if template.show_item_name:
        pdf.setFont("Helvetica-Bold", 8)
        pdf.drawString(3 * mm, y, item.name[:42])
        y -= 5 * mm
    if template.show_internal_code and item.internal_code:
        pdf.setFont("Helvetica", 6)
        pdf.drawString(3 * mm, y, str(item.internal_code)[:44])
        y -= 4 * mm
    barcode = code128.Code128(barcode_value, barHeight=16 * mm, barWidth=0.33 * mm)
    barcode.drawOn(pdf, 3 * mm, max(9 * mm, y - 17 * mm))
    if template.show_barcode_text:
        pdf.setFont("Helvetica", 7)
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
