"""Emby/Jellyfin URL helpers. No network."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scraper.emby_actors import _lookup_avatar, _persons_url, _primary_image_url


class EmbyActorsTests(unittest.TestCase):
    def test_persons_url_emby(self) -> None:
        url = _persons_url("emby", "http://host:8096", "abc", "", limit=1)
        self.assertIn("/emby/Persons?", url)
        self.assertIn("api_key=abc", url)
        self.assertIn("Limit=1", url)

    def test_persons_url_jellyfin_user(self) -> None:
        url = _persons_url("jellyfin", "http://host:8096/", "k", "uid")
        self.assertIn("/Persons?", url)
        self.assertNotIn("/emby/", url)
        self.assertIn("userid=uid", url)

    def test_primary_image_url(self) -> None:
        emby = _primary_image_url("emby", "http://h", "42", "key")
        jelly = _primary_image_url("jellyfin", "http://h", "42", "key")
        self.assertIn("/emby/Items/42/Images/Primary", emby)
        self.assertIn("/Items/42/Images/Primary", jelly)
        self.assertNotIn("/emby/", jelly)

    def test_lookup_avatar(self) -> None:
        mapping = {"Alice.jpg": "http://x/a.jpg", "Bob.png": "/tmp/b.png"}
        self.assertEqual(_lookup_avatar("Alice", mapping), "http://x/a.jpg")
        self.assertEqual(_lookup_avatar("Bob", mapping), "/tmp/b.png")
        self.assertIsNone(_lookup_avatar("Missing", mapping))


if __name__ == "__main__":
    unittest.main()
