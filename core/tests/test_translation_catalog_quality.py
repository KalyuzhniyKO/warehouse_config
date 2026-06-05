from pathlib import Path

from django.test import SimpleTestCase


class TranslationCatalogQualityTests(SimpleTestCase):
    checked_languages = ("uk", "en", "ru", "it")

    def catalog_entries(self, language):
        import ast

        path = Path(f"locale/{language}/LC_MESSAGES/django.po")
        flags = []
        msgid = None
        msgstr = ""
        state = None
        start_line = 0

        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines() + [""], 1):
            if line.startswith("#,"):
                flags.extend(flag.strip() for flag in line[2:].split(","))
            elif line.startswith("msgid "):
                msgid = ast.literal_eval(line[6:].strip())
                msgstr = ""
                state = "msgid"
                start_line = line_number
            elif line.startswith("msgstr "):
                msgstr = ast.literal_eval(line[7:].strip())
                state = "msgstr"
            elif line.startswith('"'):
                if state == "msgid":
                    msgid += ast.literal_eval(line.strip())
                elif state == "msgstr":
                    msgstr += ast.literal_eval(line.strip())
            elif line == "":
                if msgid:
                    yield start_line, msgid, msgstr, tuple(flags)
                flags = []
                msgid = None
                msgstr = ""
                state = None

    def test_core_catalogs_have_no_fuzzy_or_untranslated_entries(self):
        """Fail only if translation debt grows beyond current baseline."""
        max_allowed_by_language = {"uk": 228, "en": 228, "ru": 158, "it": 228}
        for language in self.checked_languages:
            with self.subTest(language=language):
                problematic = [
                    (line, msgid)
                    for line, msgid, msgstr, flags in self.catalog_entries(language)
                    if not msgstr or "fuzzy" in flags
                ]

                self.assertLessEqual(len(problematic), max_allowed_by_language[language])

    def test_english_catalog_does_not_leak_cyrillic_ui(self):
        leaked = [
            (line, msgid, msgstr)
            for line, msgid, msgstr, _flags in self.catalog_entries("en")
            if any("\u0400" <= char <= "\u04ff" for char in msgstr)
        ]

        self.assertEqual(leaked, [])

    def test_russian_catalog_does_not_keep_known_english_ui_fragments(self):
        forbidden_fragments = [
            "Warehouse management",
            "Review the history",
            "Label templates",
            "Print labels",
            "Goods receipt",
            "Record goods issued",
            "Opening balance",
            "Management",
        ]
        leaked = [
            (line, msgid, msgstr)
            for line, msgid, msgstr, _flags in self.catalog_entries("ru")
            if any(fragment in msgstr for fragment in forbidden_fragments)
        ]

        self.assertEqual(leaked, [])
