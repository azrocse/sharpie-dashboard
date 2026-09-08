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
                   'stake':1.5,'betsPct':35,'handlePct':70,'divergence':35,'confidenceScore':65,
                   'marketSignal':'SMART_MONEY','actionKey':'bet','pickCategory':'VALUE',
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

    def test_replaying_same_observation_does_not_confirm_entry(self):
        self.assertEqual(next(iter(self.update().values()))['state'],'CONFIRMING')
        self.assertEqual(next(iter(self.update(1).values()))['state'],'CONFIRMING')
        self.pick['history'].append({'timestamp':(self.now+timedelta(minutes=5)).isoformat()})
        self.assertEqual(next(iter(self.update(5).values()))['state'],'READY')

    def test_ev_alone_cannot_trigger_entry(self):
        for field,value in [('confidenceScore',20),('modelEdge',0),('betsPct',0),('stake',0),('marketSignal','NO_ACTION')]:
            record=next(iter(self.update(pick={**self.pick,field:value,'ev':90}).values()))
            self.assertNotIn(record['state'],{'READY','CANDIDATE'})

    def test_out_of_order_reading_cannot_confirm_entry(self):
        self.update()
        self.pick['history']=self.pick['history'][:1]
        record=next(iter(self.update(1).values()))
        self.assertEqual(record['state'],'STALE')
        self.assertEqual(record['confirmations'],0)

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
        self.assertEqual(records[changed['trackingId']]['state'],'WAITING')

    def test_price_comparison_handles_positive_negative_boundary(self):
        self.assertLess(decimal_odds('-110'),decimal_odds('+100'))
        self.assertIsNone(decimal_odds('0'))
