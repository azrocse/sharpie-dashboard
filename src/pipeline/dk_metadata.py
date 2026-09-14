"""Identify mixed-catalog sports from the linked DK event, never team names."""
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from scraper.draftkings import DraftKingsScraper
from storage import atomic_write_json

SOCCER_LEAGUES = {'england premier league', 'champions league', 'europa league', 'mls'}
ROOT = Path(__file__).resolve().parents[2]
logger = logging.getLogger(__name__)


def extract_event_sport(html, event_id):
    ids = set()
    for match in re.finditer(r'"parameters":(\{[^{}]{1,2000}\})', html):
        try:
            values = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if str(values.get('eventId')) == str(event_id) and values.get('sportId') is not None:
            ids.add(str(values['sportId']))
    if len(ids) != 1:
        return None
    sport_id = ids.pop()
    return {'sourceSportId': sport_id, 'sport': {'1': 'Soccer', '6': 'Tennis'}.get(sport_id, f'DK_SPORT_{sport_id}')}


def fetch_event_sport(event_id):
    if not re.fullmatch(r'\d+', str(event_id)):
        return None
    client = DraftKingsScraper(timeout=12)
    try:
        response = client.session.get(f'https://sportsbook.draftkings.com/event/{event_id}',
                                      headers=client.headers, timeout=12)
        response.raise_for_status()
        return extract_event_sport(response.text, event_id)
    except Exception as exc:
        logger.warning('No se pudo verificar el deporte DK del evento %s: %s', event_id, type(exc).__name__)
        return None
    finally:
        client.session.close()


def enrich_event_sports(parsed_files, cache_path=None, fetcher=None):
    cache_path = Path(cache_path or ROOT / '.runtime/dk-event-sports.json')
    cache = json.loads(cache_path.read_text(encoding='utf-8')) if cache_path.exists() else {}
    documents = [(Path(path), json.loads(Path(path).read_text(encoding='utf-8'))) for path in parsed_files]
    pending = set()
    for _, payload in documents:
        if str(payload.get('league', '')).casefold() == 'sports':
            pending.update(str(g['sourceEventId']) for g in payload.get('games', [])
                           if g.get('sourceEventId') and str(g['sourceEventId']) not in cache)
    lookup = fetcher or fetch_event_sport
    with ThreadPoolExecutor(max_workers=4) as pool:
        for event_id, result in zip(sorted(pending), pool.map(lookup, sorted(pending))):
            if result:
                cache[event_id] = result
    for path, payload in documents:
        league = str(payload.get('league', '')).casefold()
        for game in payload.get('games', []):
            if league in SOCCER_LEAGUES:
                game.update(sport='Soccer', sourceSportId='1')
            elif str(game.get('sourceEventId')) in cache:
                game.update(cache[str(game['sourceEventId'])])
        atomic_write_json(path, payload, compact=True)
    atomic_write_json(cache_path, cache, compact=True)
    return parsed_files
