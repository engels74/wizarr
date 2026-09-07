"""Timestamp-only extraction must not create daily translation PRs."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

from babel.messages.catalog import Catalog
from babel.messages.pofile import write_po

spec = importlib.util.spec_from_file_location(
    "translation_refresh", Path(__file__).parents[1] / "refresh-translations.py"
)
refresh_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refresh_module)


class TranslationRefreshTests(unittest.TestCase):
    def test_real_extraction_is_idempotent_but_detects_new_messages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            locale = root / "app/translations/da/LC_MESSAGES"
            locale.mkdir(parents=True)
            catalog = Catalog(locale="da")
            catalog.add("Original message", "Oprindelig besked")
            with (locale / "messages.po").open("wb") as output:
                write_po(output, catalog)
            (root / "babel.cfg").write_text("[python: app/**.py]\n")
            source = root / "app/example.py"
            source.write_text('_("Original message")\n')
            self.assertTrue(refresh_module.refresh(root))
            template = root / "messages.pot"
            initial = template.read_text()
            import re

            old = re.sub(
                r'"POT-Creation-Date:[^\n]+',
                r'"POT-Creation-Date: 2000-01-01 00:00+0000\\n"',
                initial,
            )
            template.write_text(old)
            self.assertFalse(refresh_module.refresh(root))
            self.assertEqual(template.read_text(), old)
            source.write_text('_("New message")\n')
            self.assertTrue(refresh_module.refresh(root))
            self.assertIn('msgid "New message"', template.read_text())


if __name__ == "__main__":
    unittest.main()
