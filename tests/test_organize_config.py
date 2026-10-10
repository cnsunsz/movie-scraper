"""Organize helpers, config round-trip, emby URL, proxy. No network."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as app_module
from scraper.emby_actors import _normalize_server_base, _persons_url, _primary_image_url
from scraper.imdb import MovieMetadata
from scraper.net import classify_proxy
from scraper.organize import (
    list_videos,
    movie_folder,
    scrape_one,
    sanitize_folder_name,
    video_filename,
    _actor_filename,
)
from scraper.sources import enabled_names, normalize_sites


class VideoNamingTests(unittest.TestCase):
    def test_video_filename_avoids_duplicate_code(self) -> None:
        meta = MovieMetadata(title="SSNI-001 示例", code="SSNI-001")
        name = video_filename(Path("clip.mkv"), meta)
        self.assertTrue(name.startswith("SSNI-001"))
        self.assertEqual(name.count("SSNI-001"), 1)
        self.assertTrue(name.endswith(".mkv"))

    def test_video_filename_prefixes_code(self) -> None:
        meta = MovieMetadata(title="漂亮的标题", code="ABC-123")
        self.assertEqual(video_filename(Path("x.mp4"), meta), "ABC-123-漂亮的标题.mp4")

    def test_movie_folder_actor_and_code(self) -> None:
        meta = MovieMetadata(title="标题", code="SSNI-001", cast=["葵"])
        self.assertEqual(movie_folder(Path("/out"), meta), Path("/out") / "葵" / "SSNI-001")
        bare = MovieMetadata(title="Inception", year="2010")
        self.assertEqual(movie_folder(Path("/out"), bare), Path("/out") / "Inception")

    def test_sanitize_strips_invalid_chars(self) -> None:
        self.assertEqual(sanitize_folder_name('a/b:c*?"<>|d'), "a b c d")
        self.assertEqual(sanitize_folder_name("Title", "2010"), "Title (2010)")

    def test_actor_filename_collision_gets_suffix(self) -> None:
        used: set[str] = set()
        first = _actor_filename("Alice", "http://x/a.jpg", used)
        second = _actor_filename("Alice", "http://x/b.jpg", used)
        self.assertEqual(first, "Alice.jpg")
        self.assertEqual(second, "Alice (2).jpg")
        self.assertIn(first, used)
        self.assertIn(second, used)


class SiteOrderTests(unittest.TestCase):
    def test_enabled_names_follow_list_order(self) -> None:
        sites = normalize_sites(
            [
                {"name": "imdb", "enabled": True},
                {"name": "javdb", "enabled": True},
                {"name": "tmdb", "enabled": False},
            ]
        )
        self.assertEqual(enabled_names(sites)[:2], ["imdb", "javdb"])
        self.assertNotIn("tmdb", enabled_names(sites))


class ConfigRoundTripTests(unittest.TestCase):
    def tearDown(self) -> None:
        app_module.set_config_path(None)

    def test_default_config_does_not_touch_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app_module.set_config_path(None)
            cfg = app_module.default_config()
            self.assertEqual(cfg["main_mode"], "4")
            self.assertFalse((root / "config.json").exists())
            # load_config with no path returns defaults, no write
            loaded = app_module.load_config()
            self.assertEqual(loaded["main_mode"], "4")
            self.assertIsNone(app_module.get_config_path())

    def test_save_requires_explicit_path(self) -> None:
        app_module.set_config_path(None)
        with self.assertRaises(OSError):
            app_module.save_config({"media_dir": "/x"})

    def test_load_save_keeps_new_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config.json"
            app_module.set_config_path(None)
            app_module.save_config(
                {
                    "media_dir": str(root / "media"),
                    "output_dir": str(root / "out"),
                    "main_mode": "1",
                    "sites": [
                        {"name": "javbus", "enabled": True},
                        {"name": "javdb", "enabled": False},
                    ],
                    "tmdb_key": "secret-key",
                    "proxy": "http://127.0.0.1:7890",
                    "proxy_enabled": True,
                    "skip_existing_nfo": False,
                    "translate_plot": False,
                    "anonymous_fill": True,
                    "actor_only_tag": True,
                    "emby_type": "jellyfin",
                    "emby_url": "http://127.0.0.1:8096",
                    "emby_api_key": "emby-secret",
                    "emby_user_id": "uid",
                    "actor_avatar_source": "local",
                    "actor_local_dir": str(root / "faces"),
                },
                config_path,
            )
            loaded = app_module.load_config_from(config_path)
            raw = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(loaded["main_mode"], "1")
        self.assertEqual(loaded["output_mode"], "folder")
        self.assertTrue(loaded["proxy_enabled"])
        self.assertEqual(loaded["proxy"], "http://127.0.0.1:7890")
        self.assertEqual(loaded["tmdb_key"], "secret-key")
        self.assertEqual(loaded["emby_type"], "jellyfin")
        self.assertEqual(loaded["emby_api_key"], "emby-secret")
        self.assertEqual(loaded["actor_avatar_source"], "local")
        self.assertFalse(loaded["skip_existing_nfo"])
        self.assertFalse(loaded["translate_plot"])
        self.assertTrue(loaded["anonymous_fill"])
        self.assertTrue(loaded["actor_only_tag"])
        names = [item["name"] for item in loaded["sites"]]
        self.assertEqual(names[0], "javbus")
        enabled = {item["name"]: item["enabled"] for item in loaded["sites"]}
        self.assertTrue(enabled["javbus"])
        self.assertFalse(enabled["javdb"])
        self.assertEqual(raw["emby_api_key"], "emby-secret")
        self.assertEqual(raw["main_mode"], "1")
        self.assertNotIn("javdb_cookie", raw)

    def test_atomic_save_and_migrate_output_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy.json"
            legacy.write_text(
                json.dumps({"output_mode": "folder", "media_dir": str(root / "m"), "film_type": "other"}),
                encoding="utf-8",
            )
            loaded = app_module.load_config_from(legacy)
            self.assertEqual(loaded["main_mode"], "1")
            out = root / "out.json"
            app_module.save_config(loaded, out)
            raw = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(raw["main_mode"], "1")
            self.assertIn("general", raw)
            self.assertIn("other", raw)

    def test_effective_proxy_respects_toggle(self) -> None:
        self.assertEqual(
            app_module.effective_proxy({"proxy_enabled": False, "proxy": "http://x:1"}),
            "",
        )
        self.assertEqual(
            app_module.effective_proxy({"proxy_enabled": True, "proxy": " http://x:1 "}),
            "http://x:1",
        )

    def test_version_file_readable(self) -> None:
        self.assertRegex(app_module.__version__, r"^\d+\.\d+\.\d+")
        version_file = Path(__file__).resolve().parents[1] / "VERSION"
        self.assertEqual(version_file.read_text(encoding="utf-8").strip(), app_module.__version__)


class EmbyUrlTests(unittest.TestCase):
    def test_strips_trailing_emby_segment(self) -> None:
        self.assertEqual(_normalize_server_base("emby", "http://h:8096/emby"), "http://h:8096")
        self.assertEqual(_normalize_server_base("emby", "http://h:8096/emby/"), "http://h:8096")
        url = _persons_url("emby", "http://h:8096/emby", "k", "")
        self.assertIn("/emby/Persons?", url)
        self.assertNotIn("/emby/emby/", url)
        primary = _primary_image_url("jellyfin", "http://h:8096/jellyfin", "42", "k")
        self.assertIn("/Items/42/Images/Primary", primary)
        self.assertNotIn("/jellyfin/Items", primary)

    def test_plain_base_unchanged(self) -> None:
        url = _persons_url("emby", "http://h:8096", "abc", "", limit=1)
        self.assertTrue(url.startswith("http://h:8096/emby/Persons?"))


class ProxyClassifyTests(unittest.TestCase):
    def test_host_port_gets_http_scheme(self) -> None:
        url, warning = classify_proxy("127.0.0.1:7890")
        self.assertEqual(url, "http://127.0.0.1:7890")
        self.assertIsNone(warning)

    def test_socks_rejected(self) -> None:
        url, warning = classify_proxy("socks5://127.0.0.1:1080")
        self.assertIsNone(url)
        self.assertIn("socks", warning.lower())


class ScrapeOneEdgeTests(unittest.TestCase):
    def test_missing_file_logs_and_returns(self) -> None:
        logs: list[str] = []
        scrape_one(
            Path("/no/such/video.mkv"),
            mode="beside",
            output_dir=None,
            sources={"sites": [], "skip_existing_nfo": False, "translate_plot": False},
            stop_check=lambda: False,
            log=logs.append,
        )
        self.assertTrue(any("文件不存在" in line for line in logs))

    def test_folder_mode_requires_output(self) -> None:
        logs: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "SSNI-001.mkv"
            video.write_bytes(b"x")
            scrape_one(
                video,
                mode="folder",
                output_dir=None,
                sources={"sites": [], "skip_existing_nfo": False, "translate_plot": False},
                stop_check=lambda: False,
                log=logs.append,
            )
        self.assertTrue(any("输出目录" in line or "主运行模式" in line for line in logs))

    def test_list_videos_skips_failed_and_actors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ok.mkv").write_bytes(b"1")
            (root / "failed").mkdir()
            (root / "failed" / "no.mkv").write_bytes(b"1")
            (root / ".actors").mkdir()
            (root / ".actors" / "face.mkv").write_bytes(b"1")
            found = list_videos(root)
            self.assertEqual([p.name for p in found], ["ok.mkv"])


class DestinationExistsTests(unittest.TestCase):
    def test_folder_mode_does_not_overwrite_existing_destination(self) -> None:
        logs: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = root / "media"
            out = root / "out"
            media.mkdir()
            out.mkdir()
            src = media / "SSNI-001.mkv"
            src.write_bytes(b"src")
            # Pretend a previous run already placed a file at the destination name.
            dest_dir = out / "SSNI-001"
            dest_dir.mkdir()
            existing = dest_dir / "SSNI-001.mkv"
            existing.write_bytes(b"old")
            scrape_one(
                src,
                mode="folder",
                output_dir=out,
                sources={
                    "sites": [
                        {"name": name, "enabled": False}
                        for name in (
                            "javdb", "javbus", "tmdb", "imdb",
                            "dmm", "avsox", "mgstage", "fc2",
                        )
                    ],
                    "skip_existing_nfo": False,
                    "translate_plot": False,
                    "anonymous_fill": False,
                    "location_rule": "number",
                    "naming_rule": "number",
                },
                stop_check=lambda: False,
                log=logs.append,
            )
            self.assertTrue(src.exists(), "source must stay when destination exists")
            self.assertEqual(existing.read_bytes(), b"old")
            self.assertFalse((dest_dir / "SSNI-001.nfo").exists())
            self.assertTrue(any("目标已存在" in line for line in logs))


if __name__ == "__main__":
    unittest.main()
