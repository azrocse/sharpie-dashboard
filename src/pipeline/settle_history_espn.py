r"""Liquida el historial de Sharpie con los scoreboards JSON de ESPN.

Lee data/history/YYYY-MM-DD/sharpie.json, localiza el evento, confirma que
terminó y evalúa Moneyline, Spread/Run Line y Totales. Ante una coincidencia
ambigua o un mercado no reconocido conserva PENDING/REVIEW: nunca inventa un
resultado.

Uso:
    python settle_history_espn.py
    python settle_history_espn.py --date 2026-09-03
    python settle_history_espn.py --dry-run
    python settle_history_espn.py --history-dir C:\ruta\data\history
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path


CURRENT_DIR = Path(__file__).resolve().parent
BASE_DIR = CURRENT_DIR.parent.parent
DEFAULT_HISTORY_DIR = BASE_DIR / "data" / "history"
ESPN_BASE_URL = "https://site.api.espn.com/apis/site/v2/sports"
FINAL_RESULTS = {"WIN", "LOSS", "PUSH", "VOID", "HALF_WIN", "HALF_LOSS"}
CDMX_TIMEZONE = timezone(timedelta(hours=-6))

# Se evalúa en orden: las etiquetas específicas deben preceder a las generales.
LEAGUE_ROUTES = [
    (("wnba",), ("basketball", "wnba")),
    (("nba",), ("basketball", "nba")),
    (("nfl",), ("football", "nfl")),
    (("ncaaf", "college football"), ("football", "college-football")),
    (("ufl",), ("football", "ufl")),
    (("ncaa womens basketball", "womens college basketball", "ncaaw"), ("basketball", "womens-college-basketball")),
    (("ncaa basketball", "college basketball", "ncaab"), ("basketball", "mens-college-basketball")),
    (("mlb", "major league baseball"), ("baseball", "mlb")),
    (("ncaa baseball", "college baseball"), ("baseball", "college-baseball")),
    (("kbo", "korea baseball"), ("baseball", "kbo")),
    (("npb", "japan baseball", "japanese baseball"), ("baseball", "jpn.1")),
    (("uefa champions", "champions league", "ucl"), ("soccer", "uefa.champions")),
    (("europa league", "uel"), ("soccer", "uefa.europa")),
    (("premier league", "epl", "eng.1"), ("soccer", "eng.1")),
    (("la liga", "laliga", "esp.1"), ("soccer", "esp.1")),
    (("serie a", "ita.1"), ("soccer", "ita.1")),
    (("ligue 1", "fra.1"), ("soccer", "fra.1")),
    (("bundesliga", "ger.1"), ("soccer", "ger.1")),
    (("liga mx", "mex.1"), ("soccer", "mex.1")),
    (("mls", "major league soccer", "usa.1"), ("soccer", "usa.1")),
    (("copa libertadores", "libertadores"), ("soccer", "conmebol.libertadores")),
    (("world cup", "fifa world cup"), ("soccer", "fifa.world")),
    (("nhl",), ("hockey", "nhl")),
    (("ncaa ice hockey", "college hockey"), ("hockey", "mens-college-hockey")),
    (("ufc", "mma"), ("mma", "ufc")),
    (("boxing", "boxeo"), ("boxing", "boxing")),
]

TEAM_ROUTE_HINTS = {
    ("baseball", "mlb"): (
        "diamondbacks", "braves", "orioles", "red sox", "cubs", "white sox",
        "reds", "guardians", "rockies", "tigers", "astros", "royals",
        "angels", "dodgers", "marlins", "brewers", "twins", "mets",
        "yankees", "athletics", "phillies", "pirates", "padres", "giants",
        "mariners", "cardinals", "rays", "rangers", "blue jays", "nationals",
    ),
    ("football", "nfl"): (
        "cardinals", "falcons", "ravens", "bills", "panthers", "bears",
        "bengals", "browns", "cowboys", "broncos", "lions", "packers",
        "texans", "colts", "jaguars", "chiefs", "raiders", "chargers",
        "rams", "dolphins", "vikings", "patriots", "saints", "giants",
        "jets", "eagles", "steelers", "49ers", "seahawks", "buccaneers",
        "titans", "commanders",
    ),
    ("basketball", "wnba"): (
        "dream", "sky", "sun", "wings", "valkyries", "fever", "aces",
        "sparks", "lynx", "liberty", "mercury", "storm", "mystics",
    ),
    ("basketball", "nba"): (
        "hawks", "celtics", "nets", "hornets", "bulls", "cavaliers",
        "mavericks", "nuggets", "pistons", "warriors", "rockets", "pacers",
        "clippers", "lakers", "grizzlies", "heat", "bucks", "timberwolves",
        "pelicans", "knicks", "thunder", "magic", "76ers", "suns",
        "trail blazers", "kings", "spurs", "raptors", "jazz", "wizards",
    ),
    ("hockey", "nhl"): (
        "ducks", "bruins", "sabres", "flames", "hurricanes", "blackhawks",
        "avalanche", "blue jackets", "stars", "red wings", "oilers",
        "panthers", "kings", "wild", "canadiens", "predators", "devils",
        "islanders", "rangers", "senators", "flyers", "penguins", "sharks",
        "kraken", "blues", "lightning", "maple leafs", "canucks", "golden knights",
        "capitals", "jets",
    ),
}


def normalize(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.casefold().replace("&", " and ")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def resolve_route(pick):
    lookup = pick.get("eventLookup") or {}
    explicit_sport = lookup.get("espnSport")
    explicit_league = lookup.get("espnLeague")
    if explicit_sport and explicit_league:
        return str(explicit_sport), str(explicit_league)

    source = normalize(" ".join([
        str(pick.get("league") or ""),
        str(pick.get("sport") or ""),
    ]))
    for aliases, route in LEAGUE_ROUTES:
        if any(alias in source for alias in aliases):
            return route
    return None


def candidate_routes(pick):
    """Devuelve rutas probables; SPORTS cae en búsqueda multiproveedor ESPN."""
    direct = resolve_route(pick)
    if direct:
        return [direct]

    text = normalize(" ".join(str(pick.get(key) or "") for key in ("game", "away", "home", "market", "pick")))
    market = normalize(pick.get("market"))
    inferred = []
    if "run line" in market:
        inferred.extend([("baseball", "mlb"), ("baseball", "kbo"), ("baseball", "jpn.1")])
    elif "puck line" in market:
        inferred.append(("hockey", "nhl"))

    for route, hints in TEAM_ROUTE_HINTS.items():
        if any(hint in text for hint in hints):
            inferred.append(route)

    # Rutas únicas en orden: primero las inferidas y después el catálogo.
    if inferred:
        return list(dict.fromkeys(inferred))
    catalog = [route for _aliases, route in LEAGUE_ROUTES]
    return list(dict.fromkeys(catalog))


def infer_primary_route(pick):
    """Infiere una única ruta solo cuando las evidencias no se contradicen."""
    direct = resolve_route(pick)
    if direct:
        return direct
    text = normalize(" ".join(str(pick.get(key) or "") for key in ("game", "away", "home", "market", "pick")))
    team_routes = list(dict.fromkeys(route for route, hints in TEAM_ROUTE_HINTS.items() if any(hint in text for hint in hints)))
    market = normalize(pick.get("market"))
    market_routes = []
    if "run line" in market:
        market_routes = [("baseball", "mlb"), ("baseball", "kbo"), ("baseball", "jpn.1")]
    elif "puck line" in market:
        market_routes = [("hockey", "nhl")]
    if team_routes and market_routes:
        intersection = [route for route in team_routes if route in market_routes]
        return intersection[0] if len(intersection) == 1 else None
    if len(team_routes) == 1:
        return team_routes[0]
    if len(market_routes) == 1:
        return market_routes[0]
    return None


def date_relation(date_text):
    """Clasifica la fecha del pick con respecto al día actual de CDMX."""
    try:
        event_date = datetime.strptime(str(date_text)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return "INVALID"
    today = datetime.now(CDMX_TIMEZONE).date()
    return "PAST" if event_date < today else "FUTURE" if event_date > today else "TODAY"


def search_dates(date_text, include_adjacent=False):
    try:
        base = datetime.strptime(str(date_text)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return [str(date_text)[:10]]
    values = [base]
    if include_adjacent:
        values.extend((base - timedelta(days=1), base + timedelta(days=1)))
    return [value.isoformat() for value in values]


class ESPNClient:
    def __init__(self, timeout=15.0, pause=0.20, retries=3):
        self.timeout = timeout
        self.pause = pause
        self.retries = max(1, int(retries))
        self.cache = {}

    def scoreboard(self, sport, league, date_text):
        date_param = str(date_text).replace("-", "")[:8]
        cache_key = (sport, league, date_param)
        if cache_key in self.cache:
            return self.cache[cache_key]

        query = urllib.parse.urlencode({"dates": date_param, "limit": 500})
        url = f"{ESPN_BASE_URL}/{sport}/{league}/scoreboard?{query}"
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "SharpieDashboard/1.0", "Accept": "application/json"},
        )
        last_error = None
        payload = None
        for attempt in range(self.retries):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = json.load(response)
                if not isinstance(payload, dict) or not isinstance(payload.get("events", []), list):
                    raise ValueError("respuesta JSON sin una lista de eventos")
                break
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                payload = None
                if attempt + 1 < self.retries:
                    time.sleep(min(2.0, 0.4 * (2 ** attempt)))
        if payload is None:
            raise RuntimeError(
                f"ESPN no respondió para {sport}/{league} {date_param}: {last_error}"
            ) from last_error

        self.cache[cache_key] = {"url": url, "payload": payload}
        if self.pause:
            time.sleep(self.pause)
        return self.cache[cache_key]


def event_competitors(event):
    competitions = event.get("competitions") or []
    competition = competitions[0] if competitions else {}
    result = {}
    for index, competitor in enumerate(competition.get("competitors") or []):
        side = competitor.get("homeAway") or ("away" if index == 0 else "home" if index == 1 else None)
        if side not in {"home", "away"}:
            continue
        team = competitor.get("team") or competitor.get("athlete") or {}
        aliases = {
            team.get("displayName"), team.get("shortDisplayName"), team.get("name"),
            team.get("location"), team.get("abbreviation"), competitor.get("id"),
        }
        result[side] = {
            "id": competitor.get("id") or team.get("id"),
            "name": team.get("displayName") or team.get("shortDisplayName") or team.get("name"),
            "aliases": {normalize(alias) for alias in aliases if alias},
            "score": parse_score(competitor.get("score")),
            "winner": competitor.get("winner"),
        }
    return result, competition


def parse_score(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def text_similarity(left, right):
    left_n, right_n = normalize(left), normalize(right)
    if not left_n or not right_n:
        return 0.0
    if left_n == right_n:
        return 1.0
    if left_n in right_n or right_n in left_n:
        return 0.92
    return SequenceMatcher(None, left_n, right_n).ratio()


def side_similarity(expected, competitor):
    if not expected or not competitor:
        return 0.0
    expected_n = normalize(expected)
    score = max((text_similarity(expected, alias) for alias in competitor.get("aliases", set())), default=0.0)
    expected_tokens = expected_n.split()
    if expected_tokens:
        nickname = expected_tokens[-1]
        if len(nickname) >= 4 and any(nickname == normalize(alias).split()[-1] for alias in competitor.get("aliases", set()) if normalize(alias)):
            score = max(score, 0.88)
    return score


def game_teams(game):
    parts = re.split(r"\s+(?:@|vs\.?|versus|v\.)\s+", str(game or ""), maxsplit=1, flags=re.IGNORECASE)
    return (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else (None, None)


def parse_event_datetime(value, assume_cdmx=False):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=CDMX_TIMEZONE if assume_cdmx else timezone.utc)
    return parsed.astimezone(timezone.utc)


def pick_datetime(pick):
    lookup = pick.get("eventLookup") or {}
    parsed = parse_event_datetime(lookup.get("scheduledAt") or pick.get("iso"), assume_cdmx=True)
    if parsed:
        return parsed
    date_text, time_text = str(pick.get("date") or "")[:10], str(pick.get("time") or "")
    return parse_event_datetime(f"{date_text}T{time_text}", assume_cdmx=True)


def event_match_score(pick, event):
    lookup = pick.get("eventLookup") or {}
    stored_id = str(lookup.get("eventId") or pick.get("sourceEventId") or "").strip()
    if stored_id and stored_id == str(event.get("id") or ""):
        return 1000.0

    competitors, _competition = event_competitors(event)
    expected_home = lookup.get("home") or pick.get("home")
    expected_away = lookup.get("away") or pick.get("away")
    if not expected_home or not expected_away:
        left, right = game_teams(pick.get("game"))
        expected_away = expected_away or left
        expected_home = expected_home or right
    if expected_home and expected_away:
        direct = side_similarity(expected_home, competitors.get("home")) + side_similarity(expected_away, competitors.get("away"))
        reverse = side_similarity(expected_home, competitors.get("away")) + side_similarity(expected_away, competitors.get("home"))
        score = max(direct, reverse) * 50.0
        expected_time = pick_datetime(pick)
        event_time = parse_event_datetime(event.get("date"))
        if expected_time and event_time:
            hours = abs((expected_time - event_time).total_seconds()) / 3600.0
            score += max(0.0, 24.0 - hours * 4.0)
        return score

    game = pick.get("game") or ""
    names = " ".join(
        competitor.get("name") or "" for competitor in competitors.values()
    )
    return text_similarity(game, event.get("name") or names) * 100.0


def find_event(pick, events):
    lookup = pick.get("eventLookup") or {}
    stored_id = str(lookup.get("eventId") or pick.get("sourceEventId") or "").strip()
    if stored_id:
        exact = [event for event in events if str(event.get("id") or "") == stored_id]
        if len(exact) == 1:
            return exact[0], 1000.0, None

    ranked = sorted(
        ((event_match_score(pick, event), event) for event in events),
        key=lambda pair: pair[0],
        reverse=True,
    )
    if not ranked or ranked[0][0] < 72.0:
        return None, ranked[0][0] if ranked else 0.0, "NO_MATCH"
    if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 8.0:
        return None, ranked[0][0], "AMBIGUOUS_MATCH"
    return ranked[0][1], ranked[0][0], None


def event_state(event):
    status_type = (event.get("status") or {}).get("type") or {}
    name = str(status_type.get("name") or "").upper()
    description = str(status_type.get("description") or status_type.get("detail") or "").upper()
    completed = bool(status_type.get("completed"))
    if any(token in name or token in description for token in ("CANCEL", "ABANDON")):
        return "CANCELED"
    if "POSTPON" in name or "POSTPON" in description:
        return "POSTPONED"
    if completed:
        return "FINAL"
    return "PENDING"


def extract_number_after(pattern, text):
    match = re.search(pattern + r"\s*([+-]?\d+(?:\.\d+)?)", text, flags=re.IGNORECASE)
    return float(match.group(1)) if match else None


def chosen_side(pick_text, competitors):
    normalized_pick = normalize(pick_text)
    scores = {}
    for side, competitor in competitors.items():
        scores[side] = max(
            (text_similarity(normalized_pick, alias) for alias in competitor.get("aliases", set())),
            default=0.0,
        )
        if any(alias and alias in normalized_pick for alias in competitor.get("aliases", set())):
            scores[side] = max(scores[side], 0.96)
    if not scores:
        return None
    ranked = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)
    if ranked[0][1] < 0.58 or (len(ranked) > 1 and ranked[0][1] - ranked[1][1] < 0.08):
        return None
    return ranked[0][0]


def compare_margin(value):
    if abs(value) < 1e-9:
        return "PUSH"
    return "WIN" if value > 0 else "LOSS"


def is_quarter_line(line):
    """Los cuartos asiáticos (.25/.75) requieren media ganada/perdida."""
    return abs(round(abs(line) * 4) % 2) == 1


def settle_quarter_line(evaluator, line):
    """Divide una línea asiática de cuarto en sus dos medias líneas."""
    lines = (line - 0.25, line + 0.25)
    outcomes = [evaluator(part) for part in lines]
    if outcomes[0] == outcomes[1]:
        return outcomes[0], lines, outcomes
    pair = set(outcomes)
    if pair == {"WIN", "PUSH"}:
        return "HALF_WIN", lines, outcomes
    if pair == {"LOSS", "PUSH"}:
        return "HALF_LOSS", lines, outcomes
    return "PUSH", lines, outcomes


def settle_market(pick, event):
    competitors, _competition = event_competitors(event)
    if set(competitors) != {"home", "away"}:
        return "REVIEW", "ESPN no entregó local y visitante"
    espn_sport = (pick.get("eventLookup") or {}).get("espnSport")
    if espn_sport in {"boxing", "mma"}:
        side = chosen_side(str(pick.get("pick") or ""), competitors)
        if side is None:
            return "REVIEW", "No se pudo identificar al peleador seleccionado"
        winner = competitors[side].get("winner")
        if winner is None:
            return "REVIEW", "ESPN no entregó el ganador oficial del combate"
        return ("WIN" if winner else "LOSS"), "Resultado oficial del combate según ESPN"
    home_score, away_score = competitors["home"]["score"], competitors["away"]["score"]
    if home_score is None or away_score is None:
        return "REVIEW", "ESPN no entregó marcador final"

    market_text = normalize(pick.get("market"))
    pick_text = str(pick.get("pick") or "")
    pick_normalized = normalize(pick_text)

    is_total = any(token in market_text for token in ("total", "over under", "puntos", "goles")) or pick_normalized.startswith(("over ", "under "))
    if is_total:
        direction = "OVER" if re.search(r"\bover\b", pick_text, re.I) else "UNDER" if re.search(r"\bunder\b", pick_text, re.I) else None
        line = extract_number_after(r"\b(?:over|under)\b", pick_text)
        if direction is None or line is None:
            return "REVIEW", "No se pudo interpretar el total"
        total = home_score + away_score
        evaluator = lambda part: compare_margin(total - part if direction == "OVER" else part - total)
        if is_quarter_line(line):
            result, lines, outcomes = settle_quarter_line(evaluator, line)
            return result, f"Total {total:g}; línea {line:g} dividida en {lines[0]:g}/{lines[1]:g} ({outcomes[0]}/{outcomes[1]})"
        return compare_margin(total - line if direction == "OVER" else line - total), f"Total final {total:g} vs línea {line:g}"

    is_spread = any(token in market_text for token in ("spread", "run line", "puck line", "handicap", "linea"))
    if is_spread:
        # La última cifra firmada corresponde a la línea del pick.
        matches = re.findall(r"(?<!\w)([+-]\d+(?:\.\d+)?)", pick_text)
        if not matches:
            return "REVIEW", "No se pudo interpretar el spread"
        line = float(matches[-1])
        side = chosen_side(pick_text, competitors)
        if side is None:
            return "REVIEW", "No se pudo identificar el equipo del spread"
        other = "away" if side == "home" else "home"
        raw_margin = competitors[side]["score"] - competitors[other]["score"]
        if is_quarter_line(line):
            result, lines, outcomes = settle_quarter_line(lambda part: compare_margin(raw_margin + part), line)
            return result, f"Margen {raw_margin:g}; línea {line:+g} dividida en {lines[0]:+g}/{lines[1]:+g} ({outcomes[0]}/{outcomes[1]})"
        adjusted_margin = raw_margin + line
        return compare_margin(adjusted_margin), f"Margen ajustado {adjusted_margin:g} con línea {line:+g}"

    is_moneyline = any(token in market_text for token in ("moneyline", "money line", "ganador", "1x2", "ml"))
    if is_moneyline:
        if any(token in pick_normalized.split() for token in ("draw", "empate", "tie")):
            return ("WIN" if home_score == away_score else "LOSS"), f"Marcador {home_score:g}-{away_score:g}"
        side = chosen_side(pick_text, competitors)
        if side is None:
            return "REVIEW", "No se pudo identificar el equipo Moneyline"
        other = "away" if side == "home" else "home"
        margin = competitors[side]["score"] - competitors[other]["score"]
        is_soccer = (pick.get("eventLookup") or {}).get("espnSport") == "soccer"
        is_draw_no_bet = "draw no bet" in market_text or "dnb" in market_text
        if margin == 0 and is_soccer and not is_draw_no_bet:
            return "LOSS", f"Empate {away_score:g}-{home_score:g} en mercado de tres vías"
        return compare_margin(margin), f"Marcador {away_score:g}-{home_score:g}"

    return "REVIEW", f"Mercado no soportado: {pick.get('market')}"


def american_profit_units(odds, stake, result):
    try:
        stake_value = float(stake)
        odds_value = float(str(odds).replace("+", ""))
    except (TypeError, ValueError):
        return None
    if result == "LOSS":
        return round(-stake_value, 4)
    if result == "HALF_LOSS":
        return round(-stake_value / 2.0, 4)
    if result in {"PUSH", "VOID"}:
        return 0.0
    if result not in {"WIN", "HALF_WIN"} or odds_value == 0:
        return None
    if 1.01 <= abs(odds_value) <= 50:
        multiplier = abs(odds_value) - 1.0
    else:
        multiplier = odds_value / 100.0 if odds_value > 0 else 100.0 / abs(odds_value)
    profit = stake_value * multiplier
    return round(profit / 2.0 if result == "HALF_WIN" else profit, 4)


def atomic_write(path, payload):
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as output:
        json.dump(payload, output, ensure_ascii=False, indent=2)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temp_path, path)


def history_files(history_dir, date_filter=None):
    root = Path(history_dir)
    if date_filter:
        candidate = root / date_filter / "sharpie.json"
        return [candidate] if candidate.exists() else []
    return sorted(root.glob("????-??-??/sharpie.json"))


def write_settlement_audit(history_dir):
    """Genera un diagnóstico agregado sin contaminar el visualizador público."""
    root = Path(history_dir)
    status_counts, reason_counts, relation_counts, route_counts = Counter(), Counter(), Counter(), Counter()
    unresolved = []
    excluded_count = 0
    total = 0
    for path in history_files(root):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        picks = payload.get("picks", []) if isinstance(payload, dict) else payload if isinstance(payload, list) else []
        for pick in picks:
            if not isinstance(pick, dict):
                continue
            total += 1
            if pick.get("excludedFromResults"):
                excluded_count += 1
                continue
            settlement = pick.get("settlement") or {}
            lookup = pick.get("eventLookup") or {}
            status = str(settlement.get("status") or "PENDING").upper()
            reason = settlement.get("failureCode") or settlement.get("notes") or "SIN_DETALLE"
            relation = date_relation(pick.get("date") or lookup.get("scheduledAt", "")[:10])
            route = "/".join(filter(None, (str(lookup.get("espnSport") or ""), str(lookup.get("espnLeague") or "")))) or "SIN_RUTA"
            status_counts[status] += 1
            relation_counts[f"{status}_{relation}"] += 1
            route_counts[route] += 1
            if status not in FINAL_RESULTS:
                reason_counts[str(reason)] += 1
                if len(unresolved) < 200:
                    unresolved.append({
                        "date": pick.get("date"), "game": pick.get("game"),
                        "pick": pick.get("pick"), "league": pick.get("league"),
                        "status": status, "reason": reason,
                        "matchConfidence": settlement.get("matchConfidence"),
                        "bestCandidate": lookup.get("bestCandidate"),
                        "attemptedRoutes": lookup.get("attemptedRoutes", []),
                        "attemptedDates": lookup.get("attemptedDates", []),
                    })
    report = {
        "generatedAt": now_iso(), "totalPicks": total, "excludedPicks": excluded_count,
        "statusCounts": dict(status_counts), "unresolvedReasons": dict(reason_counts),
        "statusByDateRelation": dict(relation_counts), "resolvedRoutes": dict(route_counts),
        "unresolvedSamples": unresolved,
    }
    output = root.parent / "results" / "settlement_audit.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(output, report)
    print(f"[AUDITORÍA ESPN] {output}")
    return report


def update_pick_from_espn(pick, client, force=False):
    try:
        positive_value = float(pick.get("ev") or 0) > 0 and float(pick.get("modelEdge") or 0) > 0
        old_stake = float(pick.get("stake") or 0)
    except (TypeError, ValueError):
        positive_value, old_stake = False, 0.0

    stake_normalized = positive_value and old_stake <= 0
    if stake_normalized:
        pick["originalStake"] = pick.get("stake")
        pick["stake"] = 1.0
        pick["stakeNormalized"] = True
        pick["stakeNormalizationReason"] = "LEGACY_STAKE_MODEL"

    actionable = positive_value and float(pick.get("stake") or 0) >= 1.0

    if not actionable:
        pick["excludedFromResults"] = True
        pick["exclusionReason"] = "NON_ACTIONABLE_PICK"
        pick["needsSettlement"] = False
        return "EXCLUDED"

    if pick.get("exclusionReason") == "NON_ACTIONABLE_PICK":
        pick.pop("excludedFromResults", None)
        pick.pop("exclusionReason", None)

    settlement = pick.get("settlement") or {"status": "PENDING"}
    settlement["status"] = str(settlement.get("status") or "PENDING").upper()
    if settlement.get("status") in FINAL_RESULTS and not force:
        if stake_normalized:
            pick["profitUnits"] = american_profit_units(pick.get("odds"), pick.get("stake"), settlement.get("status"))
            return "NORMALIZED"
        return "SKIPPED_FINAL"

    checked_at = now_iso()
    date_text = pick.get("date") or (pick.get("eventLookup") or {}).get("scheduledAt", "")[:10]
    relation = date_relation(date_text)
    if relation == "FUTURE" and not force:
        settlement.update({
            "status": "PENDING", "checkedAt": checked_at,
            "notes": "Evento programado para una fecha futura",
            "failureCode": "NOT_STARTED_FUTURE",
        })
        pick["needsSettlement"] = True
        pick["settlement"] = settlement
        return "PENDING"
    routes = candidate_routes(pick)
    dates = search_dates(date_text, include_adjacent=len(routes) <= 3)
    candidates = []
    request_errors = []
    successful_requests = 0
    stored_id = str((pick.get("eventLookup") or {}).get("eventId") or pick.get("sourceEventId") or "").strip()
    for route in routes:
        for query_date in dates:
            try:
                route_response = client.scoreboard(route[0], route[1], query_date)
            except Exception as exc:
                request_errors.append(str(exc))
                continue
            successful_requests += 1
            for route_event in route_response["payload"].get("events") or []:
                confidence = event_match_score(pick, route_event)
                if stored_id and stored_id == str(route_event.get("id") or ""):
                    confidence = 1000.0
                candidates.append((confidence, route_event, route_response, route, query_date))

        # Una liga ya identificada no debe provocar una búsqueda innecesaria.
        if resolve_route(pick):
            break

    deduplicated = {}
    for candidate in candidates:
        confidence, event, _response, route, _query_date = candidate
        identity = (route, str(event.get("id") or event.get("uid") or event.get("name") or ""))
        if identity not in deduplicated or confidence > deduplicated[identity][0]:
            deduplicated[identity] = candidate
    candidates = sorted(deduplicated.values(), key=lambda item: item[0], reverse=True)
    best = candidates[0] if candidates else None
    ambiguous = len(candidates) > 1 and best[0] < 1000 and best[0] - candidates[1][0] < 8.0
    if best is None or best[0] < 72.0 or ambiguous:
        error = "AMBIGUOUS_MATCH" if ambiguous else "NO_MATCH"
        if best is None and request_errors and not successful_requests:
            raise RuntimeError(request_errors[0])
        confidence = best[0] if best else 0.0
        if error == "AMBIGUOUS_MATCH":
            status, failure_code = "REVIEW", "AMBIGUOUS_MATCH"
        elif relation == "PAST":
            status, failure_code = "REVIEW", "NO_MATCH_PAST"
        elif relation == "INVALID":
            status, failure_code = "REVIEW", "INVALID_EVENT_DATE"
        else:
            status, failure_code = "PENDING", f"NO_MATCH_{relation}"
        lookup = pick.setdefault("eventLookup", {})
        lookup.update({
            "provider": "ESPN", "matchStatus": failure_code,
            "matchConfidence": round(confidence, 2),
            "attemptedRoutes": [f"{sport}/{league}" for sport, league in routes],
            "attemptedDates": dates,
            "candidateEvents": len(candidates),
        })
        if best:
            lookup["bestCandidate"] = best[1].get("name")
        settlement.update({
            "status": status, "checkedAt": checked_at, "notes": failure_code,
            "failureCode": failure_code, "matchConfidence": round(confidence, 2),
        })
        if failure_code == "NO_MATCH_PAST":
            pick["excludedFromResults"] = True
            pick["exclusionReason"] = failure_code
            pick["needsSettlement"] = False
        else:
            pick["needsSettlement"] = True
        pick["settlement"] = settlement
        return status

    confidence, event, response, route, matched_date = best
    pick.pop("excludedFromResults", None)
    pick.pop("exclusionReason", None)

    competitors, _competition = event_competitors(event)
    home_score = competitors.get("home", {}).get("score")
    away_score = competitors.get("away", {}).get("score")
    state = event_state(event)
    lookup = pick.setdefault("eventLookup", {})
    lookup.update({
        "provider": "ESPN", "eventId": str(event.get("id")), "espnSport": route[0],
        "espnLeague": route[1], "matchedName": event.get("name"),
        "matchStatus": "MATCHED", "matchConfidence": round(confidence, 2),
        "matchedDate": matched_date, "attemptedDates": dates,
    })

    common = {
        "source": "ESPN", "sourceUrl": response["url"], "eventId": str(event.get("id")),
        "eventName": event.get("name"), "checkedAt": checked_at,
        "homeScore": home_score, "awayScore": away_score,
        "matchConfidence": round(confidence, 2),
    }
    if state == "CANCELED":
        result, notes = "VOID", "Evento cancelado por ESPN"
    elif state == "POSTPONED":
        settlement.update(common, status="PENDING", notes="Evento pospuesto; requiere nueva fecha")
        pick["settlement"] = settlement
        return "PENDING"
    elif state != "FINAL":
        settlement.update(common, status="PENDING", notes="Evento aún no finaliza")
        pick["settlement"] = settlement
        return "PENDING"
    else:
        result, notes = settle_market(pick, event)

    settlement.update(common, status=result, notes=notes)
    if result in FINAL_RESULTS:
        settlement["settledAt"] = checked_at
        pick["result"] = result
        pick["needsSettlement"] = False
        pick["profitUnits"] = american_profit_units(pick.get("odds"), pick.get("stake"), result)
    else:
        pick["needsSettlement"] = True
    pick["settlement"] = settlement
    return result


def settle_history(history_dir=DEFAULT_HISTORY_DIR, date_filter=None, dry_run=False, force=False, timeout=15.0):
    client = ESPNClient(timeout=timeout)
    summary = {key: 0 for key in ("FILES", "PICKS", "WIN", "HALF_WIN", "LOSS", "HALF_LOSS", "PUSH", "VOID", "PENDING", "REVIEW", "NORMALIZED", "EXCLUDED", "ERROR", "SKIPPED_FINAL")}
    for path in history_files(history_dir, date_filter):
        summary["FILES"] += 1
        try:
            with path.open("r", encoding="utf-8") as source:
                payload = json.load(source)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[ERROR] {path}: {exc}")
            summary["ERROR"] += 1
            continue

        picks = payload.get("picks", []) if isinstance(payload, dict) else []
        changed = False
        for pick in picks:
            if not isinstance(pick, dict):
                continue
            summary["PICKS"] += 1
            before = json.dumps(pick, ensure_ascii=False, sort_keys=True)
            try:
                outcome = update_pick_from_espn(pick, client, force=force)
            except Exception as exc:
                outcome = "ERROR"
                settlement = pick.setdefault("settlement", {})
                relation = date_relation(pick.get("date") or (pick.get("eventLookup") or {}).get("scheduledAt", "")[:10])
                visible_status = "REVIEW" if relation in {"PAST", "INVALID"} else "PENDING"
                settlement.update({
                    "status": visible_status, "checkedAt": now_iso(), "notes": str(exc),
                    "failureCode": "ESPN_REQUEST_ERROR",
                })
                print(f"[ERROR] {pick.get('historyId') or pick.get('pick')}: {exc}")
            summary[outcome] = summary.get(outcome, 0) + 1
            changed = changed or before != json.dumps(pick, ensure_ascii=False, sort_keys=True)

        if isinstance(payload, dict):
            payload["updatedAt"] = now_iso()
            payload["pendingSettlement"] = sum(
                1 for pick in picks
                if not pick.get("excludedFromResults")
                and (pick.get("settlement") or {}).get("status") not in FINAL_RESULTS
                and pick.get("needsSettlement", True)
            )
            payload["settledCount"] = sum(1 for pick in picks if (pick.get("settlement") or {}).get("status") in FINAL_RESULTS)
        if changed and not dry_run:
            atomic_write(path, payload)
            print(f"[OK] {path}")
        elif changed:
            print(f"[DRY-RUN] {path}")
    if not dry_run:
        write_settlement_audit(history_dir)
    return summary


def main():
    parser = argparse.ArgumentParser(description="Liquida el historial de Sharpie mediante ESPN JSON")
    parser.add_argument("--history-dir", default=str(DEFAULT_HISTORY_DIR), help="Ruta de data/history")
    parser.add_argument("--date", help="Procesar solo YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true", help="Consultar y evaluar sin escribir archivos")
    parser.add_argument("--force", action="store_true", help="Revalidar picks ya liquidados")
    parser.add_argument("--timeout", type=float, default=15.0, help="Timeout HTTP por consulta")
    args = parser.parse_args()
    summary = settle_history(args.history_dir, args.date, args.dry_run, args.force, args.timeout)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
