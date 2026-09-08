"""Suscripciones explícitas por enlace /start; secretos y chats solo en .runtime."""
from datetime import datetime
import json
from pathlib import Path
import re
import requests

from storage import atomic_write_json
from tracking import DEFAULT_POLICY, timestamp, number
from opportunities import CDMX


def load_config(runtime):
    path = Path(runtime)/'telegram.json'
    if not path.exists():
        return None
    config = json.loads(path.read_text(encoding='utf-8'))
    if not config.get('enabled'):
        return None
    if not re.fullmatch(r'[A-Za-z0-9_]{5,32}', config.get('username','')) or not config.get('token'):
        raise ValueError('Configuración Telegram incompleta.')
    if not config.get('publicSubscriptions') and not config.get('allowedChatIds'):
        raise ValueError('Falta configurar quién puede suscribirse a Telegram.')
    return config


def attach_links(picks, runtime):
    config = load_config(runtime)
    for pick in picks:
        if config and pick.get('trackingId'):
            pick['telegramUrl'] = f"https://t.me/{config['username']}?start=pick_{pick['trackingId']}"


class TelegramError(Exception):
    def __init__(self, code=0):
        self.code=code
        super().__init__(f'Telegram no disponible (código {code}); se reintentará.')


class Bot:
    def __init__(self, token):
        self.token=token

    def call(self, method, payload):
        try:
            response=requests.post(f'https://api.telegram.org/bot{self.token}/{method}', json=payload, timeout=15)
            body=response.json()
        except (requests.RequestException, ValueError):
            raise TelegramError() from None
        if not response.ok or not body.get('ok'):
            raise TelegramError(body.get('error_code', response.status_code))
        return body['result']

    def send(self, chat, text):
        return self.call('sendMessage', {'chat_id':chat,'text':text[:4000]})


def message_for(record, kind):
    labels={'READY':'Cumple criterios de entrada', 'IMPROVED':'Mejora de la oportunidad',
            'LOST':'Ya no cumple criterios de entrada', 'CLOSED':'Seguimiento prepartido cerrado',
            'UNAVAILABLE':'Actualización no disponible'}
    current=record.get('current') or {}
    lines=[f"SharpIE · {labels[kind]}",str(record.get('game','')),f"{record.get('pick','')} · {record.get('market','')}",
           f"Inicio: {record.get('iso','')} (CDMX)",
           f"Cuota: {current.get('odds')} | Stake: {current.get('stake')} u",
           f"Modelo: {current.get('modelProb')}% | Edge: {current.get('modelEdge')}% | EV: {current.get('ev')}%",
           f"Bets: {current.get('betsPct')}% | Handle: {current.get('handlePct')}% | Divergencia: {current.get('divergence')}",
           f"Señal: {current.get('marketSignal')}",
           f"Lectura: {record.get('lastObservation') or 'sin lectura reciente'}",
           ' '.join(record.get('reasons',[])),
           'La evaluación corresponde a esa cuota y lectura; confirma la cuota disponible.',
           f"Cancelar: /stop {record['trackingId']}"]
    return '\n'.join(lines)


def run_alerts(runtime, tracking, now=None, bot=None, config=None):
    config=config or load_config(runtime)
    if not config:
        return {'configured':False,'sent':0}
    now=now or datetime.now(CDMX)
    bot=bot or Bot(config['token'])
    path=Path(runtime)/'telegram-state.json'
    state=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'offset':0,'subscriptions':{}}
    subscriptions=state['subscriptions']
    records=tracking['records']
    allowed={str(chat) for chat in config.get('allowedChatIds',[])}
    updates=bot.call('getUpdates',{'offset':state['offset'],'timeout':0,'limit':100,'allowed_updates':['message']})
    for update in updates:
        msg=update.get('message',{})
        chat=msg.get('chat',{})
        chat_id=str(chat.get('id',''))
        permitted=chat.get('type')=='private' and (config.get('publicSubscriptions') or chat_id in allowed)
        if permitted:
            text=msg.get('text','').strip()
            subscribe=re.fullmatch(r'/start(?:@\w+)? pick_([a-f0-9]{24})',text)
            stop=re.fullmatch(r'/stop(?:@\w+)?(?: ([a-f0-9]{24}))?',text)
            if subscribe:
                key=subscribe[1]
                record=records.get(key)
                if not record or record['state']=='CLOSED':
                    bot.send(chat_id,'Este pick no está disponible para seguimiento prepartido.')
                else:
                    subkey=f'{chat_id}:{key}'
                    if subkey not in subscriptions:
                        subscriptions[subkey]={'chatId':chat_id,'trackingId':key,'lastState':None,'lastSentAt':None,'lastReady':None}
                    bot.send(chat_id,f"Avisos activados para {record['game']} · {record['pick']}.\nSe revisa en cada procesamiento, aproximadamente cada 5 minutos.\nCancelar: /stop {key}")
            elif stop:
                subscriptions={key:sub for key,sub in subscriptions.items() if not (sub['chatId']==chat_id and (not stop[1] or sub['trackingId']==stop[1]))}
                state['subscriptions']=subscriptions
                bot.send(chat_id,'Suscripción cancelada.' if stop[1] else 'Todas tus suscripciones fueron canceladas.')
            elif text.startswith(('/start','/help','/settings')):
                bot.send(chat_id,'Abre un pick en el dashboard y pulsa «Avisarme por Telegram». Confirma Iniciar aquí para suscribirte. /stop cancela todos tus avisos.')
        state['offset']=update['update_id']+1
        atomic_write_json(path,state,compact=True)
    sent=0
    for key,sub in list(subscriptions.items()):
        if key not in subscriptions:
            continue
        if not config.get('publicSubscriptions') and sub['chatId'] not in allowed:
            continue
        record=records.get(sub['trackingId'])
        if not record:
            continue
        current_state=record['state']
        # Never send a positive alert from a stale stored READY state.
        observed=timestamp(record.get('lastObservation'))
        kickoff=timestamp(record.get('iso'))
        if kickoff and kickoff<=now:
            current_state='CLOSED'
        elif not observed or not -60 <= (now-observed).total_seconds() <= DEFAULT_POLICY['maxAgeMinutes']*60:
            current_state='STALE'
        old_state=sub.get('lastState')
        kind=None
        if current_state=='CLOSED' and old_state!='CLOSED':
            kind='CLOSED'
        elif current_state=='READY':
            if old_state!='READY':
                kind='READY'
            else:
                previous=sub.get('lastReady') or {}
                current=record.get('current') or {}
                then=timestamp(sub.get('lastSentAt'))
                if (then and (now-then).total_seconds()>=1800 and
                    number(current.get('ev')) is not None and number(previous.get('ev')) is not None and
                    number(current.get('modelEdge')) is not None and number(previous.get('modelEdge')) is not None and
                    current['ev']>=previous['ev']+DEFAULT_POLICY['improvementEv'] and
                    current['modelEdge']>=previous['modelEdge']+DEFAULT_POLICY['improvementEdge']):
                    kind='IMPROVED'
        elif old_state=='READY':
            kind='UNAVAILABLE' if current_state in {'STALE','UNAVAILABLE','INCOMPLETE'} else 'LOST'
        if kind:
            try:
                outgoing=record
                if current_state=='STALE' and record['state']!='STALE':
                    outgoing={**record,'reasons':['La última lectura ya no es reciente; no se confirma entrada.']}
                bot.send(sub['chatId'],message_for(outgoing,kind))
            except TelegramError as error:
                if error.code==403:
                    subscriptions={k:s for k,s in subscriptions.items() if s['chatId']!=sub['chatId']}
                    state['subscriptions']=subscriptions
                    atomic_write_json(path,state,compact=True)
                    continue
                raise
            sub['lastSentAt']=now.isoformat()
            if current_state=='READY':
                sub['lastReady']=record.get('current',{}).copy()
            sent+=1
        sub['lastState']=current_state
        atomic_write_json(path,state,compact=True)
        if sent>=50:
            break
    return {'configured':True,'sent':sent}
