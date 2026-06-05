import ast
import struct
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils.translation import trans_real


_COMPILED_LOCALES = set()


def compile_test_messages(locales=None):
    """Compile test catalogs even when GNU gettext is unavailable locally."""
    locale_tuple = tuple(locales or _available_locales())
    missing = tuple(locale for locale in locale_tuple if locale not in _COMPILED_LOCALES)
    if not missing:
        return True

    options = {"stdout": StringIO(), "verbosity": 0}
    if locales:
        options["locale"] = list(locales)

    try:
        call_command("compilemessages", **options)
    except CommandError as exc:
        if "msgfmt" not in str(exc):
            raise
        _compile_with_python(missing)

    _COMPILED_LOCALES.update(missing)
    trans_real._translations.clear()
    trans_real._default = None
    return True


def _available_locales():
    locale_roots = settings.LOCALE_PATHS or (Path(settings.BASE_DIR) / "locale",)
    languages = []
    for root in locale_roots:
        root_path = Path(root)
        if not root_path.exists():
            continue
        languages.extend(path.name for path in root_path.iterdir() if path.is_dir())
    return sorted(set(languages))


def _compile_with_python(locales):
    locale_roots = settings.LOCALE_PATHS or (Path(settings.BASE_DIR) / "locale",)
    for root in locale_roots:
        root_path = Path(root)
        for locale in locales:
            po_path = root_path / locale / "LC_MESSAGES" / "django.po"
            if not po_path.exists():
                continue
            mo_path = po_path.with_suffix(".mo")
            mo_path.write_bytes(_build_mo(_parse_po(po_path)))


def _parse_po(path):
    catalog = {}
    entry = _new_entry()
    active_field = None

    def finish():
        nonlocal entry
        if entry["msgid"] is None or entry["obsolete"]:
            entry = _new_entry()
            return
        if "fuzzy" in entry["flags"]:
            entry = _new_entry()
            return
        key = entry["msgid"]
        if entry["msgctxt"] is not None:
            key = f'{entry["msgctxt"]}\x04{key}'
        if entry["msgid_plural"] is not None:
            key = f'{key}\x00{entry["msgid_plural"]}'
        value = "\x00".join(
            entry["msgstrs"].get(index, "")
            for index in range(max(entry["msgstrs"].keys(), default=0) + 1)
        )
        if key and not value:
            entry = _new_entry()
            return
        catalog[key] = value
        entry = _new_entry()

    for raw_line in path.read_text(encoding="utf-8").splitlines() + [""]:
        line = raw_line.strip()
        if line == "":
            finish()
            active_field = None
            continue
        if line.startswith("#~"):
            entry["obsolete"] = True
            continue
        if line.startswith("#,"):
            entry["flags"].extend(flag.strip() for flag in line[2:].split(","))
            continue
        if line.startswith("#"):
            continue
        if line.startswith("msgctxt "):
            entry["msgctxt"] = _po_string(line[8:])
            active_field = ("msgctxt", None)
        elif line.startswith("msgid_plural "):
            entry["msgid_plural"] = _po_string(line[13:])
            active_field = ("msgid_plural", None)
        elif line.startswith("msgid "):
            entry["msgid"] = _po_string(line[6:])
            active_field = ("msgid", None)
        elif line.startswith("msgstr["):
            index_end = line.index("]")
            index = int(line[7:index_end])
            entry["msgstrs"][index] = _po_string(line[index_end + 1 :].strip())
            active_field = ("msgstr", index)
        elif line.startswith("msgstr "):
            entry["msgstrs"][0] = _po_string(line[7:])
            active_field = ("msgstr", 0)
        elif line.startswith('"') and active_field:
            value = _po_string(line)
            field, index = active_field
            if field == "msgstr":
                entry["msgstrs"][index] = entry["msgstrs"].get(index, "") + value
            else:
                entry[field] = (entry[field] or "") + value

    return catalog


def _new_entry():
    return {
        "msgctxt": None,
        "msgid": None,
        "msgid_plural": None,
        "msgstrs": {},
        "flags": [],
        "obsolete": False,
    }


def _po_string(value):
    return ast.literal_eval(value)


def _build_mo(catalog):
    keys = sorted(catalog)
    ids = [key.encode("utf-8") for key in keys]
    values = [catalog[key].encode("utf-8") for key in keys]

    count = len(keys)
    key_table_offset = 7 * 4
    value_table_offset = key_table_offset + count * 8
    key_strings_offset = value_table_offset + count * 8
    value_strings_offset = key_strings_offset + sum(len(item) + 1 for item in ids)

    key_offsets = []
    offset = key_strings_offset
    for item in ids:
        key_offsets.append((len(item), offset))
        offset += len(item) + 1

    value_offsets = []
    offset = value_strings_offset
    for item in values:
        value_offsets.append((len(item), offset))
        offset += len(item) + 1

    output = [
        struct.pack("<Iiiiiii", 0x950412DE, 0, count, key_table_offset, value_table_offset, 0, 0),
        b"".join(struct.pack("<ii", *item) for item in key_offsets),
        b"".join(struct.pack("<ii", *item) for item in value_offsets),
        b"".join(item + b"\0" for item in ids),
        b"".join(item + b"\0" for item in values),
    ]
    return b"".join(output)
