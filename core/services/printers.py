import os
import subprocess
import tempfile
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import Printer


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
    if result.returncode != 0:
        result = _run_command(["lpstat", "-p"])
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


def print_test_page(printer):
    system_name = (printer.system_name or "").strip()
    if not check_printer_exists(system_name):
        return {
            "success": False,
            "message": _("Принтер '%(name)s' не знайдено в CUPS. Перевірте системну назву або синхронізуйте принтери.")
            % {"name": printer.name},
        }

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt", encoding="utf-8") as tmp:
            tmp.write("Warehouse label printer test\n")
            tmp.write(f"Printer: {printer.name}\n")
            tmp.write(f"CUPS queue: {system_name}\n")
            tmp.write(f"Time: {timezone.now().isoformat()}\n")
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
