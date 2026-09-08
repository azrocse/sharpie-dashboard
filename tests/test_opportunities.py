from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest

from opportunities import CDMX, save_opportunities


class OpportunityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "opportunities.json"
        self.now = datetime(2026, 9, 7, 10, tzinfo=CDMX)
        self.pick = {
            "id": 1, "date": "2026-09-07", "iso": "2026-09-07T12:00:00",
            "sourceLeague": "SPORTS", "league": "MLB", "game": "Dodgers @ Padres",
            "market": "Moneyline", "pick": "Dodgers", "odds": "+130",
            "actionKey": "bet", "pickCategory": "VALUE", "status": "UPCOMING",
            "ev": 7.71, "modelEdge": 3.35, "modelProb": 46.83, "stake": 1.5,
            "freeRelease": True, "history": [{"betsPct": 40, "handlePct": 75}],
        }

    def test_saves_only_recommended_opportunities_without_recalculating(self):
        picks = [self.pick, {**self.pick, "pick": "Premium", "pickCategory": "PREMIUM"},
                 {**self.pick, "pick": "Longshot", "pickCategory": "LONGSHOT", "actionKey": "speculative"},
                 {**self.pick, "pick": "Watch", "actionKey": "pass"}]
        data = save_opportunities(picks, self.path, self.now)
        self.assertEqual(data["count"], 2)
        saved = next(p for p in data["picks"] if p["pick"] == "Dodgers")
        for key, value in self.pick.items():
            self.assertEqual(saved[key], value)

    def test_updates_same_pick_when_card_id_or_inferred_league_changes(self):
        first = save_opportunities([self.pick], self.path, self.now)["picks"][0]
        new = {**self.pick, "id": 200, "league": "SPORTS", "odds": "+140", "ev": 8.2}
        data = save_opportunities([new], self.path, self.now + timedelta(minutes=5))
        self.assertEqual(data["count"], 1)
        saved = data["picks"][0]
        self.assertEqual(saved["opportunityId"], first["opportunityId"])
        self.assertEqual(saved["firstCapturedAt"], first["firstCapturedAt"])
        self.assertEqual(saved["odds"], "+140")

    def test_freezes_last_eligible_version_at_kickoff_even_when_no_picks_remain(self):
        save_opportunities([self.pick], self.path, self.now)
        data = save_opportunities([], self.path, self.now + timedelta(hours=2))
        self.assertEqual(data["picks"][0]["frozenAt"], "2026-09-07T12:00:00-06:00")
        data = save_opportunities([{**self.pick, "odds": "+999", "iso": "2026-09-07T14:00:00"}], self.path, self.now + timedelta(hours=3))
        self.assertEqual(data["picks"][0]["odds"], "+130")

    def test_does_not_overwrite_an_opportunity_with_followup(self):
        save_opportunities([self.pick], self.path, self.now)
        data = save_opportunities([{**self.pick, "actionKey": "pass", "stake": 0}], self.path, self.now + timedelta(minutes=5))
        self.assertEqual(data["picks"][0]["stake"], 1.5)

    def test_does_not_capture_events_already_started(self):
        self.assertEqual(save_opportunities([self.pick], self.path, self.now + timedelta(hours=2))["count"], 0)

    def test_corrupt_archive_is_not_silently_overwritten(self):
        self.path.write_text("{", encoding="utf-8")
        with self.assertRaises(json.JSONDecodeError):
            save_opportunities([self.pick], self.path, self.now)
        self.assertEqual(self.path.read_text(), "{")
