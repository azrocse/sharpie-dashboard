"""Consolida el HTML parseado y preserva la evolución de cada mercado."""

from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from datetime import datetime, timezone

from scraper.parser import DraftKingsParser


BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MAX_SNAPSHOTS_PER_LEAGUE = 200
MAX_HISTORY_POINTS_PER_MARKET = 200
logger = logging.getLogger(__name__)


def _slugify(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-z0-9]+", "_", text.casefold()).strip("_")
    return text or "unknown"


def _atomic_write_json(path, payload):
    temporary = f"{path}.tmp"
    with open(temporary, "w", encoding="utf-8") as output:
        json.dump(payload, output, indent=4, ensure_ascii=False)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


def save_snapshot(data, league_slug, snapshots_root):
    league_folder = os.path.join(snapshots_root, league_slug)
    os.makedirs(league_folder, exist_ok=True)
    # El dashboard interpreta exactamente YYYYMMDD_HHMMSS para construir CLV.
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_path = os.path.join(league_folder, f"{timestamp}.json")
    _atomic_write_json(snapshot_path, data)
    if MAX_SNAPSHOTS_PER_LEAGUE is not None:
        _prune_old_snapshots(league_folder, MAX_SNAPSHOTS_PER_LEAGUE)
    return snapshot_path


def _prune_old_snapshots(league_folder, keep):
    if not isinstance(keep, int) or keep < 1:
        raise ValueError("MAX_SNAPSHOTS_PER_LEAGUE debe ser un entero mayor que cero o None")
    files = sorted(
        name for name in os.listdir(league_folder)
        if name.endswith(".json") and os.path.isfile(os.path.join(league_folder, name))
    )
    for old_file in files[:-keep]:
        try:
            os.remove(os.path.join(league_folder, old_file))
        except OSError as exc:
            logger.warning("No se pudo eliminar snapshot antiguo %s: %s", old_file, exc)


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


def _load_recent_history(parsed_path, snapshot_folder, limit=20):
    sources = [parsed_path]
    if os.path.isdir(snapshot_folder):
        snapshots = sorted(
            os.path.join(snapshot_folder, name)
            for name in os.listdir(snapshot_folder)
            if name.endswith(".json")
        )
        sources.extend(reversed(snapshots[-limit:]))
    merged = {}
    for source_path in sources:
        for key, market in _load_previous(source_path).items():
            merged.setdefault(key, market)
    return merged


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
    parser = DraftKingsParser()
    output_folder = os.path.join(BASE_DIR, "data", "parsed")
    snapshots_root = os.path.join(BASE_DIR, "data", "snapshots")
    os.makedirs(output_folder, exist_ok=True)
    os.makedirs(snapshots_root, exist_ok=True)

    parsed_files = []
    for league in downloaded or []:
        if not isinstance(league, dict):
            continue
        league_name = str(league.get("league") or "").strip()
        files = [path for path in (league.get("files") or []) if isinstance(path, str) and os.path.isfile(path)]
        if not league_name or not files:
            logger.warning("Liga omitida por nombre o archivos inválidos: %r", league_name)
            continue

        raw_games = []
        for file_path in files:
            try:
                raw_data = parser.parse_file(file_path, league_name=league_name)
            except Exception as exc:
                logger.exception("No se pudo parsear %s: %s", file_path, exc)
                continue
            if isinstance(raw_data, dict):
                raw_games.extend(raw_data.get("games") or [])
            elif isinstance(raw_data, list):
                raw_games.extend(raw_data)

        games = _consolidate_games(raw_games)
        if not games:
            logger.error("%s produjo cero mercados válidos; no se sobrescribe su JSON", league_name)
            continue

        league_slug = _slugify(league_name)
        filename = os.path.join(output_folder, f"{league_slug}.json")
        previous_index = _load_recent_history(
            filename, os.path.join(snapshots_root, league_slug)
        )
        for game in games:
            game["markets"] = [
                _merge_market_history(game, market, previous_index)
                for market in game.get("markets", [])
            ]

        data = {
            "league": league_name,
            "slug": str(league.get("slug") or ""),
            "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "games": games,
        }
        _atomic_write_json(filename, data)
        parsed_files.append(filename)
        save_snapshot(data, league_slug, snapshots_root)
        market_count = sum(len(game.get("markets", [])) for game in games)
        print(
            f"   ✅ Mercado capturado · {len(games)} encuentros · "
            f"{market_count} líneas analizadas · {os.path.basename(filename)}"
        )

    return parsed_files
