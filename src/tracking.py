"""Seguimiento persistente prepartido; no depende de un navegador o suscripción."""
from copy import deepcopy
from datetime import datetime
import json
import math
from pathlib import Path

from opportunities import CDMX, _event_time, _identity
from storage import atomic_write_json

DEFAULT_POLICY = {
    'minEv': 1.0, 'minEdge': 1.0, 'minStake': 1.0, 'minConfidence': 55.0,
    'minMinutes': 10, 'maxMinutes': 1440, 'maxAgeMinutes': 15,
    'confirmations': 2, 'improvementEv': 2.0, 'improvementEdge': 1.0,
}
FLOW_SIGNALS = {'SMART_MONEY', 'CONSENSUS', 'STEAM_MOVE', 'REVERSE_LINE_MOVEMENT', 'SHARP_VS_PUBLIC'}
METRICS = ('odds', 'modelProb', 'modelEdge', 'ev', 'stake', 'betsPct', 'handlePct',
           'divergence', 'marketSignal', 'confidenceScore')


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
    return payload


def assess(pick, now, policy):
    kickoff = _event_time(pick)
    observations = [timestamp(h.get('timestamp') or h.get('time')) for h in pick.get('history', [])]
    observations = sorted(set(t for t in observations if t and t <= now))
    observed = observations[-1] if observations else None
    minutes = (kickoff-now).total_seconds()/60 if kickoff else None
    if minutes is not None and minutes <= 0:
        return 'CLOSED', ['El encuentro ya comenzó.'], observed
    if observed is None or (now-observed).total_seconds()/60 > policy['maxAgeMinutes']:
        return 'STALE', ['No hay una lectura reciente; no se confirma entrada.'], observed
    numeric = {key: number(pick.get(key)) for key in METRICS if key not in {'marketSignal', 'odds'}}
    if minutes is None or decimal_odds(pick.get('odds')) is None or any(numeric[k] is None for k in numeric):
        return 'INCOMPLETE', ['Faltan datos válidos de cuota, modelo o flujo.'], observed
    if not (0 < numeric['betsPct'] <= 100 and 0 < numeric['handlePct'] <= 100 and 0 < numeric['modelProb'] <= 100):
        return 'INCOMPLETE', ['Lectura de porcentajes inválida.'], observed
    reasons = []
    if pick.get('actionKey') != 'bet' or pick.get('pickCategory') not in {'VALUE', 'PREMIUM'}:
        reasons.append('La evaluación actual no recomienda entrada.')
    for key, threshold, label in [('ev','minEv','EV'), ('modelEdge','minEdge','Edge'), ('stake','minStake','Stake'), ('confidenceScore','minConfidence','Confianza')]:
        if numeric[key] < policy[threshold]:
            reasons.append(f'{label} por debajo del mínimo configurado ({policy[threshold]}).')
    if not set(pick.get('marketSignals') or [pick.get('marketSignal')]).intersection(FLOW_SIGNALS):
        reasons.append('El flujo no presenta una señal admitida.')
    if abs((numeric['handlePct']-numeric['betsPct'])-numeric['divergence']) > .2:
        reasons.append('La divergencia no coincide con Bets y Handle.')
    if reasons:
        return 'NO_VALUE', reasons, observed
    if not policy['minMinutes'] <= minutes <= policy['maxMinutes']:
        return 'WAITING', ['Fuera de la ventana de entrada configurada.'], observed
    if len(observations) < 2:
        return 'CONFIRMING', ['Se requieren al menos dos observaciones.'], observed
    return 'CANDIDATE', ['Valor, cuota, riesgo, flujo y horario cumplen los criterios configurados.'], observed


def update_tracking(picks, path, now=None, policy=None, feed_ok=True):
    now = now or datetime.now(CDMX)
    now = now.replace(tzinfo=CDMX) if now.tzinfo is None else now.astimezone(CDMX)
    policy = {**DEFAULT_POLICY, **(policy or {})}
    payload = read_state(path)
    records = payload['records']
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
                'trackingId': key, 'game': pick.get('game'), 'pick': pick.get('pick'),
                'market': pick.get('market'), 'league': pick.get('league'), 'iso': pick.get('iso'),
                'firstObservedAt': first_time.isoformat(), 'initial': baseline,
                'firstEvaluatedAt': now.isoformat(), 'firstEvaluation': deepcopy(current),
                'confirmations': 0, 'lastObservation': None, 'state': None,
            }
        state, reasons, observed = assess(pick, now, policy)
        observed_text = observed.isoformat() if observed else None
        previous_observed = timestamp(old.get('lastProcessedObservation') or old.get('lastObservation'))
        new_observation = observed is not None and (previous_observed is None or observed > previous_observed)
        if observed and previous_observed and observed < previous_observed:
            state, reasons = 'STALE', ['La lectura recibida es anterior a la última procesada.']
        if state == 'CANDIDATE':
            if new_observation:
                old['confirmations'] = old.get('confirmations',0)+1
            state = 'READY' if old['confirmations'] >= policy['confirmations'] else 'CONFIRMING'
            if state == 'CONFIRMING':
                reasons = ['Esperando confirmación en otra lectura nueva.']
        else:
            old['confirmations'] = 0
        if new_observation:
            old['previous'] = old.get('current')
        old.update(current=current, state=state, reasons=reasons, lastObservation=observed_text,
                   lastProcessedObservation=max(observed, previous_observed).isoformat() if observed and previous_observed else observed_text,
                   evaluatedAt=now.isoformat(), lastSeenAt=now.isoformat(), iso=pick.get('iso'))
        first_odds = decimal_odds(old['initial'].get('odds'))
        current_odds = decimal_odds(current.get('odds'))
        old['priceChangePct'] = round((current_odds/first_odds-1)*100,2) if first_odds and current_odds else None
        pick['trackingId'] = key
        pick['tracking'] = {field: deepcopy(old.get(field)) for field in (
            'firstObservedAt','initial','firstEvaluatedAt','firstEvaluation','previous',
            'state','reasons','lastObservation','evaluatedAt','priceChangePct')}
    for key, record in records.items():
        if key in seen:
            continue
        kickoff = timestamp(record.get('iso'))
        record.update(state='CLOSED' if kickoff and kickoff<=now else 'UNAVAILABLE',
                      reasons=['El encuentro ya comenzó.'] if kickoff and kickoff<=now else
                              ['El pick no está disponible en la lectura actual.' if feed_ok else 'Falló la actualización de datos.'],
                      confirmations=0, evaluatedAt=now.isoformat())
    payload['updatedAt'] = now.isoformat()
    atomic_write_json(path, payload, compact=True)
    return payload
