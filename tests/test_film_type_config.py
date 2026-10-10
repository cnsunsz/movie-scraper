"""Film type config migrate, naming rules, per-mode site defaults."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
from scraper.imdb import MovieMetadata
from scraper.naming import eval_rule, rule_values
from scraper.organize import movie_folder, video_filename
from scraper.sources import default_sites, enabled_names, normalize_sites


class NamingRuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.meta = MovieMetadata(
            title="Inception",
            year="2010",
            code="SSNI-001",
            cast=["葵"],
            genres=["Action"],
        )
        self.values = rule_values(self.meta)

    def test_actor_slash_title(self) -> None:
        self.assertEqual(eval_rule("actor+'/'+title", self.values), "葵/Inception")

    def test_number_dash_title(self) -> None:
        self.assertEqual(eval_rule("number+'-'+title", self.values), "SSNI-001-Inception")

    def test_title_year_shorthand(self) -> None:
        self.assertEqual(eval_rule("title.year", self.values), "Inception.2010")

    def test_genres_slash_title(self) -> None:
        self.assertEqual(eval_rule("genres+'/'+title", self.values), "Action/Inception")

    def test_double_quotes(self) -> None:
        self.assertEqual(eval_rule('number+"-"+title', self.values), "SSNI-001-Inception")

    def test_rejects_eval_injection(self) -> None:
        self.assertEqual(eval_rule("__import__('os').system('x')", self.values), "未知")

    def test_video_filename_uses_rule(self) -> None:
        name = video_filename(
            Path("x.mkv"),
            self.meta,
            naming_rule="title.year",
        )
        self.assertEqual(name, "Inception.2010.mkv")

    def test_movie_folder_uses_rule(self) -> None:
        folder = movie_folder(
            Path("/out"),
            self.meta,
            location_rule="genres+'/'+title",
        )
        self.assertEqual(folder, Path("/out") / "Action" / "Inception")

    def test_shorthand_slash_and_brackets(self) -> None:
        self.assertEqual(eval_rule("genres/title", self.values), "Action/Inception")
        self.assertEqual(eval_rule("actor/[number]-title", self.values), "葵/[SSNI-001]-Inception")

    def test_expanded_tokens(self) -> None:
        self.meta.studio = "StudioX"
        self.meta.directors = ["Dir"]
        self.meta.premiered = "2010-01-02"
        values = rule_values(self.meta, suffix="mkv")
        self.assertEqual(values["studio"], "StudioX")
        self.assertEqual(values["director"], "Dir")
        self.assertEqual(values["prefix"], "SSNI")
        self.assertEqual(values["letter"], "S")
        self.assertEqual(values["suffix"], "mkv")
        self.assertEqual(eval_rule("studio+'/'+number", values), "StudioX/SSNI-001")


class SiteDefaultsByFilmTypeTests(unittest.TestCase):
    def test_general_prefers_tmdb_imdb(self) -> None:
        sites = default_sites("general")
        names = enabled_names(sites)
        self.assertEqual(names[:2], ["tmdb", "imdb"])
        self.assertNotIn("javdb", names)
        self.assertNotIn("javbus", names)

    def test_other_keeps_jav_defaults(self) -> None:
        sites = default_sites("other")
        names = enabled_names(sites)
        self.assertEqual(names[:2], ["javdb", "javbus"])
        self.assertIn("tmdb", names)
        self.assertIn("imdb", names)

    def test_normalize_preserves_order_per_type(self) -> None:
        general = normalize_sites(
            [{"name": "imdb", "enabled": True}, {"name": "tmdb", "enabled": True}],
            film_type="general",
        )
        self.assertEqual([item["name"] for item in general][:2], ["imdb", "tmdb"])


class ConfigMigrateTests(unittest.TestCase):
    def tearDown(self) -> None:
        app_module.set_config_path(None)

    def test_flat_config_migrates_into_other(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "media_dir": str(root / "media"),
                        "output_dir": str(root / "out"),
                        "output_mode": "folder",
                        "sites": [
                            {"name": "javbus", "enabled": True},
                            {"name": "javdb", "enabled": False},
                            {"name": "tmdb", "enabled": True},
                            {"name": "imdb", "enabled": True},
                        ],
                        "tmdb_key": "secret-key",
                        "proxy": "http://127.0.0.1:7890",
                        "proxy_enabled": True,
                        "skip_existing_nfo": False,
                        "translate_plot": False,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            loaded = app_module.load_config_from(config_path)
            self.assertEqual(loaded["film_type"], "other")
            self.assertEqual(loaded["main_mode"], "1")
            self.assertIn("general", loaded)
            self.assertIn("other", loaded)
            other_sites = {item["name"]: item["enabled"] for item in loaded["other"]["sites"]}
            self.assertTrue(other_sites["javbus"])
            self.assertFalse(other_sites["javdb"])
            general_enabled = enabled_names(loaded["general"]["sites"])
            self.assertEqual(general_enabled[:2], ["tmdb", "imdb"])
            self.assertEqual(loaded["tmdb_key"], "secret-key")
            self.assertFalse(loaded["skip_existing_nfo"])
            self.assertEqual(loaded["sites"][0]["name"], "javbus")

            out = root / "saved.json"
            app_module.save_config(
                {
                    "film_type": "general",
                    "media_dir": str(root / "media2"),
                    "main_mode": "4",
                    "general": loaded["general"],
                    "other": loaded["other"],
                },
                out,
            )
            again = app_module.load_config_from(out)
            raw = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(again["film_type"], "general")
        self.assertEqual(again["media_dir"], str(root / "media2"))
        self.assertEqual(again["main_mode"], "4")
        self.assertIn("general", raw)
        self.assertIn("other", raw)
        self.assertNotIn("javdb_cookie", raw)
        other_names = [item["name"] for item in raw["other"]["sites"]]
        self.assertEqual(other_names[0], "javbus")

    def test_round_trip_nested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config.json"
            app_module.save_config(
                {
                    "film_type": "general",
                    "media_dir": str(root / "m"),
                    "output_dir": str(root / "o"),
                    "main_mode": "1",
                    "tmdb_key": "k",
                    "proxy": "http://127.0.0.1:1",
                    "proxy_enabled": True,
                    "general": {
                        "sites": default_sites("general"),
                        "location_rule": "genres+'/'+title",
                        "naming_rule": "title.year",
                        "translate_plot": False,
                    },
                    "other": {
                        "sites": default_sites("other"),
                        "location_rule": "actor+'/'+number",
                        "naming_rule": "number+'-'+title",
                        "translate_plot": True,
                        "tpdb_token": "",
                    },
                },
                config_path,
            )
            loaded = app_module.load_config_from(config_path)
        self.assertEqual(loaded["film_type"], "general")
        self.assertEqual(loaded["general"]["naming_rule"], "title.year")
        self.assertEqual(loaded["other"]["naming_rule"], "number+'-'+title")
        self.assertEqual(enabled_names(loaded["sites"])[:2], ["tmdb", "imdb"])
        self.assertEqual(loaded["main_mode"], "1")


if __name__ == "__main__":
    unittest.main()
