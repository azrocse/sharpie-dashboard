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
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path


CURRENT_DIR = Path(__file__).resolve().parent
BASE_DIR = CURRENT_DIR.parent.parent
DEFAULT_HISTORY_DIR = BASE_DIR / "data" / "history"
ESPN_BASE_URL = "https://site.api.espn.com/apis/site/v2/sports"
FINAL_RESULTS = {"WIN", "LOSS", "PUSH", "VOID"}

# Se evalúa en orden: las etiquetas específicas deben preceder a las generales.
LEAGUE_ROUTES = [
    (("wnba",), ("basketball", "wnba")),
    (("nba",), ("basketball", "nba")),
    (("nfl",), ("football", "nfl")),
    (("ncaaf", "college football"), ("football", "college-football")),
    (("mlb", "major league baseball"), ("baseball", "mlb")),
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
    (("nhl",), ("hockey", "nhl")),
]


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


class ESPNClient:
    def __init__(self, timeout=15.0, pause=0.20):
        self.timeout = timeout
        self.pause = pause
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
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"ESPN no respondió para {sport}/{league} {date_param}: {exc}") from exc

        self.cache[cache_key] = {"url": url, "payload": payload}
        if self.pause:
            time.sleep(self.pause)
        return self.cache[cache_key]


def event_competitors(event):
    competitions = event.get("competitions") or []
    competition = competitions[0] if competitions else {}
    result = {}
    for competitor in competition.get("competitors") or []:
        side = competitor.get("homeAway")
        if side not in {"home", "away"}:
            continue
        team = competitor.get("team") or {}
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
    return max((text_similarity(expected, alias) for alias in competitor.get("aliases", set())), default=0.0)


def event_match_score(pick, event):
    lookup = pick.get("eventLookup") or {}
    stored_id = str(lookup.get("eventId") or pick.get("sourceEventId") or "").strip()
    if stored_id and stored_id == str(event.get("id") or ""):
        return 1000.0

    competitors, _competition = event_competitors(event)
    expected_home = lookup.get("home") or pick.get("home")
    expected_away = lookup.get("away") or pick.get("away")
    if expected_home and expected_away:
        direct = side_similarity(expected_home, competitors.get("home")) + side_similarity(expected_away, competitors.get("away"))
        reverse = side_similarity(expected_home, competitors.get("away")) + side_similarity(expected_away, competitors.get("home"))
        return max(direct, reverse) * 50.0

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
    if "CANCEL" in name or "CANCEL" in description:
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


def settle_market(pick, event):
    competitors, _competition = event_competitors(event)
    if set(competitors) != {"home", "away"}:
        return "REVIEW", "ESPN no entregó local y visitante"
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
        if is_quarter_line(line):
            return "REVIEW", "Total asiático de cuarto requiere liquidación dividida"
        total = home_score + away_score
        return compare_margin(total - line if direction == "OVER" else line - total), f"Total final {total:g} vs línea {line:g}"

    is_spread = any(token in market_text for token in ("spread", "run line", "puck line", "handicap", "linea"))
    if is_spread:
        # La última cifra firmada corresponde a la línea del pick.
        matches = re.findall(r"(?<!\w)([+-]\d+(?:\.\d+)?)", pick_text)
        if not matches:
            return "REVIEW", "No se pudo interpretar el spread"
        line = float(matches[-1])
        if is_quarter_line(line):
            return "REVIEW", "Hándicap asiático de cuarto requiere liquidación dividida"
        side = chosen_side(pick_text, competitors)
        if side is None:
            return "REVIEW", "No se pudo identificar el equipo del spread"
        other = "away" if side == "home" else "home"
        adjusted_margin = competitors[side]["score"] + line - competitors[other]["score"]
        return compare_margin(adjusted_margin), f"Margen ajustado {adjusted_margin:g} con línea {line:+g}"

    is_moneyline = any(token in market_text for token in ("moneyline", "money line", "ganador", "1x2", "ml"))
    if is_moneyline or not re.search(r"[+-]\d+(?:\.\d+)?", pick_text):
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
    if result in {"PUSH", "VOID"}:
        return 0.0
    if result != "WIN" or odds_value == 0:
        return None
    if 1.01 <= abs(odds_value) <= 50:
        multiplier = abs(odds_value) - 1.0
    else:
        multiplier = odds_value / 100.0 if odds_value > 0 else 100.0 / abs(odds_value)
    return round(stake_value * multiplier, 4)


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


def update_pick_from_espn(pick, client, force=False):
    settlement = pick.get("settlement") or {"status": "PENDING"}
    if settlement.get("status") in FINAL_RESULTS and not force:
        return "SKIPPED_FINAL"

    route = resolve_route(pick)
    checked_at = now_iso()
    if route is None:
        settlement.update({"status": "REVIEW", "checkedAt": checked_at, "notes": "Liga sin ruta ESPN configurada"})
        pick["settlement"] = settlement
        return "REVIEW"

    date_text = pick.get("date") or (pick.get("eventLookup") or {}).get("scheduledAt", "")[:10]
    response = client.scoreboard(route[0], route[1], date_text)
    events = response["payload"].get("events") or []
    event, confidence, error = find_event(pick, events)
    if event is None:
        settlement.update({"status": "PENDING" if error == "NO_MATCH" else "REVIEW", "checkedAt": checked_at, "notes": error, "matchConfidence": round(confidence, 2)})
        pick["settlement"] = settlement
        return settlement["status"]

    competitors, _competition = event_competitors(event)
    home_score = competitors.get("home", {}).get("score")
    away_score = competitors.get("away", {}).get("score")
    state = event_state(event)
    lookup = pick.setdefault("eventLookup", {})
    lookup.update({
        "provider": "ESPN", "eventId": str(event.get("id")), "espnSport": route[0],
        "espnLeague": route[1], "matchedName": event.get("name"),
        "matchStatus": "MATCHED", "matchConfidence": round(confidence, 2),
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
    summary = {key: 0 for key in ("FILES", "PICKS", "WIN", "LOSS", "PUSH", "VOID", "PENDING", "REVIEW", "ERROR", "SKIPPED_FINAL")}
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
                settlement.update({"status": "PENDING", "checkedAt": now_iso(), "notes": str(exc)})
                print(f"[ERROR] {pick.get('historyId') or pick.get('pick')}: {exc}")
            summary[outcome] = summary.get(outcome, 0) + 1
            changed = changed or before != json.dumps(pick, ensure_ascii=False, sort_keys=True)

        if isinstance(payload, dict):
            payload["updatedAt"] = now_iso()
            payload["pendingSettlement"] = sum(1 for pick in picks if pick.get("needsSettlement", True))
            payload["settledCount"] = sum(1 for pick in picks if (pick.get("settlement") or {}).get("status") in FINAL_RESULTS)
        if changed and not dry_run:
            atomic_write(path, payload)
            print(f"[OK] {path}")
        elif changed:
            print(f"[DRY-RUN] {path}")
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
