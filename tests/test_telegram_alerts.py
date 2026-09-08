from datetime import datetime,timedelta
from pathlib import Path
import tempfile
import unittest
import json
from opportunities import CDMX
from telegram_alerts import run_alerts,TelegramError,attach_links


class FakeBot:
    def __init__(self,updates=()): self.updates=list(updates); self.sent=[]; self.fail=False
    def call(self,method,payload): return [u for u in self.updates if u['update_id']>=payload['offset']]
    def send(self,chat,text):
        if self.fail: raise TelegramError(500)
        self.sent.append((chat,text))


class TelegramTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.now=datetime(2026,9,7,12,tzinfo=CDMX)
        self.key='a'*24
        self.record={'trackingId':self.key,'game':'A vs B','pick':'A','market':'Moneyline','iso':'2026-09-07T15:00:00',
                     'state':'READY','current':{'odds':'+110','ev':10,'modelEdge':5},'lastObservation':self.now.isoformat(),'reasons':['Confirmado']}
        self.data={'records':{self.key:self.record}}
        self.config={'token':'secret','username':'sample_bot','allowedChatIds':['1'],'publicSubscriptions':False}
        self.bot=FakeBot([{'update_id':1,'message':{'chat':{'id':1,'type':'private'},'text':'/start pick_'+self.key}}])

    def run_cycle(self,now=None):
        return run_alerts(self.root,self.data,now or self.now,bot=self.bot,config=self.config)

    def test_subscribe_alert_once_then_invalidate_and_close(self):
        self.run_cycle()
        self.assertEqual(len(self.bot.sent),2)
        self.run_cycle()
        self.assertEqual(len(self.bot.sent),2)
        self.record['state']='NO_VALUE'
        self.run_cycle()
        self.assertIn('Ya no cumple',self.bot.sent[-1][1])
        self.run_cycle()
        self.assertEqual(len(self.bot.sent),3)
        self.run_cycle(self.now+timedelta(hours=3))
        self.assertIn('cerrado',self.bot.sent[-1][1])

    def test_failed_delivery_is_retried_without_marking_sent(self):
        self.run_cycle()
        self.record['state']='NO_VALUE'; self.bot.fail=True
        with self.assertRaises(TelegramError): self.run_cycle()
        state=json.loads((self.root/'telegram-state.json').read_text())
        self.assertEqual(next(iter(state['subscriptions'].values()))['lastState'],'READY')
        self.bot.fail=False; self.run_cycle()
        self.assertIn('Ya no cumple',self.bot.sent[-1][1])

    def test_stop_and_unauthorized_chat(self):
        self.run_cycle()
        self.bot.updates.append({'update_id':2,'message':{'chat':{'id':1,'type':'private'},'text':'/stop'}})
        self.run_cycle()
        self.assertFalse(json.loads((self.root/'telegram-state.json').read_text())['subscriptions'])
        self.bot.updates.append({'update_id':3,'message':{'chat':{'id':2,'type':'private'},'text':'/start pick_'+self.key}})
        count=len(self.bot.sent); self.run_cycle(); self.assertEqual(len(self.bot.sent),count)

    def test_stale_ready_never_sends_positive_alert(self):
        self.run_cycle(self.now+timedelta(minutes=20))
        self.assertEqual(len(self.bot.sent),1)

    def test_significant_improvement_requires_cooldown_and_new_reading(self):
        self.run_cycle()
        self.record['current'].update(ev=13,modelEdge=7)
        self.record['lastObservation']=(self.now+timedelta(minutes=5)).isoformat()
        self.run_cycle(self.now+timedelta(minutes=5))
        self.assertEqual(len(self.bot.sent),2)
        self.record['lastObservation']=(self.now+timedelta(minutes=30)).isoformat()
        self.run_cycle(self.now+timedelta(minutes=30))
        self.assertIn('Mejora de la oportunidad',self.bot.sent[-1][1])
        self.run_cycle(self.now+timedelta(minutes=30))
        self.assertEqual(len(self.bot.sent),3)

    def test_public_link_does_not_contain_credentials(self):
        (self.root/'telegram.json').write_text(json.dumps({**self.config,'enabled':True}))
        picks=[{'trackingId':self.key}];attach_links(picks,self.root)
        self.assertEqual(picks[0]['telegramUrl'],'https://t.me/sample_bot?start=pick_'+self.key)
        self.assertNotIn('secret',json.dumps(picks))
