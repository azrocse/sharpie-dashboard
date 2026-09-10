"""Suscripción general explícita. Secretos y destinatarios solo en .runtime."""
from datetime import datetime
from html import escape
import json
from pathlib import Path
import re
import unicodedata
import requests

from storage import atomic_write_json
from tracking import MAX_AGE_MINUTES, timestamp, read_state, number
from opportunities import CDMX

DASHBOARD_URL = 'https://azrocse.github.io/sharpie-dashboard/'


def load_config(runtime):
    path = Path(runtime) / 'telegram.json'
    if not path.exists():
        return None
    config = json.loads(path.read_text(encoding='utf-8'))
    if not config.get('enabled'):
        return None
    if not re.fullmatch(r'[A-Za-z0-9_]{5,32}', config.get('username', '')) or not config.get('token'):
        raise ValueError('Configuración Telegram incompleta.')
    if not config.get('publicSubscriptions') and not config.get('allowedChatIds'):
        raise ValueError('Falta configurar quién puede suscribirse a Telegram.')
    return config


def subscription_url(runtime):
    config = load_config(runtime)
    return f"https://t.me/{config['username']}?start=alerts" if config else None


class TelegramError(Exception):
    def __init__(self, code=0):
        self.code = code
        super().__init__(f'Telegram no disponible (código {code}); se reintentará.')


class Bot:
    def __init__(self, token):
        self.token = token

    def call(self, method, payload):
        try:
            response = requests.post(f'https://api.telegram.org/bot{self.token}/{method}',
                                     json=payload, timeout=max(15, payload.get('timeout', 0) + 10))
            body = response.json()
        except (requests.RequestException, ValueError):
            raise TelegramError() from None
        if not response.ok or not body.get('ok'):
            raise TelegramError(body.get('error_code', response.status_code))
        return body['result']

    def send(self, chat, text, keyboard=None):
        payload = {'chat_id': chat, 'text': text, 'parse_mode': 'HTML',
                   'link_preview_options': {'is_disabled': True}}
        if keyboard:
            payload['reply_markup'] = {'inline_keyboard': keyboard}
        return self.call('sendMessage', payload)

    def edit(self, chat, message_id, text, keyboard=None):
        payload = {'chat_id': chat, 'message_id': message_id, 'text': text, 'parse_mode': 'HTML',
                   'link_preview_options': {'is_disabled': True}}
        if keyboard:
            payload['reply_markup'] = {'inline_keyboard': keyboard}
        return self.call('editMessageText', payload)

    def delete(self, chat, message_id):
        return self.call('deleteMessage', {'chat_id': chat, 'message_id': message_id})


def controls(active):
    return [[{'text': 'Pausar avisos' if active else 'Activar avisos',
              'callback_data': 'pause' if active else 'resume'}]]


def team_hashtag(value):
    """Quita la abreviatura geográfica del feed, conservando nombres de club."""
    text = str(value or '').strip()
    match = re.match(r'^([A-Z]{2,4})\s+(.+)$', text)
    club_prefixes = {'AC', 'AFC', 'CA', 'CD', 'CF', 'FC', 'RC', 'SC'}
    if match and match.group(1) not in club_prefixes:
        text = match.group(2)
    ascii_text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode()
    return '#' + re.sub(r'[^A-Za-z0-9]', '', ascii_text)


def message_for(record):
    current = record.get('current') or {}
    category = record.get('pickCategory') or 'FREE'
    icon, tag = {'FREE': ('🔓', '#FreePick'), 'PREMIUM': ('💎', '#PremiumPick'), 'WHALE': ('🐋', '#WhalePick')}.get(category, ('🎯', '#Pick'))
    clean = lambda value: escape(str(value or '—')[:200])
    kickoff = timestamp(record.get('iso'))
    when = kickoff.strftime('%Y-%m-%d | ⏰ %H:%M') if kickoff else 'Por confirmar'
    stake = number(current.get('stake'))
    stake_text = f'{stake:.1f}u' if stake is not None else '—'
    ev = number(current.get('ev'))
    ev_text = f'{ev:+.2f}%' if ev is not None else '—'
    model_prob = number(current.get('modelProb'))
    model_prob_text = f'{model_prob:.2f}%' if model_prob is not None else '—'
    teams = f"{team_hashtag(record.get('away'))} vs {team_hashtag(record.get('home'))}" if record.get('away') and record.get('home') else clean(record.get('game'))
    prefix = {'NO_VALUE': '🔴 <b>YA NO APOSTAR</b>\n', 'RECOVERED': '🟢 <b>VALOR RECUPERADO</b>\n', 'UPGRADED': '⬆️ <b>PICK MEJORADO</b>\n', 'DOWNGRADED': '⬇️ <b>PICK AJUSTADO</b>\n'}.get(record.get('telegramStatus'), '')
    return (f"{prefix}{icon} <b>{tag}</b>\n"
            f"📅 {when}\n🏆 {clean(record.get('league') or 'SPORTS')}\n🏟️ {teams}\n"
            f"🎯 Pick: {clean(record.get('pick'))} ({clean(record.get('market'))})\n"
            f"💵 Cuota: {clean(current.get('odds'))}\n📈 EV: {ev_text}\n"
            f"🧠 Prob. Modelo: {model_prob_text}\n💰 Stake: {stake_text}")


def load_subscribers(path):
    if not path.exists():
        return {'schemaVersion': 2, 'offset': 0, 'subscribers': {}}
    state = json.loads(path.read_text(encoding='utf-8'))
    if state.get('schemaVersion') == 2 and isinstance(state.get('subscribers'), dict):
        return state
    if isinstance(state.get('subscriptions'), dict):
        # Un permiso para un pick no autoriza avisos de todos los picks.
        subscribers = {}
        for old in state['subscriptions'].values():
            sub = subscribers.setdefault(str(old['chatId']), {'active': False, 'sent': {}})
            if old.get('lastReady') and old.get('lastSentAt'):
                sub['sent'][old['trackingId']] = old['lastSentAt']
        return {'schemaVersion': 2, 'offset': state.get('offset', 0), 'subscribers': subscribers}
    raise ValueError('Estado Telegram inválido; no se sobrescribe.')


def eligible(record, now):
    observed = timestamp(record.get('lastObservation'))
    kickoff = timestamp(record.get('iso'))
    return (record.get('state') == 'READY' and kickoff is not None and kickoff > now
            and (kickoff-now).total_seconds() <= 24*60*60
            and observed is not None and 0 <= (now-observed).total_seconds() <= MAX_AGE_MINUTES*60)


def run_alerts(runtime, tracking=None, now=None, bot=None, config=None, poll_timeout=0):
    config = config or load_config(runtime)
    if not config:
        return {'configured': False, 'sent': 0}
    bot = bot or Bot(config['token'])
    path = Path(runtime) / 'telegram-state.json'
    state = load_subscribers(path)
    subscribers = state['subscribers']
    allowed = {str(chat) for chat in config.get('allowedChatIds', [])}
    permitted = lambda chat: chat.get('type') == 'private' and (config.get('publicSubscriptions') or str(chat.get('id')) in allowed)
    updates = bot.call('getUpdates', {'offset': state['offset'], 'timeout': poll_timeout,
                                    'limit': 100, 'allowed_updates': ['message', 'callback_query']})
    for update in updates:
        callback = update.get('callback_query')
        msg = callback.get('message', {}) if callback else update.get('message', {})
        chat = msg.get('chat', {})
        chat_id = str(chat.get('id', ''))
        authorized = permitted(chat) and (not callback or str(callback.get('from', {}).get('id')) == chat_id)
        if callback:
            try:
                bot.call('answerCallbackQuery', {'callback_query_id': callback['id']})
            except TelegramError as error:
                if error.code != 400:  # Un botón vencido no debe bloquear la pausa.
                    raise
        try:
            if authorized:
                command = callback.get('data', '') if callback else re.sub(r'^(/\w+)@\w+', r'\1', msg.get('text', '').strip())
                activate = command in {'/start', '/start alerts', '/resume', 'resume'}
                pause = command in {'/stop', '/pause', 'pause'} or command.startswith('/stop ')
                if activate or pause:
                    sub = subscribers.setdefault(chat_id, {'active': False, 'sent': {}})
                    if pause:
                        sub['active'] = False
                        atomic_write_json(path, state, compact=True)
                    bot.send(chat_id,
                             '🔔 <b>Avisos activados</b>\nRecibirás los picks cuando tengan valor.' if activate else
                             '🔕 <b>Avisos pausados</b>\nPuedes reactivarlos cuando quieras.', controls(activate))
                    sub['active'] = activate
                else:
                    active = subscribers.get(chat_id, {}).get('active', False)
                    bot.send(chat_id, '🎯 <b>Picks por Telegram</b>\nActiva los avisos para recibir todos los picks con valor.'
                             if not active else '🔔 <b>Tus avisos están activos</b>\nTe avisaremos cuando un pick tenga valor.', controls(active))
        except TelegramError as error:
            if error.code != 403:
                raise
            if chat_id in subscribers:
                subscribers[chat_id]['active'] = False
        state['offset'] = update['update_id'] + 1
        atomic_write_json(path, state, compact=True)

    # Leer después del long polling: nunca enviar con una copia vieja del feed.
    now = now or datetime.now(CDMX)
    tracking = tracking if tracking is not None else read_state(Path(runtime) / 'tracking.json')
    records = sorted(tracking['records'].values(), key=lambda r: r.get('iso') or '')
    record_map = {record['trackingId']: record for record in records}
    sent = 0
    for chat_id, sub in subscribers.items():
        if not sub.get('active') or not (config.get('publicSubscriptions') or chat_id in allowed):
            continue
        for record in records:
            key = record['trackingId']
            for alias in record.get('legacyTrackingIds') or []:
                legacy = sub.get('sent', {}).pop(alias, None)
                if legacy is None:
                    continue
                current = sub['sent'].get(key)
                if current is None:
                    sub['sent'][key] = legacy
                    if isinstance(legacy, dict) and legacy.get('messageId'):
                        try:
                            bot.edit(chat_id, legacy['messageId'], message_for(record),
                                     [[{'text': 'Ver pick ↗', 'url': f'{DASHBOARD_URL}?pick={key}'}], *controls(True)])
                        except TelegramError as error:
                            if error.code not in {400, 403}:
                                raise
                elif isinstance(legacy, dict) and legacy.get('messageId') and (
                    not isinstance(current, dict) or legacy.get('messageId') != current.get('messageId')
                ):
                    try:
                        bot.delete(chat_id, legacy['messageId'])
                    except TelegramError as error:
                        if error.code not in {400, 403}:
                            raise
        for key, delivery in list(sub.get('sent', {}).items()):
            if not isinstance(delivery, dict) or not delivery.get('messageId'):
                continue
            record = record_map.get(key)
            kickoff = timestamp(record.get('iso')) if record else None
            try:
                if not record or (kickoff and kickoff <= now):
                    bot.delete(chat_id, delivery['messageId'])
                    del sub['sent'][key]
                    continue
                desired = 'READY' if record.get('state') == 'READY' else 'NO_VALUE'
                category = record.get('pickCategory')
                state_changed = delivery.get('state') != desired
                category_changed = desired == 'READY' and delivery.get('category') != category
                if state_changed or category_changed:
                    changed = dict(record)
                    if state_changed:
                        changed['telegramStatus'] = 'RECOVERED' if desired == 'READY' else 'NO_VALUE'
                    else:
                        rank = {'FREE': 1, 'PREMIUM': 2, 'WHALE': 3}
                        changed['telegramStatus'] = ('UPGRADED' if rank.get(category, 0) > rank.get(delivery.get('category'), 0)
                                                     else 'DOWNGRADED')
                    bot.edit(chat_id, delivery['messageId'], message_for(changed),
                             [[{'text': 'Ver pick ↗', 'url': f'{DASHBOARD_URL}?pick={key}'}], *controls(True)])
                    delivery.update(state=desired, category=category, updatedAt=now.isoformat())
            except TelegramError as error:
                if error.code not in {400, 403}:
                    raise
        for record in records:
            key = record['trackingId']
            if key in sub['sent'] or not eligible(record, now):
                continue
            try:
                response = bot.send(chat_id, message_for(record),
                                    [[{'text': 'Ver pick ↗', 'url': f'{DASHBOARD_URL}?pick={key}'}], *controls(True)])
            except TelegramError as error:
                if error.code != 403:
                    raise
                sub['active'] = False
                break
            sub['sent'][key] = {'sentAt': now.isoformat(), 'messageId': response.get('message_id') if isinstance(response, dict) else None,
                                'state': 'READY', 'category': record.get('pickCategory')}
            sent += 1
        atomic_write_json(path, state, compact=True)
        if sent >= 20:
            break
    atomic_write_json(path, state, compact=True)
    return {'configured': True, 'sent': sent}
