"""Sustituye cuotas DK por Playdoit cuando el mercado completo coincide."""

from __future__ import annotations

import json
import logging
from collections import defaultdict

from scraper.playdoit import PlaydoitOddsClient, build_event_catalog, find_event, match_market_group
from storage import atomic_write_json

logger = logging.getLogger(__name__)
MAX_PLAYDOIT_HISTORY_POINTS = 200


def _market_groups(markets):
    grouped = defaultdict(list)
    for market in markets:
        key = (
            str(market.get("market") or ""),
            str(market.get("marketGroup") or ""),
        )
        grouped[key].append(market)
    return grouped.values()


def _append_playdoit_history(market, odds):
    points = [point for point in market.get("playdoitHistory", []) if isinstance(point, dict)]
    point = {
        "time": market.get("observed_at") or market.get("updatedAt"),
        "bets": market.get("bets"),
        "handle": market.get("handle"),
        "odds": odds,
        "oddsSource": "PLAYDOIT",
    }
    signature = (point["time"], point["bets"], point["handle"], point["odds"])
    signatures = {
        (item.get("time"), item.get("bets"), item.get("handle"), item.get("odds"))
        for item in points
    }
    if signature not in signatures:
        points.append(point)
    market["playdoitHistory"] = points[-MAX_PLAYDOIT_HISTORY_POINTS:]


def _set_fallback(game):
    for market in game.get("markets", []):
        if market.get("oddsSource") == "PLAYDOIT" and market.get("draftKingsOdds"):
            market["odds"] = market["draftKingsOdds"]
        market["oddsSource"] = "DRAFTKINGS_FALLBACK"
        market.pop("draftKingsOdds", None)
        market.pop("playdoitEventId", None)
        market.pop("playdoitMarketId", None)
        market.pop("playdoitOddId", None)


def apply_playdoit_odds(parsed_files, client=None):
    """Aplica Playdoit de forma atómica por pareja; DK cubre faltantes y fallas."""
    own_client = client is None
    client = client or PlaydoitOddsClient()
    totals = {"playdoit": 0, "fallback": 0}
    try:
        for filepath in parsed_files:
            with open(filepath, encoding="utf-8") as source:
                payload = json.load(source)
            league = payload.get("league", "")
            games = payload.get("games", [])
            try:
                catalog = build_event_catalog(client.fetch_league(league))
            except Exception as exc:
                logger.warning("Playdoit no disponible para %s; se conserva DK: %s", league, exc)
                catalog = []
            for game in games:
                _set_fallback(game)
                event = find_event(game.get("game"), game.get("startIso"), catalog)
                if event is None:
                    totals["fallback"] += len(game.get("markets", []))
                    continue
                for group in _market_groups(game.get("markets", [])):
                    matched = match_market_group(group, event)
                    if matched is None:
                        totals["fallback"] += len(group)
                        continue
                    playdoit_market, selections = matched
                    for market, selection in zip(group, selections):
                        dk_odds = market.get("odds")
                        market.update({
                            "odds": selection["odds"],
                            "decimalOdds": selection["decimalOdds"],
                            "oddsSource": "PLAYDOIT",
                            "draftKingsOdds": dk_odds,
                            "playdoitEventId": event["id"],
                            "playdoitMarketId": playdoit_market["id"],
                            "playdoitOddId": selection["id"],
                        })
                        _append_playdoit_history(market, selection["odds"])
                        totals["playdoit"] += 1
            atomic_write_json(filepath, payload, compact=True)
    finally:
        if own_client:
            client.close()
    print(
        f"[OK] Cuotas: {totals['playdoit']} Playdoit · "
        f"{totals['fallback']} DraftKings fallback"
    )
    return parsed_files
