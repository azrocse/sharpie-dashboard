import json
import tempfile
import unittest
import requests
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import main
from config.league_config import enabled_leagues
from dashboard.generate_dashboard import assign_medals, assign_personal_stakes, build_market_observations, build_picks, generate_dashboard
from pipeline import analyze, download, parse
from scraper.draftkings import DraftKingsScraper


def sample_html():
    kickoff = datetime.now(timezone.utc) + timedelta(days=2)
    return f'''<div class="tb-se">
      <div class="tb-se-title"><h5>Dodgers @ Padres</h5><span>{kickoff:%m/%d}, 07:00PM</span></div>
      <div class="tb-market-wrap"><div>
        <div class="tb-se-head"><div>Moneyline</div></div>
        <div class="tb-sm">
          <div class="tb-sodd"><span class="tb-slipline">Dodgers</span> +130 75% 40%</div>
          <div class="tb-sodd"><span class="tb-slipline">Padres</span> -150 25% 60%</div>
        </div>
      </div></div>
    </div>'''


class CurrentPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.stack = ExitStack()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(parse, "BASE_DIR", str(self.root)))
        self.stack.enter_context(patch.object(analyze, "INPUT_DIR", str(self.root / "data/parsed")))
        self.stack.enter_context(patch.object(analyze, "SHARPIE_PATH", str(self.root / "data/analyzed/sharpie.json")))
        one_source = [{"league":"SPORTS", "slug":"Sports", "date_range":"n30days"}]
        self.stack.enter_context(patch("pipeline.download.enabled_leagues", return_value=one_source))
        self.stack.enter_context(patch.object(analyze, "enabled_leagues", return_value=one_source))
        self.stack.enter_context(patch("dashboard.generate_dashboard.enabled_leagues", return_value=one_source))
        self.stack.enter_context(patch("main.generate_dashboard", side_effect=lambda **kw: generate_dashboard(output_dir=self.root, **kw)))

    def run_feed(self, minute=0, html=None):
        observed = datetime.now(timezone.utc) + timedelta(minutes=minute)
        with patch.object(DraftKingsScraper, "fetch_page", return_value=html or sample_html()), patch.object(parse, "datetime") as clock:
            clock.now.return_value = observed
            clock.fromtimestamp.side_effect = datetime.fromtimestamp
            return main.main(runtime_dir=self.root / '.runtime')

    def test_full_flow_creates_only_current_state_and_preserves_observations(self):
        self.run_feed()
        self.assertEqual(json.loads((self.root / "picks.json").read_text()), [])
        self.run_feed(minute=1)
        files = {path.relative_to(self.root).as_posix() for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(files, {"data/parsed/sports.json", "data/analyzed/sharpie.json", "data/opportunities.json", "opportunities.html", "index.html", "picks.json", ".runtime/tracking.json"})
        picks = json.loads((self.root / "picks.json").read_text(encoding="utf-8"))
        self.assertEqual(len(picks), 2)
        self.assertTrue(all(pick["league"] == "SPORTS" for pick in picks))
        self.assertTrue(all(len(pick["history"]) == 2 for pick in picks))
        self.assertNotIn("personalStake", json.dumps(picks))
        tracking = json.loads((self.root / ".runtime/tracking.json").read_text(encoding="utf-8"))
        self.assertTrue(any("personalStake" in record.get("current", {}) for record in tracking["records"].values()))
        built = build_picks(json.loads((self.root / "data/analyzed/sharpie.json").read_text(encoding="utf-8")))
        self.assertEqual(len(built), len(picks))
        for record in built:
            self.assertNotIn("priorityKey", record)
            self.assertNotIn("flowAdjustment", record)
            self.assertNotIn("pattern", record)
            self.assertIn("reason", record)
            self.assertIn("history", record)
        self.assertTrue(all("clv" not in pick and "result" not in pick for pick in picks))
        html = (self.root / "index.html").read_text(encoding="utf-8")
        self.assertIn("Dodgers", html)
        self.assertNotIn("__PICKS_JSON__", html)
        self.assertNotIn("results.html", html)
        saved = json.loads((self.root / "data/opportunities.json").read_text(encoding="utf-8"))["picks"]
        recommended = [p for p in picks if p["actionKey"] == "bet" and p["pickCategory"] in {"FREE", "PREMIUM", "WHALE"}]
        self.assertEqual(len(saved), len(recommended))
        self.assertGreater(len(saved), 0)
        for pick in recommended:
            record = next(row for row in saved if row["id"] == pick["id"])
            for key, value in pick.items():
                self.assertEqual(record[key], value)
        self.assertNotIn('>FREE RELEASE', html)
        self.assertNotIn('confidenceScore', html)
        self.assertIn('TOP 3 DEL MOMENTO', html)
        self.assertIn('podiumDateTime', html)
        self.assertIn('Mapa de valor', html)
        self.assertIn('data-date-range="today"', html)
        self.assertIn('data-market="Moneyline"', html)
        self.assertIn('window.SHARPIE_LEAGUES=["SPORTS"]', html)

    def test_scraper_url_uses_exact_draftkings_filters(self):
        url = DraftKingsScraper().build_url("NCAA Football", "n30days", 2)
        query = parse_qs(urlparse(url).query)
        self.assertEqual(query["tb_eg"], ["NCAA Football"])
        self.assertEqual(query["itm_content"], ["NCAA Football"])
        self.assertEqual(query["tb_edate"], ["n30days"])
        self.assertEqual(query["tb_emt"], ["0"])
        self.assertEqual(query["tb_page"], ["2"])

    def test_exact_league_replaces_sports_duplicate(self):
        generic = {"date":"2026-09-10","game":"A @ B","market":"Moneyline","pick":"A","league":"SPORTS"}
        exact = {**generic, "league":"NFL", "sourceLeague":"NFL"}
        cleaned = analyze.prefer_exact_leagues([
            {"league":"SPORTS","markets":[generic]},
            {"league":"NFL","markets":[exact]},
        ])
        self.assertEqual([(g["league"], len(g["markets"])) for g in cleaned], [("NFL", 1)])

    def test_one_failed_league_does_not_discard_successful_downloads(self):
        sources = [
            {"league":"SPORTS","slug":"Sports","date_range":"n30days"},
            {"league":"NFL","slug":"NFL","date_range":"n30days"},
        ]
        with patch.object(download, "enabled_leagues", return_value=sources), patch.object(
            DraftKingsScraper, "scrape_league", side_effect=[[sample_html()], requests.ConnectionError("offline")]
        ):
            result = download.download_all()
        self.assertEqual([item["league"] for item in result], ["SPORTS"])

    def test_empty_seasonal_league_writes_empty_current_state(self):
        parsed = parse.parse_all([
            {"league":"SPORTS","slug":"Sports","date_range":"n30days","pages":[sample_html()]},
            {"league":"NBA","slug":"NBA","date_range":"n30days","pages":[]},
        ])
        self.assertEqual(len(parsed), 2)
        nba = json.loads((self.root / "data/parsed/nba.json").read_text(encoding="utf-8"))
        self.assertEqual(nba["games"], [])

    def test_failed_download_or_parse_keeps_last_successful_files(self):
        self.run_feed()
        self.run_feed(minute=1)
        before = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file() and '.runtime' not in path.parts}
        with patch.object(DraftKingsScraper, "fetch_page", return_value=""):
            with self.assertRaises(RuntimeError):
                main.main(runtime_dir=self.root / '.runtime')
        with self.assertRaises(ValueError):
            self.run_feed(minute=2, html=sample_html().replace("75% 40%", "5% 40%"))
        self.assertTrue(all(path.read_bytes() == content for path, content in before.items()))

    def test_independent_analysis_ignores_obsolete_json(self):
        self.run_feed()
        obsolete = self.root / "data/parsed/mlb.json"
        obsolete.write_text("invalid obsolete data", encoding="utf-8")
        analyze.analyze_all()
        self.assertEqual(analyze.get_current_files(), [str(self.root / "data/parsed/sports.json")])

    def test_failure_on_later_page_does_not_publish_partial_download(self):
        self.run_feed()
        before = (self.root / "data/parsed/sports.json").read_bytes()
        with patch.object(DraftKingsScraper, "_download", side_effect=[sample_html(), requests.ConnectionError("offline")]):
            with self.assertRaises(requests.ConnectionError):
                main.main(runtime_dir=self.root / '.runtime')
        self.assertEqual((self.root / "data/parsed/sports.json").read_bytes(), before)

    def test_invalid_current_json_does_not_overwrite_analysis(self):
        self.run_feed()
        output = self.root / "data/analyzed/sharpie.json"
        before = output.read_bytes()
        (self.root / "data/parsed/sports.json").write_text("{", encoding="utf-8")
        with self.assertRaises(json.JSONDecodeError):
            analyze.analyze_all()
        self.assertEqual(output.read_bytes(), before)

    def test_market_observations_are_bounded(self):
        points = [{"time": f"2026-09-01T{index // 60:02d}:{index % 60:02d}:00+00:00", "bets": 40, "handle": 75, "odds": "+130"} for index in range(250)]
        normalized = parse._normalize_history(points)
        self.assertEqual(len(normalized), 200)
        self.assertEqual(normalized[-1], points[-1])

    def test_medals_use_category_then_raw_kelly_without_synthetic_score(self):
        picks = [
            {'pick':'Free','actionKey':'bet','pickCategory':'FREE','odds':'+200','modelProb':40,'modelEdge':6,'ev':20,'modelHistoryPoints':9,'marketSignals':['SMART_MONEY'],'signedDivergence':40,'iso':'2026-09-10T12:00:00'},
            {'pick':'Premium B','actionKey':'bet','pickCategory':'PREMIUM','odds':'+120','modelProb':50,'modelEdge':5,'ev':10,'modelHistoryPoints':8,'marketSignals':['CONSENSUS'],'signedDivergence':2,'iso':'2026-09-10T13:00:00'},
            {'pick':'Premium A','actionKey':'bet','pickCategory':'PREMIUM','odds':'+120','modelProb':52,'modelEdge':5.5,'ev':14.4,'modelHistoryPoints':4,'marketSignals':['SMART_MONEY'],'signedDivergence':30,'iso':'2026-09-10T14:00:00'},
            {'pick':'Whale','actionKey':'bet','pickCategory':'WHALE','odds':'-110','modelProb':58,'modelEdge':5.62,'ev':10.73,'modelHistoryPoints':3,'marketSignals':['SMART_MONEY'],'signedDivergence':40,'iso':'2026-09-10T15:00:00'},
        ]
        assign_medals(picks)
        ranked = sorted((p['medalRank'], p['pick']) for p in picks if 'medalRank' in p)
        self.assertEqual(ranked, [(1,'Whale'),(2,'Premium A'),(3,'Premium B')])

    def test_private_portfolio_limits_pick_count_by_day_and_event_exposure(self):
        def pick(date, index, game=None):
            return {'date':date,'iso':f'{date}T{10+index:02d}:00:00','game':game or f'Game {index}',
                    'pick':f'Pick {index}','actionKey':'bet','pickCategory':'PREMIUM','odds':'+125',
                    'modelProb':60,'modelEdge':15,'ev':35}
        weekday = [pick('2026-09-11', index) for index in range(5)]
        weekend = [pick('2026-09-12', index) for index in range(7)]
        same_event = [pick('2026-09-13', index, game='Same event') for index in range(3)]
        rows = assign_personal_stakes(weekday + weekend + same_event)
        active = lambda date: [row for row in rows if row['date'] == date and row['personalStake'] > 0]
        self.assertEqual(len(active('2026-09-11')), 4)
        self.assertLessEqual(sum(row['personalStake'] for row in active('2026-09-11')), 20)
        self.assertEqual(len(active('2026-09-12')), 6)
        self.assertLessEqual(sum(row['personalStake'] for row in active('2026-09-12')), 30)
        self.assertEqual(len(active('2026-09-13')), 2)
        self.assertEqual(sum(row['personalStake'] for row in active('2026-09-13')), 8)

    def test_observations_exclude_live_data_and_duplicate_timestamps(self):
        before = {"time": "2026-09-07T17:00:00+00:00", "betsPct": 40, "handlePct": 75, "odds": "+130"}
        live = {**before, "time": "2026-09-07T18:00:00+00:00"}
        points = build_market_observations([before, before, live], "2026-09-07T12:00:00-06:00")
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["timestamp"], "2026-09-07T11:00:00-06:00")

    def test_empty_current_dashboard_replaces_outdated_picks(self):
        self.run_feed()
        self.run_feed(minute=1)
        source = self.root / "data/analyzed/sharpie.json"
        data = json.loads(source.read_text(encoding="utf-8"))
        for league in data:
            for market in league["markets"]:
                market["startIso"] = "2000-01-01T12:00:00-06:00"
        source.write_text(json.dumps(data), encoding="utf-8")
        generate_dashboard(source, self.root)
        self.assertEqual(json.loads((self.root / "picks.json").read_text()), [])

    def test_config_rejects_colliding_filenames(self):
        config = self.root / "leagues.json"
        config.write_text(json.dumps({name: {"enabled": True, "slug": "Sports"} for name in ("NCAA Football", "NCAA_Football")}), encoding="utf-8")
        with self.assertRaises(ValueError):
            enabled_leagues(config)

    def test_team_names_do_not_create_unconfigured_leagues(self):
        self.run_feed()
        data = json.loads((self.root / "data/analyzed/sharpie.json").read_text(encoding="utf-8"))
        self.assertTrue(all(market["league"] == "SPORTS" for group in data for market in group["markets"]))
        self.assertTrue(all("espnLeague" not in market for group in data for market in group["markets"]))
