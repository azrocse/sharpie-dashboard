import unittest
from pipeline import analyze

class RiskCalibrationTests(unittest.TestCase):
    def test_financial_categories_are_exclusive(self):
        self.assertEqual(analyze.classify_pick_category(4, 2.5, [], 0, 48, "+120"), "FREE")
        self.assertEqual(analyze.classify_pick_category(8, 5, [], 0, 55, "-110"), "PREMIUM")
        self.assertEqual(analyze.classify_pick_category(12, 7, [], 40, 60, "+100", handle=80), "WHALE")

    def test_whale_requires_extended_flow(self):
        self.assertEqual(analyze.classify_pick_category(12, 7, [], 20, 60, "+100", handle=80), "PREMIUM")
        self.assertEqual(analyze.classify_pick_category(12, 7, [], 40, 60, "+100", handle=60), "PREMIUM")

    def test_odds_outside_range_are_informative(self):
        self.assertIsNone(analyze.classify_pick_category(30, 15, [], 50, 70, "+201", handle=90))
        self.assertIsNone(analyze.classify_pick_category(30, 15, [], 50, 70, "-201", handle=90))

    def test_kelly_eighth_and_caps(self):
        self.assertEqual(analyze.calculate_stake(58.72, 2.25, 32.12, actionable=True, category="PREMIUM"), 3.0)
        self.assertLessEqual(analyze.calculate_stake(75, 2, 50, actionable=True, category="FREE"), 2.0)
        self.assertEqual(analyze.calculate_stake(40.53, 2.77, 12.27, odds_stake_cap=1.0, actionable=True, category="PREMIUM"), 1.0)
        self.assertEqual(analyze.calculate_stake(55, 2, 10, actionable=False, category="FREE"), 0.0)

    def test_personal_stake_uses_half_kelly_and_private_caps(self):
        self.assertEqual(analyze.calculate_personal_stake(58.72, 2.25, 32.12, "+125", category="PREMIUM"), 4.0)
        self.assertEqual(analyze.calculate_personal_stake(40.53, 2.77, 12.27, "+177", category="PREMIUM"), 3.0)
        self.assertEqual(analyze.calculate_personal_stake(55, 2, 10, "+100", actionable=False, category="FREE"), 0.0)

    def test_signals_are_independent_of_financial_metrics(self):
        self.assertIn("SMART_MONEY", analyze.evaluate_market_signals(20, 40, 60, -20, -10, 0, 5, None))
        self.assertIn("CONSENSUS", analyze.evaluate_market_signals(5, 70, 75, -20, -10, 0, 5, None))

if __name__ == "__main__": unittest.main()
