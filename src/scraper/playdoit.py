"""Cuotas públicas de Playdoit (Altenar) para mercados pregame."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from zoneinfo import ZoneInfo

import requests
import truststore
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

truststore.inject_into_ssl()

CDMX_TZ = ZoneInfo("America/Mexico_City")
API_BASE = "https://sb2frontend-altenar2.biahosted.com/api/widget/"
COMMON_PARAMS = {
    "culture": "es-ES",
    "timezoneOffset": 360,
    "integration": "playdoit2",
    "deviceType": 1,
    "numFormat": "en-GB",
    "countryCode": "MX",
}

CHAMPIONSHIP_IDS = {
    "NFL": (3281,),
    "NBA": (2980,),
    "NHL": (3232,),
    "MLB": (3286,),
    "WNBA": (5519,),
    "NCAA Football": (3284,),
    "NCAA Basketball": (2979,),
    "NCAA Womens Basketball": (2981,),
    "England Premier League": (2936,),
    "Champions League": (16808,),
    "Europa League": (16809,),
    "MLS": (4610,),
}

SPORT_IDS = {
    "UFC": (84,),
    "UFL": (75,),
    "NCAA Baseball": (76,),
    "NCAA Ice Hockey": (70,),
    "SPORTS": (66, 67, 68, 70, 71, 75, 76, 84),
}


def _ascii(value):
    return unicodedata.normalize("NFKD", str(value or "")).encode(
        "ascii", "ignore"
    ).decode()


def normalize_name(value):
    text = _ascii(value).lower().replace(" vs. ", " ").replace(" vs ", " ").replace(" @ ", " ")
    replacements = {
        r"\bnc\b": "north carolina",
        r"\bny\b": "new york",
        r"\bla\b": "los angeles",
        r"\bsf\b": "san francisco",
        r"\bst\b": "state",
        r"\bmt\b": "mount",
    }
    for pattern, replacement in replacements.items():
        text = re.sub(pattern, replacement, text)
    text = re.sub(r"\b(fc|cf|afc|sc|sk|nk)\b", " ", text)
    return " ".join(re.findall(r"[a-z0-9]+", text))


def split_event(value):
    parts = re.split(r"\s+(?:@|vs\.?|v)\s+", str(value or ""), maxsplit=1, flags=re.I)
    return parts if len(parts) == 2 else [str(value or "")]


def team_similarity(left, right):
    left, right = normalize_name(left), normalize_name(right)
    left_tokens, right_tokens = set(left.split()), set(right.split())
    if left_tokens and right_tokens and (
        left_tokens <= right_tokens or right_tokens <= left_tokens
    ):
        return 1.0
    overlap = len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))
    return max(overlap, SequenceMatcher(None, left, right).ratio())


def event_similarity(left, right):
    left_sides, right_sides = split_event(left), split_event(right)
    if len(left_sides) != 2 or len(right_sides) != 2:
        return SequenceMatcher(None, normalize_name(left), normalize_name(right)).ratio()
    direct = sum(team_similarity(a, b) for a, b in zip(left_sides, right_sides)) / 2
    crossed = sum(team_similarity(a, b) for a, b in zip(left_sides, reversed(right_sides))) / 2
    return max(direct, crossed)


def decimal_to_american(decimal_price):
    price = float(decimal_price)
    if price <= 1:
        return None
    value = round((price - 1) * 100) if price >= 2 else round(-100 / (price - 1))
    return f"{value:+d}"


def _market_kind(market):
    name = normalize_name(market.get("name"))
    type_id = market.get("typeId")
    if type_id in {1, 219} or "resultado final" in name or "ganador" in name:
        return "Moneyline"
    if type_id == 223 or "handicap" in name:
        return "Spread"
    if type_id in {18, 225} or "total" in name:
        return "Total"
    return None


def _split_pick(value):
    text = _ascii(value).replace("−", "-").strip()
    folded = normalize_name(text)
    direction = "over" if folded.startswith("over ") or folded.startswith("mas de ") else ""
    if folded.startswith("under ") or folded.startswith("menos de "):
        direction = "under"
    numbers = re.findall(r"(?<!\d)([+-]?\d+(?:\.\d+)?)", text)
    line = numbers[-1] if numbers else ""
    team = re.sub(r"\s*\(?[+-]?\d+(?:\.\d+)?\)?\s*$", "", text).strip()
    team = re.sub(r"^(?:over|under|mas de|menos de)\s+", "", team, flags=re.I)
    return direction, line, team


def selection_similarity(dk_pick, playdoit_pick, market_kind):
    dk_direction, dk_line, dk_team = _split_pick(dk_pick)
    pd_direction, pd_line, pd_team = _split_pick(playdoit_pick)
    if market_kind in {"Spread", "Total"} and dk_line != pd_line:
        return 0.0
    if market_kind == "Total":
        return 1.0 if dk_direction and dk_direction == pd_direction else 0.0
    return team_similarity(dk_team, pd_team)


def _parse_start(value):
    parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=CDMX_TZ)
    return parsed.astimezone(CDMX_TZ)


class PlaydoitOddsClient:
    """Cliente anónimo del feed que usa el sportsbook de Playdoit."""

    def __init__(self, session=None, timeout=30):
        self.timeout = timeout
        self.session = session or requests.Session()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://www.playdoit.mx",
            "Referer": "https://www.playdoit.mx/",
        }
        if session is None:
            retry = Retry(
                total=3,
                connect=3,
                read=3,
                backoff_factor=0.8,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset({"GET"}),
            )
            self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def _get(self, endpoint, **params):
        response = self.session.get(
            API_BASE + endpoint,
            params={**COMMON_PARAMS, **params},
            headers=self.headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
            raise requests.RequestException("Respuesta de cuotas Playdoit inválida")
        return payload

    def fetch_league(self, league):
        payloads = []
        errors = []
        for champ_id in CHAMPIONSHIP_IDS.get(league, ()):
            try:
                payloads.append(self._get("GetEvents", champId=champ_id))
            except requests.RequestException as exc:
                errors.append(exc)
        for sport_id in SPORT_IDS.get(league, ()):
            try:
                payloads.append(self._get("GetUpcoming", eventCount=100, sportId=sport_id))
            except requests.RequestException as exc:
                errors.append(exc)
        if not payloads and errors:
            raise errors[0]
        return payloads

    def close(self):
        self.session.close()


def build_event_catalog(payloads):
    catalog = []
    for payload in payloads:
        markets = {item["id"]: item for item in payload.get("markets", [])}
        odds = {item["id"]: item for item in payload.get("odds", [])}
        for event in payload.get("events", []):
            event_markets = []
            for market_id in event.get("marketIds", []):
                market = markets.get(market_id, {})
                kind = _market_kind(market)
                if kind is None:
                    continue
                selections = []
                for odd_id in market.get("oddIds", []):
                    odd = odds.get(odd_id, {})
                    american = decimal_to_american(odd.get("price")) if odd.get("price") else None
                    if odd.get("oddStatus") == 0 and american:
                        selections.append({
                            "id": odd_id,
                            "name": odd.get("name", ""),
                            "odds": american,
                            "decimalOdds": float(odd["price"]),
                        })
                if selections:
                    event_markets.append({
                        "id": market_id,
                        "kind": kind,
                        "selections": selections,
                    })
            if event_markets:
                catalog.append({
                    "id": event.get("id"),
                    "name": event.get("name", ""),
                    "start": _parse_start(event.get("startDate")),
                    "markets": event_markets,
                })
    unique = {}
    for event in catalog:
        unique[event["id"]] = event
    return list(unique.values())


def find_event(game, start_iso, catalog):
    try:
        kickoff = _parse_start(start_iso)
    except (TypeError, ValueError):
        return None
    timed = [event for event in catalog if abs((event["start"] - kickoff).total_seconds()) <= 5400]
    ranked = sorted(
        ((event_similarity(game, event["name"]), event) for event in timed),
        key=lambda item: item[0],
        reverse=True,
    )
    if not ranked or ranked[0][0] < 0.78:
        return None
    if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 0.08:
        return None
    return ranked[0][1]


def match_market_group(dk_group, playdoit_event):
    if len(dk_group) != 2:
        return None
    market_kind = dk_group[0].get("market")
    candidates = []
    for market in playdoit_event.get("markets", []):
        if market["kind"] != market_kind:
            continue
        matched = []
        used = set()
        for dk_selection in dk_group:
            ranked = sorted(
                ((selection_similarity(dk_selection.get("pick"), selection["name"], market_kind), selection)
                 for selection in market["selections"] if selection["id"] not in used),
                key=lambda item: item[0],
                reverse=True,
            )
            if not ranked or ranked[0][0] < 0.84:
                break
            if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 0.08:
                break
            used.add(ranked[0][1]["id"])
            matched.append(ranked[0][1])
        if len(matched) == len(dk_group):
            candidates.append((market, matched))
    return candidates[0] if len(candidates) == 1 else None
