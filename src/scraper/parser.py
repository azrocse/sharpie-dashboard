"""Parser estructurado para Betting Splits de DraftKings Network."""

from __future__ import annotations

import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bs4 import BeautifulSoup


ODDS_PATTERN = re.compile(
    r"(?<!\d)([+-]\d{2,6})(?!\d)|\b(EVEN)\b",
    flags=re.IGNORECASE,
)
PERCENT_PATTERN = re.compile(r"(?<!\d)(100|[1-9]?\d)%")
TIME_PATTERN = re.compile(
    r"(?P<month>\d{1,2})/(?P<day>\d{1,2})\s*,\s*"
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})\s*(?P<ampm>AM|PM)",
    flags=re.IGNORECASE,
)


def _zone(name, fallback):
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return fallback


class DraftKingsParser:
    def __init__(
        self,
        source_timezone="America/New_York",
        target_timezone="America/Mexico_City",
        now=None,
    ):
        self.source_timezone_name = source_timezone
        self.target_timezone_name = target_timezone
        self.source_tz = _zone(source_timezone, timezone(timedelta(hours=-4)))
        self.target_tz = _zone(target_timezone, timezone(timedelta(hours=-6)))
        self.now = now

    @staticmethod
    def _text(value):
        text = unicodedata.normalize("NFKC", str(value or ""))
        text = text.replace("\u2212", "-").replace("\u2013", "-")
        return " ".join(text.split())

    def count_events(self, html):
        soup = BeautifulSoup(html or "", "html.parser")
        return len(soup.select(".tb-se"))

    def split_game(self, text):
        game = self._text(text)
        at_parts = re.split(r"\s+@\s+", game, maxsplit=1, flags=re.IGNORECASE)
        if len(at_parts) == 2:
            return {"away": at_parts[0].strip(), "home": at_parts[1].strip()}

        versus_parts = re.split(
            r"\s+(?:vs\.?|v\.)\s+", game, maxsplit=1, flags=re.IGNORECASE
        )
        if len(versus_parts) == 2:
            return {"away": versus_parts[1].strip(), "home": versus_parts[0].strip()}

        return {"away": game, "home": ""}

    def _now_source(self):
        if self.now is None:
            return datetime.now(self.source_tz)
        current = self.now
        if current.tzinfo is None:
            return current.replace(tzinfo=self.source_tz)
        return current.astimezone(self.source_tz)

    def parse_event_datetime(self, raw):
        source_text = self._text(raw)
        match = TIME_PATTERN.search(source_text)
        if not match:
            return {
                "sourceTimeRaw": source_text,
                "time_raw": source_text,
                "date": None,
                "time": None,
                "startIso": None,
                "sourceTimezone": self.source_timezone_name,
                "timezone": self.target_timezone_name,
            }

        now = self._now_source()
        month, day = int(match.group("month")), int(match.group("day"))
        hour, minute = int(match.group("hour")), int(match.group("minute"))
        if match.group("ampm").upper() == "PM" and hour != 12:
            hour += 12
        elif match.group("ampm").upper() == "AM" and hour == 12:
            hour = 0

        candidates = []
        for year in (now.year - 1, now.year, now.year + 1):
            try:
                candidates.append(
                    datetime(year, month, day, hour, minute, tzinfo=self.source_tz)
                )
            except ValueError:
                continue
        if not candidates:
            return {
                "sourceTimeRaw": source_text,
                "time_raw": source_text,
                "date": None,
                "time": None,
                "startIso": None,
                "sourceTimezone": self.source_timezone_name,
                "timezone": self.target_timezone_name,
            }

        source_dt = min(candidates, key=lambda value: abs(value - now))
        local_dt = source_dt.astimezone(self.target_tz)
        return {
            "sourceTimeRaw": source_text,
            "time_raw": local_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "date": local_dt.strftime("%Y-%m-%d"),
            "time": local_dt.strftime("%H:%M"),
            "startIso": local_dt.isoformat(timespec="seconds"),
            "sourceStartIso": source_dt.isoformat(timespec="seconds"),
            "sourceTimezone": self.source_timezone_name,
            "timezone": self.target_timezone_name,
        }

    def _extract_odds(self, row_text, pick_text):
        remainder = row_text.replace(pick_text, "", 1).strip()
        match = ODDS_PATTERN.search(remainder)
        if not match:
            return None
        token = (match.group(1) or match.group(2)).upper()
        return "+100" if token == "EVEN" else token

    def _extract_line(self, pick_text, market_name):
        pick, market = self._text(pick_text), self._text(market_name).lower()
        if any(word in market for word in ("total", "totales", "puntos", "goals")):
            match = re.search(
                r"\b(?:over|under|más|menos)\s+([+-]?\d+(?:\.\d+)?)\b",
                pick,
                flags=re.IGNORECASE,
            )
            return match.group(1) if match else None
        if any(
            word in market
            for word in ("spread", "run line", "puck line", "handicap", "hándicap")
        ):
            match = re.search(r"([+-]\d+(?:\.\d+)?)\s*$", pick)
            if match:
                return match.group(1)
            if re.search(r"\b(?:pk|pick(?:'em)?)\b", pick, flags=re.IGNORECASE):
                return "0"
        return None

    @staticmethod
    def _valid_distribution(entries, tolerance=2):
        if len(entries) not in {2, 3}:
            return False
        handle_total = sum(entry["handle"] for entry in entries)
        bets_total = sum(entry["bets"] for entry in entries)
        return abs(handle_total - 100) <= tolerance and abs(bets_total - 100) <= tolerance

    def parse_file(self, file, league_name):
        with open(file, "r", encoding="utf-8") as source:
            html = source.read()

        soup = BeautifulSoup(html, "html.parser")
        games = []
        seen_events = set()
        scraped_at = datetime.fromtimestamp(
            os.path.getmtime(file), tz=timezone.utc
        ).isoformat(timespec="seconds")

        for event in soup.select(".tb-se"):
            title = event.select_one(".tb-se-title h5")
            time_node = event.select_one(".tb-se-title span")
            if not title:
                continue

            game_name = self._text(title.get_text(" ", strip=True))
            raw_time = time_node.get_text(" ", strip=True) if time_node else ""
            timing = self.parse_event_datetime(raw_time)
            event_key = (league_name, game_name.casefold(), timing.get("time_raw"))
            if event_key in seen_events:
                continue
            seen_events.add(event_key)

            teams = self.split_game(game_name)
            game = {
                "league": league_name,
                "game": game_name,
                "away": teams["away"],
                "home": teams["home"],
                **timing,
                "scrapedAt": scraped_at,
                "markets": [],
            }
            seen_market_rows = set()

            for block_index, block in enumerate(event.select(".tb-market-wrap > div")):
                head = block.select_one(".tb-se-head div")
                if not head:
                    continue
                market_name = self._text(head.get_text(" ", strip=True))

                for group_index, container in enumerate(block.select(".tb-sm")):
                    entries = []
                    for row in container.select(".tb-sodd"):
                        pick_node = row.select_one(".tb-slipline")
                        if not pick_node:
                            continue
                        pick_text = self._text(pick_node.get_text(" ", strip=True))
                        row_text = self._text(row.get_text(" ", strip=True))
                        percentages = [
                            int(value) for value in PERCENT_PATTERN.findall(row_text)
                        ]
                        odds = self._extract_odds(row_text, pick_text)
                        if len(percentages) < 2 or odds is None:
                            continue

                        handle, bets = percentages[0], percentages[1]
                        line = self._extract_line(pick_text, market_name)
                        row_key = (
                            market_name.casefold(), pick_text.casefold(), line, odds,
                            handle, bets,
                        )
                        if row_key in seen_market_rows:
                            continue
                        seen_market_rows.add(row_key)
                        entries.append({
                            "market": market_name,
                            "pick": pick_text,
                            "line": line,
                            "odds": odds,
                            "handle": handle,
                            "bets": bets,
                            "edge": handle - bets,
                            "marketGroup": f"{block_index}:{group_index}",
                            "observed_at": scraped_at,
                        })

                    if not self._valid_distribution(entries):
                        continue
                    for entry in entries:
                        entry["marketValid"] = True
                    game["markets"].extend(entries)

            if game["markets"]:
                games.append(game)

        return {
            "league": league_name,
            "source": "DraftKings Network Betting Splits",
            "scrapedAt": scraped_at,
            "games": games,
        }
