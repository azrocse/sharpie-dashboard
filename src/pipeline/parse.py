"""Consolida el HTML parseado y preserva la evolución de cada mercado."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from scraper.parser import DraftKingsParser
from config.league_config import league_slug
from storage import atomic_write_json


BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MAX_HISTORY_POINTS_PER_MARKET = 200
logger = logging.getLogger(__name__)


def _game_key(game):
    return (
        str(game.get("game") or "").strip().casefold(),
        str(game.get("sourceTimeRaw") or game.get("time_raw") or game.get("startIso") or game.get("date") or "").strip(),
    )


def _market_key(market, include_group=True):
    return (
        str(market.get("market") or "").strip().casefold(),
        str(market.get("marketGroup") or "").strip() if include_group else "",
        str(market.get("pick") or "").strip().casefold(),
        str(market.get("line") or "").strip() if include_group else "",
    )


def _history_point(market):
    observed_at = market.get("observed_at") or market.get("updatedAt")
    if not observed_at:
        observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {
        "time": str(observed_at),
        "bets": market.get("bets"),
        "handle": market.get("handle"),
        "odds": market.get("odds"),
    }


def _normalize_history(points):
    unique = {}
    for point in points:
        if not isinstance(point, dict):
            continue
        normalized = {
            "time": str(point.get("time") or point.get("observed_at") or ""),
            "bets": point.get("bets", point.get("betsPct")),
            "handle": point.get("handle", point.get("handlePct")),
            "odds": point.get("odds"),
        }
        signature = (
            normalized["time"], normalized["bets"],
            normalized["handle"], str(normalized["odds"]),
        )
        unique[signature] = normalized
    ordered = sorted(unique.values(), key=lambda item: item["time"])
    return ordered[-MAX_HISTORY_POINTS_PER_MARKET:]


def _load_previous(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as source:
            payload = json.load(source)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("No se reutilizó %s: %s", path, exc)
        return {}
    index = {}
    previous_observed_at = datetime.fromtimestamp(
        os.path.getmtime(path), tz=timezone.utc
    ).isoformat(timespec="seconds")
    for game in payload.get("games", []) if isinstance(payload, dict) else []:
        if not isinstance(game, dict):
            continue
        game_key = _game_key(game)
        for market in game.get("markets", []):
            if isinstance(market, dict):
                prior = dict(market)
                prior.setdefault("observed_at", previous_observed_at)
                index[(game_key, _market_key(prior))] = prior
                index.setdefault((game_key, _market_key(prior, include_group=False)), prior)
    return index


def _merge_market_history(game, market, previous_index):
    game_key = _game_key(game)
    previous = (
        previous_index.get((game_key, _market_key(market)))
        or previous_index.get((game_key, _market_key(market, include_group=False)))
        or {}
    )
    points = []
    points.extend(previous.get("history", []))
    if previous:
        points.append(_history_point(previous))
    points.extend(market.get("history", []))
    points.append(_history_point(market))
    merged = dict(market)
    merged["history"] = _normalize_history(points)
    return merged


def _consolidate_games(raw_games):
    games = {}
    market_indexes = {}
    for game in raw_games:
        if not isinstance(game, dict) or not game.get("game"):
            continue
        key = _game_key(game)
        if key not in games:
            games[key] = {**game, "markets": []}
            market_indexes[key] = {}
        target = games[key]
        target.update({name: value for name, value in game.items() if name != "markets" and value not in (None, "")})
        for market in game.get("markets", []):
            if not isinstance(market, dict) or not market.get("pick") or not market.get("market"):
                continue
            market_key = _market_key(market)
            existing_position = market_indexes[key].get(market_key)
            if existing_position is None:
                market_indexes[key][market_key] = len(target["markets"])
                target["markets"].append(dict(market))
            else:
                target["markets"][existing_position] = dict(market)
    return [game for game in games.values() if game.get("markets")]


def parse_all(downloaded):
    """Actualiza solo los eventos presentes; conserva hasta 200 observaciones por mercado."""
    if not downloaded:
        raise ValueError("No hay descargas para parsear")
    parser = DraftKingsParser()
    output_folder = os.path.join(BASE_DIR, "data", "parsed")
    pending = []
    for league in downloaded:
        league_name = league["league"]
        observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        raw_games = []
        for page in league["pages"]:
            data = parser.parse_html(page, league_name=league_name, observed_at=observed_at)
            raw_games.extend(data.get("games", []))
        games = _consolidate_games(raw_games)
        if not games:
            raise ValueError(f"{league_name} produjo cero mercados válidos")
        filename = os.path.join(output_folder, f"{league_slug(league_name)}.json")
        previous_index = _load_previous(filename)
        for game in games:
            game["markets"] = [
                _merge_market_history(game, market, previous_index)
                for market in game["markets"]
            ]
        pending.append((filename, {
            "league": league_name,
            "slug": league["slug"],
            "generatedAt": observed_at,
            "games": games,
        }))
    for filename, payload in pending:
        atomic_write_json(filename, payload, compact=True)
        print(f"[OK] Estado actual: {os.path.basename(filename)} ({len(payload['games'])} juegos)")
    return [filename for filename, _ in pending]
