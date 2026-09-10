from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
import json
from opportunities import CDMX
from telegram_alerts import run_alerts, TelegramError, subscription_url, message_for, team_hashtag, Bot
from unittest.mock import patch


class FakeBot:
    def __init__(self, updates=()):
        self.updates=list(updates); self.sent=[]; self.edited=[]; self.deleted=[]; self.fail=0; self.answered=[]

    def call(self, method, payload):
        if method == 'answerCallbackQuery':
            self.answered.append(payload); return True
        return [u for u in self.updates if u['update_id'] >= payload['offset']]

    def send(self, chat, text, keyboard=None):
        if self.fail: raise TelegramError(self.fail)
        self.sent.append((chat, text, keyboard))
        return {'message_id': len(self.sent)}

    def edit(self, chat, message_id, text, keyboard=None):
        self.edited.append((chat, message_id, text, keyboard)); return True

    def delete(self, chat, message_id):
        self.deleted.append((chat, message_id))
        return True


class TelegramTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.now=datetime(2026,9,7,12,tzinfo=CDMX)
        self.key='a'*24
        self.record={'trackingId':self.key,'game':'A vs B','pick':'A','market':'Moneyline',
                     'iso':'2026-09-07T15:00:00','state':'READY','freeRelease':True,'pickCategory':'FREE',
                     'current':{'odds':'+110','ev':10,'modelProb':58.72,'modelEdge':5,'stake':1.5},'lastObservation':self.now.isoformat()}
        self.data={'records':{self.key:self.record}}
        self.config={'token':'secret','username':'sample_bot','allowedChatIds':['1'],'publicSubscriptions':False}
        self.bot=FakeBot()
        self.command('/start alerts')

    def command(self, text, chat=1, callback=False):
        msg={'chat':{'id':chat,'type':'private'},'text':text}
        item={'update_id':len(self.bot.updates)+1}
        if callback:
            item['callback_query']={'id':str(item['update_id']),'from':{'id':chat},'message':msg,'data':text}
        else: item['message']=msg
        self.bot.updates.append(item)

    def run_cycle(self, now=None):
        return run_alerts(self.root,self.data,now or self.now,bot=self.bot,config=self.config)

    def state(self):
        return json.loads((self.root/'telegram-state.json').read_text())

    def test_value_message_is_removed_and_republished_when_value_returns(self):
        self.run_cycle()
        self.assertEqual(len(self.bot.sent),2)
        self.assertIn('Avisos activados',self.bot.sent[0][1])
        self.assertIn('#FreePick',self.bot.sent[1][1])
        self.run_cycle()
        self.record['state']='NO_VALUE'; self.run_cycle()
        delivery=self.state()['subscribers']['1']['sent'][self.key]
        self.assertEqual(delivery['state'],'NO_VALUE')
        self.assertIsNone(delivery['messageId'])
        self.assertEqual(self.bot.deleted,[('1',2)])
        self.record['state']='READY'; self.run_cycle()
        self.assertEqual(len(self.bot.sent),3)
        self.assertIn('VALOR RECUPERADO',self.bot.sent[-1][1])
        delivery=self.state()['subscribers']['1']['sent'][self.key]
        self.assertEqual(delivery['state'],'READY')
        self.assertEqual(delivery['messageId'],3)
        self.run_cycle(self.now+timedelta(hours=3))
        self.assertEqual(self.bot.deleted,[('1',2),('1',3)])
        self.assertNotIn(self.key,self.state()['subscribers']['1']['sent'])
        self.assertEqual(self.bot.edited,[])

    def test_confirmation_does_not_require_tracking_data(self):
        self.data={'records':{}}
        self.run_cycle()
        self.assertEqual(len(self.bot.sent),1)
        self.assertTrue(self.state()['subscribers']['1']['active'])

    def test_pick_acquires_value_later(self):
        self.record['state']='NO_VALUE'; self.run_cycle()
        self.assertEqual(len(self.bot.sent),1)
        self.record['state']='READY'; self.run_cycle()
        self.assertEqual(len(self.bot.sent),2)

    def test_pause_resume_and_queue_dedup(self):
        second={**self.record,'trackingId':'b'*24,'pick':'B'}
        self.data['records'][second['trackingId']]=second
        self.run_cycle()
        self.command('pause',callback=True); self.run_cycle()
        self.assertFalse(self.state()['subscribers']['1']['active'])
        self.assertEqual(len(self.bot.sent),4)
        self.command('resume',callback=True); self.run_cycle()
        self.assertEqual(len(self.bot.sent),5)
        self.assertIn('Avisos activados',self.bot.sent[-1][1])
        self.run_cycle(); self.assertEqual(len(self.bot.sent),5)
        self.assertEqual(len(self.bot.answered),2)

    def test_failed_pick_delivery_is_retried(self):
        self.record['state']='NO_VALUE'; self.run_cycle()
        self.record['state']='READY'; self.bot.fail=500
        with self.assertRaises(TelegramError): self.run_cycle()
        self.assertFalse(self.state()['subscribers']['1']['sent'])
        self.bot.fail=0; self.run_cycle()
        self.assertIn(self.key,self.state()['subscribers']['1']['sent'])

    def test_blocked_bot_disables_subscription(self):
        self.record['state']='NO_VALUE'; self.run_cycle()
        self.record['state']='READY'; self.bot.fail=403; self.run_cycle()
        self.assertFalse(self.state()['subscribers']['1']['active'])

    def test_stop_and_unauthorized_chat(self):
        self.run_cycle(); self.command('/stop'); self.run_cycle()
        self.assertFalse(self.state()['subscribers']['1']['active'])
        self.command('/start alerts',chat=2)
        count=len(self.bot.sent); self.run_cycle(); self.assertEqual(len(self.bot.sent),count)

    def test_stale_future_observation_and_closed_never_send_value(self):
        self.run_cycle(self.now+timedelta(minutes=20))
        self.run_cycle(self.now-timedelta(minutes=1))
        self.run_cycle(self.now+timedelta(hours=3))
        self.assertEqual(len(self.bot.sent),1)

    def test_migration_does_not_expand_previous_consent(self):
        self.bot.updates=[]
        (self.root/'telegram-state.json').write_text(json.dumps({'offset':12,'subscriptions':{
            '1:'+self.key:{'chatId':'1','trackingId':self.key,'lastReady':{},'lastSentAt':None}}}))
        self.run_cycle()
        self.assertEqual(self.bot.sent,[])
        self.assertFalse(self.state()['subscribers']['1']['active'])
        self.assertEqual(self.state()['offset'],12)

    def test_old_pick_link_requires_general_opt_in(self):
        self.bot.updates=[]; self.command('/start pick_'+self.key); self.run_cycle()
        self.assertEqual(len(self.bot.sent),1)
        self.assertFalse(self.state()['subscribers'])
        self.assertEqual(self.bot.sent[0][2][0][0]['callback_data'],'resume')

    def test_public_link_has_no_credentials_and_message_escapes_html(self):
        (self.root/'telegram.json').write_text(json.dumps({**self.config,'enabled':True}))
        self.assertEqual(subscription_url(self.root),'https://t.me/sample_bot?start=alerts')
        self.record.update(game='<A> & B',pick='<A>')
        msg=message_for(self.record)
        self.assertIn('&lt;A&gt; &amp; B',msg)
        self.assertIn('1.5u',msg)
        self.assertIn('📈 EV: +10.00%',msg)
        self.assertIn('🧠 Prob. Modelo: 58.72%',msg)
        self.assertLess(len(msg),350)
        with patch.object(Bot,'call') as call:
            Bot('secret').send('1',msg,[[{'text':'Pausar','callback_data':'pause'}]])
            payload=call.call_args.args[1]
            self.assertEqual(payload['parse_mode'],'HTML')
            self.assertIn('inline_keyboard',payload['reply_markup'])

    def test_team_hashtags_remove_feed_city_codes_only(self):
        self.assertEqual(team_hashtag('HOU Astros'), '#Astros')
        self.assertEqual(team_hashtag('LA Rams'), '#Rams')
        self.assertEqual(team_hashtag('Real Madrid'), '#RealMadrid')
        self.assertEqual(team_hashtag('FC Barcelona'), '#FCBarcelona')
