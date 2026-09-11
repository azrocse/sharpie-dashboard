import json
import tempfile
import unittest
from pathlib import Path
import requests

from pipeline.odds import apply_playdoit_odds
from pipeline.analyze import normalize_history
from scraper.playdoit import (
    build_event_catalog,
    decimal_to_american,
    find_event,
    match_market_group,
    PlaydoitOddsClient,
)


def playdoit_payload(total_line="47"):
    return {
        "events": [{
            "id": 10,
            "name": "CHI Bears @ CAR Panthers",
            "startDate": "2026-09-13T17:00:00Z",
            "marketIds": [20, 21, 22],
        }],
        "markets": [
            {"id": 20, "typeId": 219, "name": "Ganador", "oddIds": [100, 101]},
            {"id": 21, "typeId": 223, "name": "Hándicap", "oddIds": [102, 103]},
            {"id": 22, "typeId": 225, "name": "Totales", "oddIds": [104, 105]},
        ],
        "odds": [
            {"id": 100, "name": "CHI Bears", "price": 1.595, "oddStatus": 0},
            {"id": 101, "name": "CAR Panthers", "price": 2.47, "oddStatus": 0},
            {"id": 102, "name": "CHI Bears (-3)", "price": 1.909, "oddStatus": 0},
            {"id": 103, "name": "CAR Panthers (+3)", "price": 1.909, "oddStatus": 0},
            {"id": 104, "name": f"Más de {total_line}", "price": 1.909, "oddStatus": 0},
            {"id": 105, "name": f"Menos de {total_line}", "price": 1.909, "oddStatus": 0},
        ],
    }


class FakeClient:
    def __init__(self, payload):
        self.payload = payload

    def fetch_league(self, _league):
        return [self.payload]


class PlaydoitOddsTests(unittest.TestCase):
    def test_multi_sport_feed_keeps_successful_payloads_when_one_sport_fails(self):
        client = PlaydoitOddsClient(session=object())
        client._get = lambda _endpoint, **params: (
            (_ for _ in ()).throw(requests.ConnectionError("offline"))
            if params["sportId"] == 66 else playdoit_payload()
        )
        payloads = client.fetch_league("SPORTS")
        self.assertEqual(len(payloads), 7)

    def test_decimal_odds_are_converted_to_american(self):
        self.assertEqual(decimal_to_american(1.909), "-110")
        self.assertEqual(decimal_to_american(2.47), "+147")

    def test_college_aliases_match_without_ambiguity(self):
        payload = playdoit_payload()
        payload["events"][0].update(
            name="Richmond Spiders @ North Carolina State Wolfpack",
            startDate="2026-09-11T23:00:00Z",
        )
        event = find_event(
            "Richmond @ NC State", "2026-09-11T17:00:00-06:00",
            build_event_catalog([payload]),
        )
        self.assertEqual(event["id"], 10)

    def test_market_is_replaced_only_when_both_counterparts_match(self):
        event = build_event_catalog([playdoit_payload()])[0]
        spread = [
            {"market": "Spread", "pick": "CHI Bears -3"},
            {"market": "Spread", "pick": "CAR Panthers +3"},
        ]
        self.assertIsNotNone(match_market_group(spread, event))
        wrong_total = [
            {"market": "Total", "pick": "Over 49.5"},
            {"market": "Total", "pick": "Under 49.5"},
        ]
        self.assertIsNone(match_market_group(wrong_total, event))

    def test_overlay_uses_playdoit_and_falls_back_to_dk_by_complete_market(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "nfl.json"
            payload = {
                "league": "NFL",
                "games": [{
                    "game": "CHI Bears @ CAR Panthers",
                    "startIso": "2026-09-13T11:00:00-06:00",
                    "markets": [
                        {"market": "Spread", "marketGroup": "1:0", "pick": "CHI Bears -3", "odds": "-102", "bets": 43, "handle": 56, "observed_at": "2026-09-11T16:00:00Z"},
                        {"market": "Spread", "marketGroup": "1:0", "pick": "CAR Panthers +3", "odds": "-118", "bets": 57, "handle": 44, "observed_at": "2026-09-11T16:00:00Z"},
                        {"market": "Total", "marketGroup": "2:0", "pick": "Over 49.5", "odds": "-108", "bets": 58, "handle": 76, "observed_at": "2026-09-11T16:00:00Z"},
                        {"market": "Total", "marketGroup": "2:0", "pick": "Under 49.5", "odds": "-112", "bets": 42, "handle": 24, "observed_at": "2026-09-11T16:00:00Z"},
                    ],
                }],
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            apply_playdoit_odds([str(path)], client=FakeClient(playdoit_payload()))
            markets = json.loads(path.read_text(encoding="utf-8"))["games"][0]["markets"]
            self.assertEqual([row["odds"] for row in markets[:2]], ["-110", "-110"])
            self.assertTrue(all(row["oddsSource"] == "PLAYDOIT" for row in markets[:2]))
            self.assertEqual([row["odds"] for row in markets[2:]], ["-108", "-112"])
            self.assertTrue(all(row["oddsSource"] == "DRAFTKINGS_FALLBACK" for row in markets[2:]))
            self.assertEqual(markets[0]["draftKingsOdds"], "-102")
            self.assertEqual(len(markets[0]["playdoitHistory"]), 1)
            apply_playdoit_odds([str(path)], client=FakeClient(playdoit_payload()))
            markets = json.loads(path.read_text(encoding="utf-8"))["games"][0]["markets"]
            self.assertEqual(markets[0]["draftKingsOdds"], "-102")

    def test_model_history_uses_only_playdoit_without_hiding_flow_history(self):
        market = {
            "oddsSource": "PLAYDOIT",
            "history": [
                {"time": "2026-09-11T15:00:00Z", "bets": 40, "handle": 60, "odds": "-105"},
                {"time": "2026-09-11T15:05:00Z", "bets": 41, "handle": 61, "odds": "-108"},
            ],
            "playdoitHistory": [
                {"time": "2026-09-11T15:05:00Z", "bets": 41, "handle": 61, "odds": "-115"},
            ],
        }
        self.assertEqual(len(normalize_history(market)), 2)
        self.assertEqual(normalize_history(market, source_specific=True)[0]["odds"], "-115")


if __name__ == "__main__":
    unittest.main()
