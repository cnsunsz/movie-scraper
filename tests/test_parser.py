"""Filename parser tests. Run: python3 -m unittest tests/test_parser.py"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scraper.parser import parse_filename


class ParserTests(unittest.TestCase):
    def test_title_with_year_and_resolution(self) -> None:
        parsed = parse_filename("Inception 2010 1080p.mkv")
        self.assertIsNone(parsed.imdb_id)
        self.assertIsNone(parsed.code)
        self.assertEqual(parsed.title, "Inception 2010")
        self.assertEqual(parsed.year, "2010")

    def test_imdb_id_only(self) -> None:
        parsed = parse_filename("tt1375666.mkv")
        self.assertEqual(parsed.imdb_id, "tt1375666")
        self.assertIsNone(parsed.code)
        self.assertEqual(parsed.title, "")

    def test_imdb_id_case_and_eight_digits(self) -> None:
        parsed = parse_filename("Movie.TT01330938.1080p.mkv")
        self.assertEqual(parsed.imdb_id, "tt01330938")
        self.assertEqual(parsed.title, "Movie")

    def test_imdb_id_not_prefix_of_longer_number(self) -> None:
        parsed = parse_filename("tt137566619.mkv")
        self.assertIsNone(parsed.imdb_id)

    def test_imdb_inside_dotted_name(self) -> None:
        parsed = parse_filename("The.Matrix.tt0133093.1999.1080p.BluRay.mkv")
        self.assertEqual(parsed.imdb_id, "tt0133093")
        self.assertIsNone(parsed.code)
        self.assertEqual(parsed.title, "The Matrix 1999")
        self.assertEqual(parsed.year, "1999")

    def test_hyphen_code_keeps_padding(self) -> None:
        parsed = parse_filename("SSNI-001.mkv")
        self.assertEqual(parsed.code, "SSNI-001")
        self.assertIsNone(parsed.imdb_id)
        self.assertEqual(parsed.title, "")

    def test_glued_code_drops_leading_zeros(self) -> None:
        parsed = parse_filename("ssni00123.mkv")
        self.assertEqual(parsed.code, "SSNI-123")
        self.assertEqual(parsed.title, "")

    def test_glued_code_keeps_at_least_three_digits(self) -> None:
        self.assertEqual(parse_filename("ssni0001.mkv").code, "SSNI-001")
        self.assertEqual(parse_filename("ab001.mkv").code, "AB-001")

    def test_unpadded_glued_number_is_not_a_code(self) -> None:
        parsed = parse_filename("ssni1000.mkv")
        self.assertIsNone(parsed.code)
        self.assertEqual(parsed.title, "ssni1000")

    def test_fc2_ppv_and_fc2(self) -> None:
        self.assertEqual(parse_filename("FC2-PPV-123456.mp4").code, "FC2-PPV-123456")
        self.assertEqual(parse_filename("fc2ppv-1234567.mkv").code, "FC2-PPV-1234567")
        self.assertEqual(parse_filename("FC2-123456.mkv").code, "FC2-123456")

    def test_heyzo(self) -> None:
        self.assertEqual(parse_filename("HEYZO-1234.mkv").code, "HEYZO-1234")
        self.assertEqual(parse_filename("heyzo_0123.avi").code, "HEYZO-0123")

    def test_tokyo_hot_and_bare_n(self) -> None:
        self.assertEqual(parse_filename("Tokyo-Hot-n1234.mkv").code, "n1234")
        self.assertEqual(parse_filename("tokyo hot n0651.wmv").code, "n0651")
        parsed = parse_filename("n1234.avi")
        self.assertEqual(parsed.code, "n1234")
        self.assertEqual(parsed.title, "")

    def test_standard_code_length_bounds(self) -> None:
        self.assertEqual(parse_filename("AB-12.mkv").code, "AB-12")
        self.assertEqual(parse_filename("ABCDEFGHIJ-12345.mkv").code, "ABCDEFGHIJ-12345")
        self.assertIsNone(parse_filename("A-123.mkv").code)
        self.assertIsNone(parse_filename("ABCDEFGHIJK-12.mkv").code)

    def test_cd_and_part_are_not_part_of_the_id(self) -> None:
        cd = parse_filename("ABC-123-CD1.mkv")
        self.assertEqual(cd.code, "ABC-123")
        self.assertNotIn("CD", cd.title.upper())
        part = parse_filename("ABC-1234-part2.mkv")
        self.assertEqual(part.code, "ABC-1234")
        self.assertEqual(part.title, "")
        loose = parse_filename("Pretty.Movie-cd1.mkv")
        self.assertIsNone(loose.code)
        self.assertEqual(loose.title, "Pretty Movie")

    def test_code_plus_title(self) -> None:
        parsed = parse_filename("ABC-123 漂亮的标题 1080p.mkv")
        self.assertEqual(parsed.code, "ABC-123")
        self.assertEqual(parsed.title, "漂亮的标题")

    def test_junk_tokens_and_chinese_subtitle_tag(self) -> None:
        parsed = parse_filename("The.Matrix.1999.1080p.BluRay.x264-中字幕.mkv")
        self.assertIsNone(parsed.code)
        self.assertEqual(parsed.title, "The Matrix 1999")
        web = parse_filename("Dune.2021.2160p.WEB-DL.HEVC.4K.mkv")
        self.assertEqual(web.title, "Dune 2021")
        self.assertIsNone(web.code)
        self.assertEqual(web.year, "2021")

    def test_subtitle_c_tag_not_abbreviation(self) -> None:
        self.assertEqual(parse_filename("Some.Movie.c.mkv").title, "Some Movie")
        self.assertEqual(parse_filename("Some.Movie.2010.1080p-C.mkv").title, "Some Movie 2010")
        abbreviated = parse_filename("C.R.A.Z.Y.2005.mkv")
        self.assertIn("C", abbreviated.title)
        self.assertIn("R", abbreviated.title)
        self.assertIn("2005", abbreviated.title)
        self.assertNotIn("1080", abbreviated.title)

    def test_hyphenated_title_with_year_is_not_a_code(self) -> None:
        parsed = parse_filename("Inception-2010.mkv")
        self.assertIsNone(parsed.code)
        self.assertEqual(parsed.title, "Inception 2010")
        knight = parse_filename("The-Dark-Knight-2008-1080p.mkv")
        self.assertIsNone(knight.code)
        self.assertEqual(knight.title, "The Dark Knight 2008")

    def test_codec_is_not_a_code(self) -> None:
        parsed = parse_filename("Some Movie x264.mkv")
        self.assertIsNone(parsed.code)
        self.assertEqual(parsed.title, "Some Movie")

    def test_path_and_extension_case(self) -> None:
        parsed = parse_filename(r"D:\films\SSNI-001.MKV")
        self.assertEqual(parsed.code, "SSNI-001")


if __name__ == "__main__":
    unittest.main()
