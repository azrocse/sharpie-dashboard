import importlib.util
import sys
import types
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "src" / "pipeline" / "analyze.py"
settlement_stub = types.ModuleType("settle_history_espn")
settlement_stub.infer_primary_route = lambda _market: None
sys.modules.setdefault("settle_history_espn", settlement_stub)
spec = importlib.util.spec_from_file_location("sharpie_analyze", MODULE_PATH)
analyze = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analyze)


class RiskCalibrationTests(unittest.TestCase):
    def test_positive_151_is_longshot_with_half_unit_cap(self):
        self.assertEqual(analyze.classify_odds_risk("+151"), ("LONGSHOT", "ALTA", 0.5))

    def test_positive_251_is_extreme_longshot(self):
        self.assertEqual(analyze.classify_odds_risk("+251"), ("EXTREME_LONGSHOT", "ALTA", 0.5))

    def test_longshot_stake_never_exceeds_half_unit(self):
        stake = analyze.calculate_stake(65.0, 3.5, 100.0, 95.0, 0.5, True)
        self.assertEqual(stake, 0.5)

    def test_non_actionable_pick_has_zero_stake(self):
        stake = analyze.calculate_stake(54.9, 2.0, 8.0, 80.0, 3.0, False)
        self.assertEqual(stake, 0.0)

    def test_qualifying_high_price_becomes_longshot_not_premium(self):
        category = analyze.classify_pick_category(
            20.0, 5.0, ["SMART_MONEY"], 30.0, 60.0, "+180", 70.0
        )
        self.assertEqual(category, "LONGSHOT")

    def test_longshot_remains_visible_with_speculative_confidence(self):
        category = analyze.classify_pick_category(
            12.0, 3.0, ["SMART_MONEY"], 20.0, 55.0, "+180", 30.0
        )
        self.assertEqual(category, "LONGSHOT")

    def test_underdog_below_55_can_be_value_when_edge_is_positive(self):
        confidence = analyze.calculate_confidence_score(
            46.83, 3.35, 7.71, 35.0, ["SMART_MONEY"], "+130", None
        )
        category = analyze.classify_pick_category(
            7.71, 3.35, ["SMART_MONEY"], 35.0, 46.83, "+130", confidence
        )
        self.assertEqual(category, "VALUE")

    def test_tommy_paul_example_is_extreme_longshot(self):
        category = analyze.classify_pick_category(
            13.85, 3.26, ["SMART_MONEY"], 30.0, 26.73, "+326", 25.9
        )
        self.assertEqual(category, "LONGSHOT")

    def test_etcheverry_example_is_longshot(self):
        category = analyze.classify_pick_category(
            9.63, 2.90, ["SMART_MONEY"], 30.0, 33.02, "+232", 33.1
        )
        self.assertEqual(category, "LONGSHOT")

    def test_whale_is_signal_not_category(self):
        category = analyze.classify_pick_category(
            20.0, 6.0, ["SMART_MONEY"], 31.0, 62.0, "+120", 70.0
        )
        self.assertEqual(category, "PREMIUM")


if __name__ == "__main__":
    unittest.main()
