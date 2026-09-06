import unittest

from pipeline.settle_history_espn import event_match_score, settlement_identity_valid


def espn_event(event_id, away, home):
    return {
        "id": event_id,
        "date": "2026-09-06T01:00:00Z",
        "competitions": [{"competitors": [
            {"homeAway": "away", "team": {"displayName": away}},
            {"homeAway": "home", "team": {"displayName": home}},
        ]}],
    }


class SettlementIdentityTests(unittest.TestCase):
    def setUp(self):
        self.pick = {
            "game": "Club America vs Tijuana Caliente",
            "away": "Club America",
            "home": "Tijuana Caliente",
            "date": "2026-09-05",
            "time": "19:00",
            "iso": "2026-09-05T19:00:00",
            "eventLookup": {"eventId": "wrong-id", "espnSport": "soccer"},
        }

    def test_stored_id_never_overrides_wrong_teams(self):
        wrong = espn_event("wrong-id", "Army Black Knights", "Navy Midshipmen")
        self.assertEqual(event_match_score(self.pick, wrong), 0.0)

    def test_both_teams_are_required(self):
        partial = espn_event("other-id", "Club America", "Puebla")
        self.assertEqual(event_match_score(self.pick, partial), 0.0)

    def test_valid_stored_id_is_trusted_only_after_identity_check(self):
        correct = espn_event("wrong-id", "America", "Tijuana")
        self.assertEqual(event_match_score(self.pick, correct), 1000.0)

    def test_impossible_saved_soccer_result_is_rejected(self):
        self.pick["settlement"] = {
            "status": "LOSS", "eventName": "Army at Navy",
            "awayScore": 24, "homeScore": 45,
        }
        self.assertFalse(settlement_identity_valid(self.pick))


if __name__ == "__main__":
    unittest.main()
