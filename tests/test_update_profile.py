from datetime import date, timedelta
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import update_profile as profile


AS_OF = date(2026, 11, 24)


def calendar(counts=None):
    counts = counts or {}
    markup = []
    for offset in range(365):
        day = AS_OF - timedelta(days=offset)
        count = counts.get(offset, 0)
        label = "No contributions" if count == 0 else f"{count:,} contribution{'s' if count != 1 else ''}"
        markup.append(f'<td data-date="{day}" id="day-{offset}"></td>'
                      f'<tool-tip for="day-{offset}">{label} on November 24th.</tool-tip>')
    return "".join(markup)


class ProfileTests(unittest.TestCase):
    def test_calendar_order_and_counts(self):
        days = profile.parse_calendar(calendar({0: 1, 1: 1234}), AS_OF)
        self.assertEqual(len(days), 365)
        self.assertEqual(days[-2:], [(AS_OF - timedelta(days=1), 1234), (AS_OF, 1)])

    def test_streak_allows_today_to_be_unfinished(self):
        days = profile.parse_calendar(calendar({1: 2, 2: 3, 3: 1, 10: 1}), AS_OF)
        self.assertEqual(profile.streaks(days), (3, 3))

    def test_streak_includes_today(self):
        days = profile.parse_calendar(calendar({0: 2, 1: 3, 2: 1}), AS_OF)
        self.assertEqual(profile.streaks(days), (3, 3))

    def test_streak_resets_after_a_missed_day(self):
        days = profile.parse_calendar(calendar({2: 3, 3: 1}), AS_OF)
        self.assertEqual(profile.streaks(days), (0, 2))

    def test_empty_calendar_is_valid_but_not_missing_calendar(self):
        days = profile.parse_calendar(calendar(), AS_OF)
        self.assertEqual(profile.streaks(days), (0, 0))
        for document in ["<html>Sign in</html>", "<html>Too many requests</html>", ""]:
            with self.assertRaises(ValueError):
                profile.parse_calendar(document, AS_OF)

    def test_missing_or_changed_tooltip_is_rejected(self):
        document = calendar().replace("No contributions on November 24th.", "Activity unavailable", 1)
        with self.assertRaises(ValueError):
            profile.parse_calendar(document, AS_OF)

    def test_stale_calendar_is_rejected(self):
        with self.assertRaises(ValueError):
            profile.parse_calendar(calendar(), AS_OF + timedelta(days=1))

    def test_duplicate_dates_are_rejected(self):
        document = calendar() + f'<td data-date="{AS_OF}" id="copy"></td><tool-tip for="copy">1 contribution on November 24th.</tool-tip>'
        with self.assertRaises(ValueError):
            profile.parse_calendar(document, AS_OF)

    def test_render_zero_and_nonzero_charts_without_network_dependencies(self):
        for counts in [{}, {0: 1234, 1: 1, 2: 5}]:
            days = profile.parse_calendar(calendar(counts), AS_OF)
            for svg in [profile.summary_svg(days), profile.activity_svg(days)]:
                root = ET.fromstring(svg)
                self.assertEqual(root.tag, "{http://www.w3.org/2000/svg}svg")
                self.assertNotIn("<script", svg)
                self.assertNotIn("<image", svg)
                self.assertNotIn("NaN", svg)
                self.assertIn(str(AS_OF), svg)
        self.assertIn("No publicly visible contributions", profile.activity_svg(days=profile.parse_calendar(calendar(), AS_OF)))

    def test_successful_refresh_writes_both_cards(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            profile.update("yeahhbean", target, AS_OF, calendar({0: 1}))
            for name in ["stats.svg", "activity.svg"]:
                ET.parse(target / name)

    def test_invalid_payload_preserves_both_existing_cards(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for name in ["stats.svg", "activity.svg"]:
                (target / name).write_text("last good snapshot")
            with self.assertRaises(ValueError):
                profile.update("yeahhbean", target, AS_OF, "<html>Rate limit</html>")
            self.assertEqual([p.read_text() for p in target.iterdir()], ["last good snapshot"] * 2)

    def test_network_failure_preserves_existing_card(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            (target / "stats.svg").write_text("last good snapshot")
            error = HTTPError("https://github.com", 403, "Forbidden", {}, None)
            with patch.object(profile, "urlopen", side_effect=error), self.assertRaises(HTTPError):
                profile.update("yeahhbean", target, AS_OF)
            self.assertEqual((target / "stats.svg").read_text(), "last good snapshot")


if __name__ == "__main__":
    unittest.main()
