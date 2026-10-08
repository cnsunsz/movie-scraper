"""Source order and JavDB HTML parsing. No network."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scraper.javdb import first_video_path, matching_video_path, parse_detail_html, preview_stills
from scraper.javbus import parse_detail_html as parse_javbus
from scraper.match import accept_code
from scraper.imdb import ImdbError, _choose
from scraper.sources import normalize_sites
from scraper.nfo import render_nfo
from scraper.organize import movie_folder
from scraper.sources import resolve_priority
from scraper.translate import has_cjk
from scraper.imdb import MovieMetadata
from pathlib import Path as P


SEARCH_HTML = """
<div class="movie-list">
  <a href="/v/ABC12" class="box"><strong>SSNI-001</strong> Sample</a>
  <a href="/v/OTHER" class="box"><strong>SSND-001</strong> Other</a>
</div>
"""

DETAIL_HTML = """
<h2><strong class="current-title">示例标题</strong>
<span class="origin-title">Original Title</span></h2>
<img class="video-cover" src="https://img.example/cover.jpg" />
<div class="panel-block"><strong>番號:</strong><span class="value"><a>SSNI</a>-001</span></div>
<div class="panel-block"><strong>日期:</strong><span class="value">2017-09-25</span></div>
<div class="panel-block"><strong>時長:</strong><span class="value">160 分鍾</span></div>
<div class="panel-block"><strong>導演:</strong><span class="value"><a>Director X</a></span></div>
<div class="panel-block"><strong>片商:</strong><span class="value"><a>Studio A</a></span></div>
<div class="panel-block"><strong>發行:</strong><span class="value"><a>Label B</a></span></div>
<div class="panel-block"><strong>系列:</strong><span class="value"><a>Series C</a></span></div>
<div class="panel-block"><strong>類別:</strong><span class="value"><a>Tag1</a>, <a>Tag2</a></span></div>
<div class="panel-block"><strong>演員:</strong><span class="value"><a>Actor One</a>, <a>Actor Two</a></span></div>
<div class="panel-block"><strong>評分:</strong><span class="value">4.52分, 由10人評價</span></div>
<div class="preview-images">
  <a class="tile-item" href="https://img.example/still_l_0.jpg"><img src="https://img.example/still_s_0.jpg"></a>
  <a class="tile-item" href="https://img.example/still_l_1.jpg"><img src="https://img.example/still_s_1.jpg"></a>
</div>
"""


class PriorityTests(unittest.TestCase):
    def test_order_follows_text(self) -> None:
        enabled = {"javdb": True, "tmdb": True, "imdb": True}
        self.assertEqual(
            resolve_priority("imdb, tmdb, javdb", enabled),
            ["imdb", "tmdb", "javdb"],
        )

    def test_disabled_sources_are_skipped(self) -> None:
        enabled = {"javdb": False, "tmdb": True, "imdb": True}
        self.assertEqual(
            resolve_priority("javdb,imdb,tmdb", enabled),
            ["imdb", "tmdb"],
        )

    def test_unknown_and_duplicates_ignored(self) -> None:
        enabled = {"javdb": True, "tmdb": False, "imdb": True}
        self.assertEqual(
            resolve_priority("foo,imdb,imdb,javdb", enabled),
            ["imdb", "javdb"],
        )

    def test_blank_uses_default_and_skips_off(self) -> None:
        enabled = {"javdb": True, "tmdb": False, "imdb": True}
        self.assertEqual(resolve_priority("  ", enabled), ["javdb", "imdb"])


class JavdbParseTests(unittest.TestCase):
    def test_first_video_link(self) -> None:
        self.assertEqual(first_video_path(SEARCH_HTML), "/v/ABC12")

    def test_detail_fields_and_stills(self) -> None:
        movie = parse_detail_html(DETAIL_HTML, "https://javdb.com/v/ABC12")
        self.assertEqual(movie.title, "示例标题")
        self.assertEqual(movie.original_title, "Original Title")
        self.assertEqual(movie.code, "SSNI-001")
        self.assertEqual(movie.premiered, "2017-09-25")
        self.assertEqual(movie.runtime, "160")
        self.assertEqual(movie.directors, ["Director X"])
        self.assertEqual(movie.studio, "Studio A")
        self.assertEqual(movie.label, "Label B")
        self.assertEqual(movie.series, "Series C")
        self.assertEqual(movie.cast, ["Actor One", "Actor Two"])
        self.assertEqual(movie.tags[:2], ["Tag1", "Tag2"])
        self.assertEqual(movie.poster_url, "https://img.example/cover.jpg")
        self.assertEqual(movie.javdb_id, "ABC12")
        self.assertEqual(movie.source, "javdb")
        self.assertEqual(
            preview_stills(DETAIL_HTML),
            [
                "https://img.example/still_l_0.jpg",
                "https://img.example/still_l_1.jpg",
            ],
        )

    def test_nfo_shape_and_folder(self) -> None:
        movie = parse_detail_html(DETAIL_HTML, "https://javdb.com/v/ABC12")
        xml = render_nfo(movie, artwork={"poster": True, "thumb": True, "fanart": True})
        self.assertIn("<num>SSNI-001</num>", xml)
        self.assertIn("<poster>poster.jpg</poster>", xml)
        self.assertIn("<thumb>thumb.jpg</thumb>", xml)
        self.assertIn("<fanart>fanart.jpg</fanart>", xml)
        self.assertIn("<source>javdb</source>", xml)
        self.assertIn("<mpaa>JP-18+</mpaa>", xml)
        self.assertIn("<tag>Tag1</tag>", xml)
        self.assertIn("<genre>Tag1</genre>", xml)
        self.assertIn("<maker>Studio A</maker>", xml)
        self.assertIn("CDATA", xml)
        folder = movie_folder(P("/out"), movie)
        self.assertEqual(folder, P("/out") / "Actor One" / "SSNI-001")
        no_actor = MovieMetadata(title="Inception", year="2010")
        self.assertEqual(movie_folder(P("/out"), no_actor), P("/out") / "Inception")

    def test_has_cjk(self) -> None:
        self.assertFalse(has_cjk("A thief who steals secrets."))
        self.assertTrue(has_cjk("中文简介"))


if __name__ == "__main__":
    unittest.main()


JAVBUS_HTML = """
<h3>SSNI-001 示例标题</h3>
<p><span class="header">識別碼:</span> <span style="color:#CC0000;">SSNI-001</span></p>
<p><span class="header">發行日期:</span> 2017-09-17</p>
<div class="star-box"><li><a><img src="/pics/actress/nj9_a.jpg"></a><div class="star-name"><a>葵</a></div></li></div>
"""


class StrictMatchTests(unittest.TestCase):
    def test_imdb_year_must_match(self) -> None:
        metas = [
            {"name": "Triple Threat", "year": "2019", "id": "tt6643972", "type": "movie"},
            {"name": "Triple Threat", "year": "2026", "id": "tt43311780", "type": "movie"},
        ]
        chosen = _choose(metas, "Triple Threat", "2026")
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen["id"], "tt43311780")
        self.assertIsNone(_choose([metas[0]], "Triple Threat", "2026"))

    def test_imdb_refuses_to_guess_without_year(self) -> None:
        metas = [
            {"name": "Triple Threat", "year": "2019", "id": "tt6643972", "type": "movie"},
            {"name": "Triple Threat!", "year": "2026", "id": "tt43311780", "type": "movie"},
        ]
        with self.assertRaises(ImdbError) as caught:
            _choose(metas, "Triple Threat", None)
        self.assertIn("有多部同名，文件名里没有年份", str(caught.exception))

    def test_javdb_code_mismatch_is_rejected(self) -> None:
        movie = parse_detail_html(DETAIL_HTML, "https://javdb.com/v/ABC12")
        self.assertIsNone(accept_code(movie, "SSND-001"))
        self.assertEqual(accept_code(movie, "ssni 001").code, "SSNI-001")
        swapped = """
        <div class="movie-list">
          <a href="/v/WRONG" class="box"><strong>SSND-001</strong></a>
          <a href="/v/RIGHT" class="box"><strong>SSNI-001</strong></a>
        </div>
        """
        self.assertEqual(matching_video_path(swapped, "SSNI-001"), "/v/RIGHT")
        self.assertIsNone(matching_video_path(swapped, "IPX-001"))

    def test_javbus_code_mismatch_is_rejected(self) -> None:
        movie = parse_javbus(JAVBUS_HTML)
        self.assertEqual(movie.code, "SSNI-001")
        self.assertEqual(movie.cast, ["葵"])
        self.assertTrue(movie.actor_photos["葵"].endswith("nj9_a.jpg"))
        self.assertIsNone(accept_code(movie, "SSND-001"))
        self.assertEqual(accept_code(movie, "ssni-001").title, "示例标题")

    def test_sites_migrate_old_priority(self) -> None:
        sites = normalize_sites(None, {"javdb": False, "tmdb": True, "imdb": True}, "imdb,javdb,tmdb")
        names = [item["name"] for item in sites]
        self.assertEqual(names[:3], ["imdb", "javdb", "tmdb"])
        enabled = {item["name"]: item["enabled"] for item in sites}
        self.assertFalse(enabled["javdb"])
        self.assertTrue(enabled["imdb"])
        self.assertFalse(enabled["dmm"])
