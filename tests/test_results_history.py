import json
import tempfile
import unittest
from pathlib import Path

from dashboard.generate_results_viewer import load_history


class ResultsHistoryTests(unittest.TestCase):
    def test_preserves_published_pick_without_recalibrating_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "history"
            root.mkdir()
            snapshot = Path(tmp) / "results_snapshot.json"
            snapshot.write_text(json.dumps([{
                "historyId": "legacy-id", "date": "2026-09-06", "league": "SPORTS",
                "game": "A @ B", "market": "Moneyline", "pick": "A",
                "pickCategory": "VALUE", "actionKey": "bet", "stake": 1.0,
                "ev": 1.2, "modelEdge": 0.5, "odds": "+100", "result": "PENDING",
            }]), encoding="utf-8")
            records = load_history(root, snapshot)
            self.assertEqual(len(records), 1)

    def test_daily_record_replaces_snapshot_duplicate_even_with_different_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "history"
            day = root / "2026-09-06"
            day.mkdir(parents=True)
            base = {
                "date": "2026-09-06", "league": "SPORTS", "game": "A @ B",
                "market": "Moneyline", "pick": "A", "pickCategory": "VALUE",
                "actionKey": "bet", "stake": 1.0, "ev": 4.0, "modelEdge": 2.0,
                "result": "PENDING",
            }
            snapshot = Path(tmp) / "results_snapshot.json"
            snapshot.write_text(json.dumps([{**base, "historyId": "old", "odds": "+100"}]), encoding="utf-8")
            (day / "sharpie.json").write_text(json.dumps({"picks": [{**base, "historyId": "new", "odds": "+110"}]}), encoding="utf-8")
            records = load_history(root, snapshot)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["odds"], "+110")


if __name__ == "__main__":
    unittest.main()
