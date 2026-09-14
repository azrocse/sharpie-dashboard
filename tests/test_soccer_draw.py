import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline import analyze
from pipeline.dk_metadata import extract_event_sport, enrich_event_sports
from scraper.parser import DraftKingsParser


class SoccerDrawTests(unittest.TestCase):
    def pair(self, odds=('+500', '-193'), flow=(50, 50, 50, 50)):
        return [{'market':'Moneyline','pick':'A','odds':odds[0],'handle':flow[0],'bets':flow[1],'history':[]},
                {'market':'Moneyline','pick':'B','odds':odds[1],'handle':flow[2],'bets':flow[3],'history':[]}]

    def test_example_infers_draw_without_normalizing_teams_to_100(self):
        pair = self.pair()
        a, b = [analyze.soccer_fair_model(p, pair) for p in pair]
        self.assertAlmostEqual(a['modelProb'], 15.87, places=2)
        self.assertAlmostEqual(b['modelProb'], 62.73, places=2)
        self.assertAlmostEqual(a['drawEstimation']['probability'], 21.4, places=2)
        self.assertEqual(a['drawEstimation']['estimatedAmericanOdds'], 345)
        self.assertEqual(sum([a['modelProb'], b['modelProb'], a['drawEstimation']['probability']]), 100)
        self.assertAlmostEqual(analyze.calculate_ev(a['modelProb'], 6), -4.78, places=2)
        self.assertFalse(a['drawEstimation']['calibrated'])

    def test_complete_probability_mass_and_zero_sum_split_adjustment(self):
        pair = self.pair(('+150', '+150'), (80, 30, 20, 70))
        a, b = [analyze.soccer_fair_model(p, pair) for p in pair]
        self.assertEqual(a['flowAdjustment'], 6)
        self.assertEqual(b['flowAdjustment'], -6)
        self.assertEqual(a['drawEstimation']['probability'], b['drawEstimation']['probability'])
        self.assertAlmostEqual(a['modelProb']+b['modelProb']+a['drawEstimation']['probability'],100)
        self.assertGreater(analyze.calculate_ev(a['modelProb'],2.5), 0)

    def test_history_is_corrected_too_not_mixed_with_old_binary_probabilities(self):
        pair = self.pair()
        for p in pair:
            p['history'] = [{'time':'2026-09-14T10:00:00','odds':p['odds'],'bets':50,'handle':50},
                            {'time':'2026-09-14T10:30:00','odds':p['odds'],'bets':50,'handle':50}]
        a=analyze.soccer_fair_model(pair[0],pair)
        self.assertEqual(a['modelProb'],15.87)
        self.assertEqual(a['modelHistoryPoints'],2)

    def test_scenario_range_includes_central_estimate(self):
        pair=self.pair()
        a=analyze.soccer_fair_model(pair[0],pair)
        d=a['drawEstimation']
        self.assertEqual(d['marginScenariosPct'],[0,5,10])
        self.assertLess(d['modelProbabilityMin'],a['modelProb'])
        self.assertGreater(d['modelProbabilityMax'],a['modelProb'])

    def test_bad_or_incomplete_pairs_do_not_fall_back_to_binary(self):
        for pair in [self.pair(('-300','-300')),self.pair(('+10000','+10000')),self.pair()[:1]]:
            self.assertIsNone(analyze.soccer_fair_model(pair[0],pair))

    def test_reordering_selections_preserves_probabilities(self):
        pair=self.pair(flow=(70,30,30,70))
        a=analyze.soccer_fair_model(pair[0],pair)
        b=analyze.soccer_fair_model(pair[0],list(reversed(pair)))
        self.assertEqual(a,b)

    def test_soccer_metadata_from_global_catalog_is_used(self):
        pair=self.pair(('+150','+150'),(80,30,20,70))
        result=analyze.process_market('SPORTS',{'game':'A vs B','sourceSportId':'1'},pair[0],pair)
        self.assertEqual(result['modelSource'],'soccer_ml_mixed_50_50_v1')
        self.assertIsNotNone(result['drawEstimation'])
        self.assertEqual(result['actionKey'],'bet')
        self.assertGreater(result['stake'],0)

    def test_known_soccer_league_and_generic_soccer_give_same_result(self):
        pair=self.pair()
        a=analyze.process_market('MLS',{'game':'A vs B'},pair[0],pair)
        b=analyze.process_market('SPORTS',{'game':'A vs B','sport':'Soccer'},pair[0],pair)
        self.assertEqual(a['modelProb'],b['modelProb'])
        self.assertEqual(a['ev'],b['ev'])

    def test_binary_sport_is_unchanged(self):
        pair=self.pair(('+130','-150'))
        expected=analyze.historical_fair_model(pair[0],pair,2.3,0)
        result=analyze.process_market('MLB',{'game':'A @ B'},pair[0],pair)
        self.assertEqual(result['modelProb'],expected[0])
        self.assertIsNone(result['drawEstimation'])

    def test_soccer_total_is_not_affected(self):
        pair=self.pair(('-110','-110'))
        for p in pair:p['market']='Total'
        result=analyze.process_market('MLS',{'game':'A vs B'},pair[0],pair)
        self.assertEqual(result['modelSource'],'sharpie_v2')
        self.assertIsNone(result['drawEstimation'])

    def test_unidentified_underround_is_not_assumed_binary(self):
        pair=self.pair()
        result=analyze.process_market('SPORTS',{'game':'A vs B'},pair[0],pair)
        self.assertEqual(result['modelSource'],'sport_not_verified')
        self.assertIsNone(result['modelProb'])
        self.assertEqual(result['stake'],0)

    def test_analysis_restores_dk_prices_from_legacy_other_book_records(self):
        pair=self.pair()
        for p in pair:
            p.update(draftKingsOdds=p['odds'],odds='+100',oddsSource='PLAYDOIT')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); source=root/'parsed.json'; output=root/'result.json'
            source.write_text(json.dumps({'league':'MLS','games':[{'game':'A vs B','date':'2030-01-01','markets':pair}]}))
            with patch.object(analyze,'SHARPIE_PATH',str(output)):
                analyze.analyze_all([source])
            markets=json.loads(output.read_text())[0]['markets']
            self.assertEqual([p['odds'] for p in markets],['+500','-193'])
            self.assertTrue(all(p['oddsSource']=='DRAFTKINGS' for p in markets))
            comparison = markets[0]['modelComparison']['evaluations']
            self.assertEqual(comparison['drawAware']['modelProb'],15.87)
            self.assertEqual(markets[0]['modelProb'],round((comparison['binary']['modelProb']+15.87)/2,2))

    def test_mixed_recomputes_ev_and_preserves_comparison(self):
        pair=self.pair(('+150','+150'),(80,30,20,70))
        result=analyze.process_market('MLS',{'game':'A vs B'},pair[0],pair)
        evaluations=result['modelComparison']['evaluations']
        self.assertEqual(result['modelProb'],round((evaluations['binary']['modelProb']+evaluations['drawAware']['modelProb'])/2,2))
        self.assertEqual(result['ev'],analyze.calculate_ev(result['modelProb'],2.5))
        self.assertEqual(result['stake'],evaluations['mixed']['stakeBeforeExposure'])
        self.assertFalse(result['modelComparison']['calibrated'])


class DkSportMetadataTests(unittest.TestCase):
    def test_parser_preserves_dk_event_identity_and_original_match_name(self):
        html='''<div class="tb-se"><div class="tb-se-title"><h5><a href="https://sportsbook.draftkings.com/event/123?x=1">Como vs Parma</a></h5><span>09/14, 12:00PM</span></div><div class="tb-market-wrap"><div><div class="tb-se-head"><div>Moneyline</div></div><div class="tb-sm"><div class="tb-sodd"><span class="tb-slipline">Como</span> +150 60% 50%</div><div class="tb-sodd"><span class="tb-slipline">Parma</span> +150 40% 50%</div></div></div></div></div>'''
        result=DraftKingsParser().parse_html(html,'SPORTS')
        self.assertEqual(result['games'][0]['sourceEventId'],'123')
        self.assertEqual(result['games'][0]['game'],'Como vs Parma')

    def test_metadata_is_bound_to_exact_event_not_navigation_or_team_name(self):
        html='"parameters":{"sportId":"6","eventId":"123"},"parameters":{"sportId":"1","eventId":"456"}'
        self.assertEqual(extract_event_sport(html,'123')['sport'],'Tennis')
        self.assertEqual(extract_event_sport(html,'456')['sport'],'Soccer')
        self.assertIsNone(extract_event_sport(html,'789'))
        self.assertIsNone(extract_event_sport('Como vs Parma soccer','123'))

    def test_conflicting_sports_are_not_guessed(self):
        html='"parameters":{"sportId":"6","eventId":"123"},"parameters":{"sportId":"1","eventId":"123"}'
        self.assertIsNone(extract_event_sport(html,'123'))

    def test_enrichment_caches_success_and_retries_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); path=root/'sports.json'; cache=root/'cache.json'
            path.write_text(json.dumps({'league':'SPORTS','games':[{'sourceEventId':'123','game':'A vs B'}]}))
            calls=[]
            def fetch(event_id):
                calls.append(event_id)
                return {'sourceSportId':'1','sport':'Soccer'}
            enrich_event_sports([path],cache,fetcher=fetch)
            enrich_event_sports([path],cache,fetcher=fetch)
            self.assertEqual(calls,['123'])
            self.assertEqual(json.loads(path.read_text())['games'][0]['sport'],'Soccer')

    def test_failed_sport_lookup_is_not_cached_as_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); path=root/'sports.json'; cache=root/'cache.json'
            path.write_text(json.dumps({'league':'SPORTS','games':[{'sourceEventId':'123'}]}))
            enrich_event_sports([path],cache,fetcher=lambda _: None)
            self.assertEqual(json.loads(cache.read_text()),{})
            self.assertNotIn('sport',json.loads(path.read_text())['games'][0])
            enrich_event_sports([path],cache,fetcher=lambda _: {'sourceSportId':'1','sport':'Soccer'})
            self.assertEqual(json.loads(path.read_text())['games'][0]['sport'],'Soccer')
