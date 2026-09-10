"""Seguimiento persistente prepartido; no depende de un navegador o suscripción."""
from copy import deepcopy
from datetime import datetime
import json
import math
from pathlib import Path

from opportunities import CDMX, _event_time, _identity
from storage import atomic_write_json

MAX_AGE_MINUTES = 15
METRICS = ('odds', 'modelProb', 'modelEdge', 'ev', 'stake', 'betsPct', 'handlePct',
           'divergence', 'marketSignal')


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def timestamp(value):
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return result.replace(tzinfo=CDMX) if result.tzinfo is None else result.astimezone(CDMX)
    except (ValueError, TypeError):
        return None


def decimal_odds(value):
    odds = number(value)
    if odds is None or abs(odds) < 100:
        return None
    return 1 + (odds / 100 if odds > 0 else 100 / abs(odds))


def read_state(path):
    path = Path(path)
    if not path.exists():
        return {'schemaVersion': 1, 'records': {}}
    payload = json.loads(path.read_text(encoding='utf-8'))
    if payload.get('schemaVersion') != 1 or not isinstance(payload.get('records'), dict):
        raise ValueError('Estado de seguimiento inválido; no se sobrescribe.')
    # Migra estados anteriores sin arrastrar la métrica descartada al HTML/JSON.
    for record in payload['records'].values():
        for section in ('current', 'previous', 'firstEvaluation'):
            if isinstance(record.get(section), dict):
                record[section].pop('confidenceScore', None)
    return payload


def assess(pick, now):
    kickoff = _event_time(pick)
    observations = [timestamp(h.get('timestamp') or h.get('time')) for h in pick.get('history', [])]
    observations = sorted(set(t for t in observations if t and t <= now))
    observed = observations[-1] if observations else None
    minutes = (kickoff-now).total_seconds()/60 if kickoff else None
    if minutes is not None and minutes <= 0:
        return 'CLOSED', ['El encuentro ya comenzó.'], observed
    if observed is None or (now-observed).total_seconds()/60 > MAX_AGE_MINUTES:
        return 'STALE', ['Actualizando datos.'], observed
    if minutes is None or decimal_odds(pick.get('odds')) is None:
        return 'INCOMPLETE', ['Actualizando datos.'], observed
    # El analizador del dashboard es la única autoridad de valor.
    # Aquí solo se protege contra lecturas antiguas o encuentros iniciados.
    if pick.get('actionKey') != 'bet' or pick.get('pickCategory') not in {'FREE', 'PREMIUM', 'WHALE'}:
        return 'NO_VALUE', [], observed
    return 'READY', [], observed


def update_tracking(picks, path, now=None, feed_ok=True):
    now = now or datetime.now(CDMX)
    now = now.replace(tzinfo=CDMX) if now.tzinfo is None else now.astimezone(CDMX)
    payload = read_state(path)
    records = {}
    for old_key, record in payload['records'].items():
        kickoff = timestamp(record.get('iso'))
        key = _identity(record, kickoff) if kickoff else record.get('trackingId')
        aliases = set(record.get('legacyTrackingIds') or [])
        if old_key and old_key != key:
            aliases.add(old_key)
        record['legacyTrackingIds'] = sorted(aliases)
        record['trackingId'] = key
        current = records.get(key)
        if current is None:
            records[key] = record
            continue
        exact = record if record.get('league') != 'SPORTS' else current
        other = current if exact is record else record
        if timestamp(other.get('firstObservedAt')) and (
            not timestamp(exact.get('firstObservedAt'))
            or timestamp(other.get('firstObservedAt')) < timestamp(exact.get('firstObservedAt'))
        ):
            exact['firstObservedAt'], exact['initial'] = other.get('firstObservedAt'), deepcopy(other.get('initial'))
        if timestamp(other.get('firstEvaluatedAt')) and (
            not timestamp(exact.get('firstEvaluatedAt'))
            or timestamp(other.get('firstEvaluatedAt')) < timestamp(exact.get('firstEvaluatedAt'))
        ):
            exact['firstEvaluatedAt'], exact['firstEvaluation'] = other.get('firstEvaluatedAt'), deepcopy(other.get('firstEvaluation'))
        exact['legacyTrackingIds'] = sorted(set(exact.get('legacyTrackingIds') or []) | set(other.get('legacyTrackingIds') or []))
        records[key] = exact
    payload['records'] = records
    seen = set()
    for pick in picks:
        kickoff = _event_time(pick)
        if kickoff is None:
            continue
        key = _identity(pick, kickoff)
        seen.add(key)
        current = {field: deepcopy(pick.get(field)) for field in METRICS}
        old = records.get(key)
        if old is None:
            points = [(timestamp(h.get('timestamp') or h.get('time')), h) for h in pick.get('history', [])]
            points = sorted([(t,h) for t,h in points if t and t<=now], key=lambda pair:pair[0])
            first_time, first = points[0] if points else (now, {})
            baseline = {field: first.get(field) for field in ('odds','betsPct','handlePct')}
            old = records[key] = {
                'trackingId': key, 'game': pick.get('game'), 'away': pick.get('away'), 'home': pick.get('home'), 'pick': pick.get('pick'),
                'market': pick.get('market'), 'league': pick.get('league'), 'iso': pick.get('iso'),
                'firstObservedAt': first_time.isoformat(), 'initial': baseline,
                'firstEvaluatedAt': now.isoformat(), 'firstEvaluation': deepcopy(current),
                'lastObservation': None, 'state': None,
            }
        state, reasons, observed = assess(pick, now)
        observed_text = observed.isoformat() if observed else None
        previous_observed = timestamp(old.get('lastProcessedObservation') or old.get('lastObservation'))
        new_observation = observed is not None and (previous_observed is None or observed > previous_observed)
        if observed and previous_observed and observed < previous_observed:
            state, reasons = 'STALE', ['La lectura recibida es anterior a la última procesada.']
        if new_observation:
            misses = 0 if state == 'READY' else int(old.get('consecutiveMisses') or 0) + 1
            old['consecutiveMisses'] = misses
            if state != 'READY' and old.get('state') == 'READY' and misses < 2:
                state, reasons = 'READY', []
        old.pop('confirmations', None)
        if new_observation:
            old['previous'] = old.get('current')
        old.update(game=pick.get('game'), away=pick.get('away'), home=pick.get('home'),
                   pick=pick.get('pick'), market=pick.get('market'), league=pick.get('league'),
                   current=current, state=state, reasons=reasons, lastObservation=observed_text,
                   freeRelease=bool(pick.get('freeRelease')), pickCategory=pick.get('pickCategory'),
                   lastProcessedObservation=max(observed, previous_observed).isoformat() if observed and previous_observed else observed_text,
                   evaluatedAt=now.isoformat(), lastSeenAt=now.isoformat(), iso=pick.get('iso'))
        first_odds = decimal_odds(old['initial'].get('odds'))
        current_odds = decimal_odds(current.get('odds'))
        old['priceChangePct'] = round((current_odds/first_odds-1)*100,2) if first_odds and current_odds else None
        pick['trackingId'] = key
        pick['tracking'] = {field: deepcopy(old.get(field)) for field in (
            'firstObservedAt','initial','firstEvaluatedAt','firstEvaluation','previous',
            'state','reasons','lastObservation','evaluatedAt','priceChangePct','legacyTrackingIds')}
    for key, record in records.items():
        if key in seen:
            continue
        kickoff = timestamp(record.get('iso'))
        record.update(state='CLOSED' if kickoff and kickoff<=now else 'UNAVAILABLE',
                      reasons=['El encuentro ya comenzó.'] if kickoff and kickoff<=now else
                              ['El pick no está disponible en la lectura actual.' if feed_ok else 'Falló la actualización de datos.'],
                      evaluatedAt=now.isoformat())
        record.pop('confirmations', None)
    payload['updatedAt'] = now.isoformat()
    atomic_write_json(path, payload, compact=True)
    return payload
