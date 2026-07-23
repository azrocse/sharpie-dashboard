import json
import os
from datetime import datetime, timedelta

# ============================================================
# RUTAS
# ============================================================
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
INPUT_DIR = os.path.join(BASE_DIR, "data", "analyzed")
SNAPSHOTS_DIR = os.path.join(BASE_DIR, "data", "snapshots")
OUTPUT_DIR = BASE_DIR

MAX_HISTORY_POINTS = 8

# ============================================================
# LOCALIZAR ARCHIVO FUENTE
# ============================================================
def get_latest_file():
    direct = os.path.join(INPUT_DIR, "sharpie.json")
    if os.path.exists(direct):
        return direct

    if not os.path.exists(INPUT_DIR):
        return None

    candidates = []
    for root, dirs, files in os.walk(INPUT_DIR):
        for file in files:
            if file.lower() == "sharpie.json":
                candidates.append(os.path.join(root, file))

    if not candidates:
        return None

    return max(candidates, key=os.path.getmtime)

# ============================================================
# FECHAS Y HORAS
# ============================================================
def parse_match_datetime(raw):
    now = datetime.now()
    if not raw:
        return (
            now.strftime("%Y-%m-%d"),
            "--:--",
            now.strftime("%Y-%m-%dT00:00:00")
        )

    raw = str(raw).strip()
    formats = [
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(raw, fmt)
            return (
                dt.strftime("%Y-%m-%d"),
                dt.strftime("%H:%M"),
                dt.strftime("%Y-%m-%dT%H:%M:%S")
            )
        except:
            pass

    try:
        if "," in raw:
            date_part, time_part = [x.strip() for x in raw.split(",", 1)]
            year = now.year
            full = f"{date_part}/{year} {time_part}"
            dt = datetime.strptime(full, "%m/%d/%Y %I:%M%p")
            dt = dt - timedelta(hours=2)
            return (
                dt.strftime("%Y-%m-%d"),
                dt.strftime("%H:%M"),
                dt.strftime("%Y-%m-%dT%H:%M:%S")
            )
    except:
        pass

    return (
        now.strftime("%Y-%m-%d"),
        raw,
        now.strftime("%Y-%m-%dT00:00:00")
    )

# ============================================================
# CLASIFICADORES
# ============================================================
def classify_action(text):
    text = (text or "").upper()
    if any(k in text for k in ["APOSTAR", "INCLINACIÓN", "BET", "SHARP LEAN", "LEAN", "TAKE"]):
        return "bet"
    return "pass"

def classify_trend(text):
    t = (text or "").lower()
    if any(k in t for k in ["sharp", "🔥", "alcista", "entrando", "divergence", "whale"]):
        return "sharp"
    if any(k in t for k in ["mixto", "cambio", "estable"]):
        return "mixed"
    if "consenso" in t:
        return "consensus"
    if any(k in t for k in ["público", "public", "bajista", "perdiendo", "trap"]):
        return "public"
    return "other"

def classify_priority(text):
    t = (text or "").upper()
    if "AHORA" in t:
        return "now"
    if "PRONTO" in t:
        return "soon"
    return "watch"

def classify_status(market, iso_str):
    explicit = market.get("status")
    if explicit:
        return explicit

    if not iso_str:
        return "UPCOMING"

    try:
        event_dt = datetime.strptime(iso_str, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return "UPCOMING"

    if event_dt > datetime.now():
        return "UPCOMING"

    return "LIVE"

# ============================================================
# CONVERSORES Y VALIDACIONES SEGURAS
# ============================================================
def safe_float(val):
    if val is None:
        return 0.0
    try:
        if isinstance(val, str):
            val = val.replace('%', '').strip()
        return float(val)
    except Exception:
        return 0.0

def safe_score(value):
    try:
        value = float(value)
    except:
        return 0
    return max(0, min(100, value))

def safe_edge(value):
    try:
        value = float(value)
    except Exception:
        return 0.0
    return max(-100.0, min(100.0, value))

def safe_pct(val):
    if val is None:
        return None
    try:
        if isinstance(val, str):
            val = val.replace('%', '').strip()
        num = float(val)
        if 0 < num < 1:
            return int(num * 100)
        return int(num)
    except Exception:
        return None

def american_to_decimal(american_odds):
    try:
        odds = float(american_odds)
        if odds == 0:
            return None
        if odds > 0:
            return (odds / 100.0) + 1.0
        else:
            return (100.0 / abs(odds)) + 1.0
    except (ValueError, TypeError):
        return None

# ============================================================
# DETECCIÓN WHALE / SHARP DIVERGENCE
# ============================================================
def detect_whale(market):
    if market.get("whale"):
        return True

    handle = safe_pct(market.get("handle_pct", market.get("handle")))
    bets = safe_pct(market.get("bets_pct", market.get("bets")))

    if handle is not None and bets is not None:
        diff = handle - bets
        if diff >= 30 or (diff >= 15 and handle >= 70):
            return True

    blob = " ".join(
        str(market.get(k, ""))
        for k in ["priority", "action", "reason", "market_trend", "trend", "pattern"]
    ).lower()

    return any(k in blob for k in ["whale", "🐋", "divergence", "sharp lean"])

# ============================================================
# EVOLUCIÓN HISTÓRICA DEL PICK
# ============================================================
_snapshot_cache = {}

def _league_slug(league_name):
    return (league_name or "").strip().lower().replace(" ", "_")

def _market_unique_key(game, pick, market_name):
    return f"{game}||{pick}||{market_name}"

def _load_league_snapshots(league_slug):
    if league_slug in _snapshot_cache:
        return _snapshot_cache[league_slug]

    league_folder = os.path.join(SNAPSHOTS_DIR, league_slug)
    indexed = []

    if os.path.isdir(league_folder):
        files = sorted(f for f in os.listdir(league_folder) if f.endswith(".json"))

        for filename in files:
            path = os.path.join(league_folder, filename)
            try:
                with open(path, "r", encoding="utf-8") as file:
                    snap_data = json.load(file)
            except (json.JSONDecodeError, OSError):
                continue

            timestamp_raw = filename.replace(".json", "")
            try:
                dt = datetime.strptime(timestamp_raw, "%Y%m%d_%H%M%S")
                time_label = dt.strftime("%H:%M")
            except ValueError:
                time_label = timestamp_raw

            market_index = {}
            for game_entry in snap_data.get("games", []):
                game_name = game_entry.get("game")
                for market in game_entry.get("markets", []):
                    pick = market.get("pick")
                    market_name = market.get("market", market.get("type"))
                    if not game_name or not pick:
                        continue

                    key = _market_unique_key(game_name, pick, market_name)

                    raw_bets = market.get("bets_pct", market.get("betsPct", market.get("bets")))
                    raw_handle = market.get("handle_pct", market.get("handlePct", market.get("handle")))
                    raw_odds = market.get("odds", market.get("cuota"))

                    market_index[key] = {
                        "time": time_label,
                        "betsPct": safe_pct(raw_bets),
                        "handlePct": safe_pct(raw_handle),
                        "odds": raw_odds if raw_odds not in (None, "—") else None
                    }

            indexed.append(market_index)

    _snapshot_cache[league_slug] = indexed
    return indexed

def build_pick_history(league_name, game, pick, market_name):
    league_slug = _league_slug(league_name)
    key = _market_unique_key(game, pick, market_name)

    snapshots = _load_league_snapshots(league_slug)

    history = []
    for market_index in snapshots:
        point = market_index.get(key)
        if point is None:
            continue
        if point["betsPct"] is None and point["handlePct"] is None and point["odds"] is None:
            continue
        history.append({
            "time": point["time"],
            "betsPct": point["betsPct"],
            "handlePct": point["handlePct"],
            "odds": point["odds"]
        })

    if MAX_HISTORY_POINTS is not None and len(history) > MAX_HISTORY_POINTS:
        history = history[-MAX_HISTORY_POINTS:]

    return history

# ============================================================
# BUILD PICKS
# ============================================================
def build_picks(raw_data):
    _snapshot_cache.clear()

    def extract_markets(node):
        found = []
        if isinstance(node, list):
            for item in node:
                found.extend(extract_markets(item))
        elif isinstance(node, dict):
            if "markets" in node and isinstance(node["markets"], list):
                found.extend(node["markets"])
            elif "game" in node or "pick" in node:
                found.append(node)
            for value in node.values():
                if isinstance(value, (dict, list)):
                    found.extend(extract_markets(value))
        return found

    markets = extract_markets(raw_data)

    all_items = []
    counter = 0
    seen_picks = set()

    for market in reversed(markets):
        game = market.get("game")
        pick = market.get("pick")

        if not game and not pick:
            continue
        if not market.get("market") and not market.get("type"):
            continue

        market_name = market.get("market", market.get("type"))

        unique_key = f"{game}||{pick}||{market_name}"
        if unique_key in seen_picks:
            continue
        seen_picks.add(unique_key)

        counter += 1

        date, time, iso = parse_match_datetime(market.get("time", ""))

        # 1. Extraer métricas numéricas primero
        raw_bets = market.get("bets_pct", market.get("betsPct", market.get("bets", 50)))
        raw_handle = market.get("handle_pct", market.get("handlePct", market.get("handle", 50)))

        bets = int(safe_float(raw_bets))
        handle = int(safe_float(raw_handle))
        divergence = abs(handle - bets)

        action_text = market.get("action", "🔴 PASAR")
        trend_text = market.get("trend", "➡️ ESTABLE")

        # 2. Lógica Dinámica de Patrones
        diff = handle - bets
        pattern_tag = market.get("pattern", market.get("trend", ""))

        if not pattern_tag or pattern_tag in ["➡️ ESTABLE", "Neutral"]:
            if diff >= 30 and handle >= 70:
                pattern_tag = "⚡ Sharp Lean"
                action_text = "🟢 APOSTAR"
            elif diff >= 45:
                pattern_tag = "🔥 Sharp Divergence"
            elif bets >= 65 and handle <= 40:
                pattern_tag = "🚨 Public Trap"
                action_text = "🔴 PASAR"
            else:
                pattern_tag = trend_text

        if pattern_tag == "⚡ Sharp Lean" and action_text == "🔴 PASAR":
            action_text = "🟢 APOSTAR"

        market_score = safe_score(market.get("market_score", 0))
        confidence = safe_score(market.get("confidence", market_score))
        edge = safe_edge(market.get("edge", 0))

        sharp_score = round(
            (market_score * .45 + confidence * .35 + max(divergence, 0) * .20),
            1
        )

        raw_odds = market.get("odds", market.get("cuota", "—"))
        odds_str = str(raw_odds).strip() if raw_odds is not None else "—"
        
        try:
            odds_val = int(odds_str.replace("+", "").strip())
        except (ValueError, TypeError):
            odds_val = -110

        # Lógica de Riesgo
        risk = "MEDIUM"
        if odds_val >= 150:
            risk = "HIGH"
        elif sharp_score >= 80 and odds_val <= 149:
            risk = "LOW"
        elif sharp_score < 55:
            risk = "HIGH"

        # Modelo y Probabilidades
        raw_model = market.get("model_prob", market.get("model_pct", market.get("modelProb", market.get("modelIsReal"))))
        model_val = safe_pct(raw_model)
        model_is_real = bool(market.get("modelIsReal", model_val and model_val > 0))

        if model_is_real and model_val:
            model_prob = int(model_val)
        else:
            estimated_prob = 50 + int(edge / 2)
            model_prob = int(min(99, max(1, estimated_prob)))

        decimal_odds = american_to_decimal(odds_str) if odds_str != "—" else None

        raw_ev = market.get("ev")
        ev_val = safe_float(raw_ev)
        ev_is_estimated = market.get("evEstimated", False)

        if ev_val is not None and ev_val != 0:
            ev = ev_val
        elif decimal_odds is not None and model_is_real:
            p_model_dec = model_prob / 100.0
            calculated_ev = (p_model_dec * decimal_odds) - 1.0
            ev = round(calculated_ev * 100.0, 1)
        else:
            ev = round(edge * 0.8, 1) if edge > 0 else 0.0
            ev_is_estimated = True

        league_name = market.get("league", "Otras Ligas")

        item = {
            "id": counter,
            "game": game or "Evento desconocido",
            "league": league_name,
            "market": market_name or "Línea estándar",
            "pick": pick or "Sin selección",
            "odds": odds_str,            
            "action": action_text,
            "actionKey": classify_action(action_text),
            "pattern": pattern_tag,
            "trend": pattern_tag,
            "trendKey": classify_trend(pattern_tag),
            "priority": market.get("priority", ""),
            "priorityKey": classify_priority(market.get("priority", "")),
            "stake": safe_float(market.get("stake", 0)),
            "score": sharp_score,
            "marketScore": market_score,
            "confidence": confidence,
            "edge": edge,
            "modelProb": model_prob,
            "modelEstimated": not model_is_real,
            "ev": ev,
            "evEstimated": ev_is_estimated,
            "risk": risk,
            "freePick": (
                classify_action(action_text) == "pass"
                and sharp_score >= 20
            ),
            "reason": market.get("reason", ""),
            "date": date,
            "time": time,
            "iso": iso,
            "whale": detect_whale(market),
            "handlePct": handle,
            "betsPct": bets,
            "divergence": divergence,
            "history": build_pick_history(league_name, game, pick, market_name),
            "status": classify_status(market, iso),
            "result": market.get("result", "PENDING"),
            "roi": market.get("roi")
        }

        all_items.append(item)

    all_items.reverse()
    return all_items

# ============================================================
# GENERATE DASHBOARD
# ============================================================
def generate_dashboard():
    utc_now = datetime.utcnow()
    cdmx_now = utc_now - timedelta(hours=6)
    now_str = cdmx_now.strftime("%Y-%m-%d %H:%M:%S")

    template_path = os.path.join(CURRENT_DIR, "template.html")
    source_json_path = get_latest_file()

    if not os.path.exists(template_path):
        raise FileNotFoundError(f"No existe template.html: {template_path}")

    if not source_json_path or not os.path.exists(source_json_path):
        raise FileNotFoundError(f"No se encontró sharpie.json en {INPUT_DIR}")

    with open(template_path, "r", encoding="utf-8") as file:
        html_template = file.read()

    try:
        with open(source_json_path, "r", encoding="utf-8") as file:
            raw_data = json.load(file)
    except json.JSONDecodeError as e:
        print(f"[ERROR CRÍTICO] El archivo {source_json_path} está corrupto o truncado: {e}")
        raise SystemExit("Proceso detenido para evitar generar un index.html corrupto.")

    all_events = build_picks(raw_data)

    json_data = json.dumps(all_events, ensure_ascii=False)

    html_content = html_template.replace("__GENERATED_AT__", now_str)
    html_content = html_content.replace("__PICKS_JSON__", json_data)

    output_file = os.path.join(OUTPUT_DIR, "index.html")
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    with open(output_file, "w", encoding="utf-8") as file:
        file.write(html_content)

    return output_file

if __name__ == "__main__":
    generate_dashboard()