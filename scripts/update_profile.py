#!/usr/bin/env python3
"""Generate profile cards from GitHub's public calendar, without third-party APIs.

Fetch and validate the complete calendar before writing either SVG. A failed
refresh exits nonzero and leaves the previous committed images available.
"""

import argparse
from datetime import date, datetime, timedelta, timezone
from html import escape
from html.parser import HTMLParser
from pathlib import Path
import re
import sys
from urllib.request import Request, urlopen


class CalendarParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.dates = {}
        self.tooltips = {}
        self.target = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "td" and "data-date" in attrs:
            self.dates[attrs["id"]] = date.fromisoformat(attrs["data-date"])
        if tag == "tool-tip":
            self.target = attrs.get("for")
            if self.target:
                self.tooltips[self.target] = ""

    def handle_data(self, data):
        if self.target:
            self.tooltips[self.target] += data

    def handle_endtag(self, tag):
        if tag == "tool-tip":
            self.target = None


def parse_calendar(document, as_of):
    parser = CalendarParser()
    parser.feed(document)
    counts = {}
    for target, day in parser.dates.items():
        text = " ".join(parser.tooltips.get(target, "").split())
        match = re.match(r"^(No|[0-9][0-9,]*) contributions? on .+\.$", text)
        if not match:
            raise ValueError(f"Missing or unrecognized contribution count for {day}")
        if day in counts:
            raise ValueError(f"Duplicate contribution day: {day}")
        counts[day] = 0 if match[1] == "No" else int(match[1].replace(",", ""))

    # Do not turn a login page, rate-limit response, stale calendar, or changed
    # markup into an apparently valid zero-activity chart.
    days = [as_of - timedelta(days=offset) for offset in reversed(range(365))]
    if any(day not in counts for day in days):
        raise ValueError("GitHub did not return the complete current 365-day calendar")
    return [(day, counts[day]) for day in days]


def streaks(days):
    longest = run = 0
    for _, count in days:
        run = run + 1 if count else 0
        longest = max(longest, run)
    # An unfinished UTC day does not end yesterday's streak.
    current = 0
    end = len(days) if days[-1][1] else len(days) - 1
    for _, count in reversed(days[:end]):
        if not count:
            break
        current += 1
    return current, longest


def svg_card(height, title, description, content):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="760" height="{height}" '
        f'viewBox="0 0 760 {height}" role="img" aria-labelledby="title desc">\n'
        f'<title id="title">{escape(title)}</title>\n'
        f'<desc id="desc">{escape(description)}</desc>\n'
        f'<rect width="760" height="{height}" rx="8" fill="#0D1117"/>\n'
        '<g font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif">\n'
        + content + '\n</g>\n</svg>\n'
    )


def summary_svg(days):
    current, longest = streaks(days)
    total = sum(count for _, count in days)
    start, end = days[0][0], days[-1][0]
    content = '<text x="28" y="34" fill="#C7D2FE" font-size="17" font-weight="600">GitHub contributions</text>\n'
    for x, value, label in [(143, total, "Past 365 days"),
                             (380, current, "Current streak (days)"),
                             (617, longest, "Longest streak in period")]:
        content += (
            f'<text x="{x}" y="91" text-anchor="middle" fill="#A78BFA" '
            f'font-size="34" font-weight="700">{value:,}</text>\n'
            f'<text x="{x}" y="120" text-anchor="middle" fill="#A5B4FC" '
            f'font-size="13">{label}</text>\n'
        )
    content += (
        f'<text x="380" y="163" text-anchor="middle" fill="#8B949E" '
        f'font-size="12">{start.isoformat()} to {end.isoformat()} · UTC · Public profile calendar</text>'
    )
    return svg_card(184, "GitHub contribution summary",
                    f"{total} contributions from {start} to {end}. Current streak: {current} days. "
                    f"Longest streak within this period: {longest} days.", content)


def activity_svg(days):
    days = days[-31:]
    maximum = max(1, max(count for _, count in days))
    content = '<text x="28" y="34" fill="#C7D2FE" font-size="17" font-weight="600">Recent activity · 31 days</text>\n'
    for numerator in range(5):
        y = 64 + numerator * 26
        content += f'<path d="M48 {y}H732" stroke="#21262D"/>\n'
    points = []
    for index, (day, count) in enumerate(days):
        x = 48 + index * 22.8
        y = 168 - count / maximum * 104
        points.append(f"{x:.1f},{y:.1f}")
        content += (
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="#A78BFA">'
            f'<title>{day.isoformat()}: {count} contributions</title></circle>\n'
        )
        if index % 5 == 0:
            content += (f'<text x="{x:.1f}" y="193" text-anchor="middle" '
                        f'fill="#8B949E" font-size="11">{day.strftime("%m-%d")}</text>\n')
    content += f'<polyline points="{" ".join(points)}" fill="none" stroke="#6366F1" stroke-width="2"/>\n'
    content += f'<text x="36" y="68" text-anchor="end" fill="#8B949E" font-size="11">{maximum:,}</text>\n'
    content += '<text x="36" y="172" text-anchor="end" fill="#8B949E" font-size="11">0</text>\n'
    if not any(count for _, count in days):
        content += ('<text x="390" y="117" text-anchor="middle" fill="#8B949E" '
                    'font-size="14">No publicly visible contributions in this period</text>\n')
    content += (f'<text x="380" y="224" text-anchor="middle" fill="#8B949E" font-size="12">'
                f'{days[0][0].isoformat()} to {days[-1][0].isoformat()} · UTC · Public profile calendar</text>')
    return svg_card(246, "GitHub contributions over the past 31 days",
                    "; ".join(f"{day}: {count}" for day, count in days), content)


def update(username, output_dir, as_of, document=None):
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", username):
        raise ValueError("Invalid GitHub username")
    if document is None:
        request = Request(
            f"https://github.com/users/{username}/contributions",
            headers={"User-Agent": "github-profile-cards", "Accept-Language": "en-US"},
        )
        with urlopen(request, timeout=30) as response:
            if response.headers.get_content_type() != "text/html":
                raise ValueError("GitHub returned an unexpected content type")
            document = response.read().decode("utf-8")
    days = parse_calendar(document, as_of)
    cards = {"stats.svg": summary_svg(days), "activity.svg": activity_svg(days)}
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in cards.items():
        temporary = output_dir / f".{name}.tmp"
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(output_dir / name)
    return days


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", default="yeahhbean")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parents[1] / "profile")
    parser.add_argument("--as-of", type=date.fromisoformat, default=datetime.now(timezone.utc).date())
    args = parser.parse_args()
    try:
        days = update(args.username, args.output_dir, args.as_of)
    except (OSError, ValueError) as error:
        print(f"Profile refresh failed; existing cards retained: {error}", file=sys.stderr)
        return 1
    print(f"Generated cards for {args.username} through {days[-1][0]} from GitHub's public calendar")
    return 0


if __name__ == "__main__":
    sys.exit(main())
