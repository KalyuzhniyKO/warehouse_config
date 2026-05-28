import os
import subprocess
import tempfile
from io import BytesIO

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import Printer

MM_TO_PT = 72 / 25.4
TEST_PAGE_WIDTH_MM = 58
TEST_PAGE_HEIGHT_MM = 40


class PrinterDiscoveryError(Exception):
    """Raised when CUPS printer discovery cannot be completed."""


def _run_command(args):
    try:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        command = args[0]
        if command == "lpstat":
            message = _("Команда lpstat недоступна. Встановіть cups-client.")
        elif command == "lp":
            message = _("Команда lp недоступна. Встановіть cups-client.")
        else:
            message = _("Команда %(command)s недоступна.") % {"command": command}
        raise PrinterDiscoveryError(str(message)) from exc


def _command_error(result, fallback):
    return (result.stderr or result.stdout or fallback).strip()


def _is_no_destinations_output(text):
    normalized = (text or "").strip().lower()
    return "no destinations added" in normalized


def _parse_lpstat_printers(output):
    printers = []
    seen = set()
    for raw_line in output.splitlines():
        line = raw_line.strip()
        system_name = None
        if line.startswith("device for ") and ":" in line:
            system_name = line.split(":", 1)[0].replace("device for ", "", 1).strip()
        elif line.startswith("printer "):
            parts = line.split()
            if len(parts) >= 2:
                system_name = parts[1].strip()
        if not system_name or system_name in seen:
            continue
        seen.add(system_name)
        printers.append(
            {
                "system_name": system_name,
                "name": system_name,
                "raw": line,
            }
        )
    return printers


def list_system_printers():
    result = _run_command(["lpstat", "-v"])
    if result.returncode != 0 and _is_no_destinations_output(
        _command_error(result, "")
    ):
        return []
    if result.returncode != 0:
        result = _run_command(["lpstat", "-p"])
        if result.returncode != 0 and _is_no_destinations_output(
            _command_error(result, "")
        ):
            return []
    if result.returncode != 0:
        raise PrinterDiscoveryError(
            _command_error(result, _("Не вдалося отримати список CUPS-принтерів."))
        )
    return _parse_lpstat_printers(result.stdout)


def get_default_system_printer():
    result = _run_command(["lpstat", "-d"])
    if result.returncode != 0:
        text = _command_error(result, "")
        if "no system default destination" in text.lower():
            return None
        raise PrinterDiscoveryError(
            text or str(_("Не вдалося отримати CUPS-принтер за замовчуванням."))
        )

    line = (result.stdout or "").strip()
    if not line or "no system default destination" in line.lower():
        return None
    marker = "system default destination:"
    if marker in line.lower():
        return line.split(":", 1)[1].strip() or None
    return None


def check_printer_exists(system_name):
    normalized = (system_name or "").strip()
    if not normalized:
        return False
    return any(
        printer["system_name"] == normalized for printer in list_system_printers()
    )


@transaction.atomic
def sync_system_printers_to_db():
    system_printers = list_system_printers()
    default_system_name = get_default_system_printer()
    created = 0
    updated = 0

    for system_printer in system_printers:
        system_name = system_printer["system_name"]
        printer, was_created = Printer.objects.get_or_create(
            system_name=system_name,
            defaults={
                "name": system_printer.get("name") or system_name,
                "description": "",
                "is_active": True,
                "is_default": system_name == default_system_name,
            },
        )
        if was_created:
            created += 1
            continue

        fields = []
        if not printer.is_active:
            printer.is_active = True
            fields.append("is_active")
        should_be_default = system_name == default_system_name
        if printer.is_default != should_be_default:
            printer.is_default = should_be_default
            fields.append("is_default")
        if fields:
            printer.save(update_fields=fields + ["updated_at"])
            updated += 1

    if default_system_name:
        Printer.objects.exclude(system_name=default_system_name).update(is_default=False)

    return {
        "created": created,
        "updated": updated,
        "total": len(system_printers),
        "default_system_name": default_system_name,
    }


def _printer_not_found_message(printer):
    return _(
        "Принтер '%(name)s' не знайдено в CUPS. Перевірте системну назву або синхронізуйте принтери."
    ) % {"name": printer.name}


def _pdf_escape(value):
    return str(value).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _fallback_test_pdf(lines):
    width = TEST_PAGE_WIDTH_MM * MM_TO_PT
    height = TEST_PAGE_HEIGHT_MM * MM_TO_PT
    commands = []
    y = height - 16
    for idx, line in enumerate(lines):
        font_size = 10 if idx == 0 else 6
        commands.append(
            "BT /F1 %(size)s Tf 8 %(y).2f Td (%(text)s) Tj ET"
            % {"size": font_size, "y": y, "text": _pdf_escape(line[:48])}
        )
        y -= 12 if idx == 0 else 9
    stream = "\n".join(commands).encode("utf-8", errors="replace")
    objects = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
        (
            f"3 0 obj << /Type /Page /Parent 2 0 R "
            f"/MediaBox [0 0 {width:.2f} {height:.2f}] "
            "/Resources << /Font << /F1 4 0 R >> >> "
            "/Contents 5 0 R >> endobj\n"
        ).encode(),
        b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
        (f"5 0 obj << /Length {len(stream)} >> stream\n").encode()
        + stream
        + b"\nendstream endobj\n",
    ]
    pdf = BytesIO()
    pdf.write(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(pdf.tell())
        pdf.write(obj)
    xref = pdf.tell()
    pdf.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        pdf.write(f"{offset:010d} 00000 n \n".encode())
    pdf.write(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF".encode()
    )
    return pdf.getvalue()


def _generate_test_pdf(printer, system_name):
    timestamp = timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "TEST PRINT",
        f"Printer: {printer.name}",
        f"CUPS queue: {system_name}",
        f"Time: {timestamp}",
    ]
    try:
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas

        buffer = BytesIO()
        pdf = canvas.Canvas(
            buffer,
            pagesize=(TEST_PAGE_WIDTH_MM * mm, TEST_PAGE_HEIGHT_MM * mm),
        )
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(4 * mm, 32 * mm, lines[0])
        pdf.setFont("Helvetica", 6)
        y = 25 * mm
        for line in lines[1:]:
            pdf.drawString(4 * mm, y, line[:56])
            y -= 6 * mm
        pdf.showPage()
        pdf.save()
        return buffer.getvalue()
    except Exception:
        return _fallback_test_pdf(lines)


def print_test_page(printer):
    system_name = (printer.system_name or "").strip()
    tmp_path = None
    try:
        if not check_printer_exists(system_name):
            return {"success": False, "message": _printer_not_found_message(printer)}

        pdf_bytes = _generate_test_pdf(printer, system_name)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name

        result = _run_command(["lp", "-d", system_name, tmp_path])
        if result.returncode == 0:
            return {
                "success": True,
                "message": _("Тестову сторінку відправлено на друк."),
            }
        return {
            "success": False,
            "message": _command_error(result, _("Не вдалося надрукувати тестову сторінку.")),
        }
    except PrinterDiscoveryError as exc:
        return {"success": False, "message": str(exc)}
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
