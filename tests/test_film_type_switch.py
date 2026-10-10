"""Film-type switch: persist leaving mode, restore target mode, no stray layout control."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QPushButton

import app as app_module
from scraper.sources import enabled_names
from ui import MainWindow


_APP: QApplication | None = None


def _app() -> QApplication:
    global _APP
    existing = QApplication.instance()
    if existing is not None:
        return existing  # type: ignore[return-value]
    _APP = QApplication(["movie-scraper-tests"])
    return _APP


class FilmTypeSwitchUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _app()

    def setUp(self) -> None:
        app_module.set_config_path(None)
        self.win = MainWindow()

    def tearDown(self) -> None:
        self.win.close()
        self.win.deleteLater()
        app_module.set_config_path(None)

    def _type_row_buttons(self) -> list[QPushButton]:
        """PushButtons that sit in the film-type card row (not the card title)."""
        return [self.win.general_film_btn, self.win.other_film_btn]

    def test_layout_has_only_two_type_buttons_no_scraping_config_label(self) -> None:
        # Stray 「刮削配置」 must not appear as a sibling control beside the type buttons.
        parent = self.win.general_film_btn.parentWidget()
        self.assertIsNotNone(parent)
        labels = [
            w.text().strip()
            for w in parent.findChildren(QLabel)
            if w.text().strip() in {"刮削配置", "一般影片", "其他影片"}
        ]
        self.assertNotIn("刮削配置", labels)
        # Card title 「影片类型」 is fine; type buttons are exactly these two.
        self.assertEqual(
            [b.text() for b in self._type_row_buttons()],
            ["一般影片", "其他影片"],
        )
        # Exactly one of the two is checked
        self.assertEqual(
            int(self.win.general_film_btn.isChecked()) + int(self.win.other_film_btn.isChecked()),
            1,
        )

    def test_switch_a_then_b_then_a_restores_sites_and_rules(self) -> None:
        # Start on other (default), customize other, switch to general, customize,
        # switch back to other — other profile must be restored.
        if not self.win.other_film_btn.isChecked():
            self.win.other_film_btn.click()
        QApplication.processEvents()
        self.assertEqual(self.win._film_type, "other")

        self.win.location_edit.setText("actor+'/'+number-CUSTOM")
        self.win.naming_edit.setText("number+'-'+title-CUSTOM")
        self.win.translate_box.setChecked(True)
        # Flip first site enable state so order/content is distinctive
        other_sites_before = self.win._sites()
        self.assertTrue(other_sites_before)
        item0 = self.win.site_list.item(0)
        item0.setCheckState(item0.checkState())  # keep; rename via location is enough
        other_names = enabled_names(other_sites_before)

        self.win.general_film_btn.click()
        QApplication.processEvents()
        self.assertEqual(self.win._film_type, "general")
        self.assertTrue(self.win.general_film_btn.isChecked())
        general_names = enabled_names(self.win._sites())
        self.assertEqual(general_names[:2], ["tmdb", "imdb"])
        # general defaults should load (unless previously customized — first visit)
        self.assertIn("title.year", self.win.naming_edit.text())
        self.assertFalse(self.win.translate_box.isChecked())

        # Customize general so we can detect it was saved when leaving
        self.win.naming_edit.setText("title.year-GENERAL")
        self.win.location_edit.setText("genres+'/'+title-GENERAL")
        self.win.translate_box.setChecked(False)

        # Back to other — must restore CUSTOM other profile, not wipe it
        self.win.other_film_btn.click()
        QApplication.processEvents()
        self.assertEqual(self.win._film_type, "other")
        self.assertTrue(self.win.other_film_btn.isChecked())
        self.assertEqual(self.win.location_edit.text(), "actor+'/'+number-CUSTOM")
        self.assertEqual(self.win.naming_edit.text(), "number+'-'+title-CUSTOM")
        self.assertTrue(self.win.translate_box.isChecked())
        self.assertEqual(enabled_names(self.win._sites()), other_names)

        # And general must still be in cache for next switch
        self.win.general_film_btn.click()
        QApplication.processEvents()
        self.assertEqual(self.win.naming_edit.text(), "title.year-GENERAL")
        self.assertEqual(self.win.location_edit.text(), "genres+'/'+title-GENERAL")
        self.assertEqual(enabled_names(self.win._sites())[:2], ["tmdb", "imdb"])

    def test_selected_button_style_updates(self) -> None:
        self.win.general_film_btn.click()
        QApplication.processEvents()
        self.assertIn("#2563EB", self.win.general_film_btn.styleSheet())
        self.assertIn("background: white", self.win.other_film_btn.styleSheet())

        self.win.other_film_btn.click()
        QApplication.processEvents()
        self.assertIn("#2563EB", self.win.other_film_btn.styleSheet())
        self.assertIn("background: white", self.win.general_film_btn.styleSheet())


if __name__ == "__main__":
    unittest.main()
