from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from tracking import update_tracking, decimal_odds
from opportunities import CDMX


class TrackingTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'tracking.json'
        self.now=datetime(2026,9,7,12,tzinfo=CDMX)
        self.pick={'game':'A vs B','pick':'A','market':'Moneyline','league':'SPORTS','sourceLeague':'SPORTS',
                   'iso':'2026-09-07T15:00:00','odds':'+110','modelProb':55,'modelEdge':7.38,'ev':15.5,
                   'stake':1.5,'personalStake':3.5,'betsPct':35,'handlePct':70,'divergence':35,'confidenceScore':65,
                   'marketSignal':'SMART_MONEY','actionKey':'bet','pickCategory':'FREE',
                   'history':[{'timestamp':(self.now-timedelta(minutes=5)).isoformat(),'odds':'+100','betsPct':30,'handlePct':60},
                              {'timestamp':self.now.isoformat(),'odds':'+110','betsPct':35,'handlePct':70}]}

    def update(self,minutes=0,pick=None):
        return update_tracking([pick or self.pick],self.path,self.now+timedelta(minutes=minutes))['records']

    def test_baseline_survives_new_runs_and_new_browser_ids(self):
        first=next(iter(self.update().values()))
        self.pick['history']=self.pick['history'][1:]+[{'timestamp':(self.now+timedelta(minutes=5)).isoformat(),'odds':'+120','betsPct':40,'handlePct':75}]
        self.pick.update(id=999,odds='+120')
        second=next(iter(self.update(5).values()))
        self.assertEqual(first['initial'],second['initial'])
        self.assertEqual(first['firstEvaluation'],second['firstEvaluation'])
        self.assertEqual(first['trackingId'],second['trackingId'])
        self.assertEqual(second['initial']['odds'],'+100')
        self.assertEqual(second['current']['personalStake'],3.5)

    def test_value_is_available_without_extra_confirmation(self):
        self.assertEqual(next(iter(self.update().values()))['state'],'READY')
        self.assertEqual(next(iter(self.update(1).values()))['state'],'READY')

    def test_ev_alone_cannot_trigger_entry(self):
        for field,value in [('actionKey','watch'),('pickCategory','LONGSHOT')]:
            record=next(iter(self.update(pick={**self.pick,field:value,'ev':90}).values()))
            self.assertNotIn(record['state'],{'READY','CANDIDATE'})

    def test_no_second_confidence_or_time_gate(self):
        self.pick.update(confidenceScore=20, iso='2026-09-07T12:02:00')
        self.assertEqual(next(iter(self.update().values()))['state'],'READY')

    def test_out_of_order_reading_cannot_confirm_entry(self):
        self.update()
        self.pick['history']=self.pick['history'][:1]
        record=next(iter(self.update(1).values()))
        self.assertEqual(record['state'],'STALE')
        self.assertNotIn('confirmations',record)

    def test_stale_missing_and_closed_have_no_entry(self):
        self.update()
        self.assertEqual(next(iter(self.update(16).values()))['state'],'STALE')
        state=update_tracking([],self.path,self.now+timedelta(minutes=20),feed_ok=False)
        self.assertEqual(next(iter(state['records'].values()))['state'],'UNAVAILABLE')
        state=update_tracking([],self.path,self.now+timedelta(hours=3))
        self.assertEqual(next(iter(state['records'].values()))['state'],'CLOSED')

    def test_future_match_date_changes_identity(self):
        self.update()
        changed={**self.pick,'iso':'2026-09-08T15:00:00'}
        records=self.update(pick=changed)
        self.assertEqual(len(records),2)
        self.assertEqual(records[changed['trackingId']]['state'],'READY')

    def test_exact_league_upgrade_keeps_one_tracking_record(self):
        first = next(iter(self.update().values()))
        changed = {**self.pick, 'league':'NFL', 'sourceLeague':'NFL'}
        records = self.update(1, pick=changed)
        self.assertEqual(len(records), 1)
        record = next(iter(records.values()))
        self.assertEqual(record['trackingId'], first['trackingId'])
        self.assertEqual(record['league'], 'NFL')

    def test_price_comparison_handles_positive_negative_boundary(self):
        self.assertLess(decimal_odds('-110'),decimal_odds('+100'))
        self.assertIsNone(decimal_odds('0'))
