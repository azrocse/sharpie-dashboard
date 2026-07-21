"""
generate_dashboard.py -- Generador del panel HTML interactivo Sharpie
Toma el archivo unificado sharpie.json generado por analyze.py y construye index.html
sin clasificaciones de estado (live/finished), unificando todo en un flujo limpio.
"""

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

# Cuántos puntos recientes de evolución mostrar por pick en el dashboard.
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
    if "APOSTAR" in text or "INCLINACIÓN" in text:
        return "bet"
    return "pass"

def classify_trend(text):
    t = (text or "").lower()
    if "sharp" in t or "🔥" in t or "alcista" in t or "entrando" in t:
        return "sharp"
    if "mixto" in t or "cambio" in t or "estable" in t:
        return "mixed"
    if "consenso" in t:
        return "consensus"
    if "público" in t or "public" in t or "bajista" in t or "perdiendo" in t:
        return "public"
    return "other"

def classify_priority(text):
    t = (text or "").upper()
    if "AHORA" in t:
        return "now"
    if "PRONTO" in t:
        return "soon"
    return "watch"

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
    """Convierte momios americanos (ej: -110, +150) a decimal de forma segura."""
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
# DETECCIÓN WHALE
# ============================================================
def detect_whale(market):
    if market.get("whale"):
        return True

    handle = safe_pct(market.get("handle_pct", market.get("handle")))
    bets = safe_pct(market.get("bets_pct", market.get("bets")))

    if handle is not None and bets is not None:
        if handle - bets >= 15:
            return True

    blob = " ".join(
        str(market.get(k, ""))
        for k in ["priority", "action", "reason", "market_trend", "trend"]
    ).lower()

    return "whale" in blob or "🐋" in blob or "divergence" in blob

# ============================================================
# EVOLUCIÓN HISTÓRICA DEL PICK (tickets / dinero / cuota)
# Reconstruida a partir de los snapshots con timestamp que guarda parse.py
# en data/snapshots/{liga}/, usando el mismo criterio de identidad de
# mercado (game + pick + market) que ya se usa como unique_key más abajo.
# ============================================================
_snapshot_cache = {}


def _league_slug(league_name):
    return (league_name or "").strip().lower().replace(" ", "_")


def _market_unique_key(game, pick, market_name):
    return f"{game}||{pick}||{market_name}"


def _load_league_snapshots(league_slug):
    """
    Lee y cachea (por corrida de generate_dashboard) todos los snapshots de
    una liga, indexados por unique_key de mercado para lookup rápido.
    Cada entrada del resultado es un dict {unique_key: {time, betsPct, handlePct, odds}}
    correspondiente a un snapshot, en orden cronológico.
    """
    if league_slug in _snapshot_cache:
        return _snapshot_cache[league_slug]

    league_folder = os.path.join(SNAPSHOTS_DIR, league_slug)
    indexed = []

    if os.path.isdir(league_folder):
        files = sorted(f for f in os.listdir(league_folder) if f.endswith(".json"))

        for filename in files:
            path = os.path.join(league_folder, filename)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    snap_data = json.load(f)
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
    """
    Devuelve la lista lista para el campo "history" del dashboard
    (tickets/dinero/cuota por horario), a partir de los snapshots guardados
    por parse.py. Si aún no hay snapshots para esa liga, devuelve [].
    """
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
# BUILD PICKS (Aplanador de Estructura Jerárquica)
# ============================================================
def build_picks(raw_data):
    print("\n[DEBUG] Iniciando procesamiento de mercados para dashboard...")

    # Cache de snapshots limpio en cada corrida para no arrastrar datos viejos
    # si el proceso vive más de una ejecución (ej. modo servidor/loop).
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
    print(f"[DEBUG] Mercados encontrados: {len(markets)}")

    all_items = []
    counter = 0
    seen_picks = set()

    for market in markets:
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

        raw_bets = market.get("bets_pct", market.get("betsPct", market.get("bets", 50)))
        raw_handle = market.get("handle_pct", market.get("handlePct", market.get("handle", 50)))

        bets = int(safe_float(raw_bets))
        handle = int(safe_float(raw_handle))
        divergence = abs(handle - bets)

        market_score = safe_score(market.get("market_score", 0))
        confidence = safe_score(market.get("confidence", market_score))
        edge = safe_score(market.get("edge", 0))

        sharp_score = round(
            (market_score * .45 + confidence * .35 + max(divergence, 0) * .20),
            1
        )

        risk = "MEDIUM"
        if sharp_score >= 80:
            risk = "LOW"
        elif sharp_score < 55:
            risk = "HIGH"

        raw_model = market.get("model_prob", market.get("model_pct", market.get("modelProb", market.get("modelIsReal"))))
        model_val = safe_pct(raw_model)
        model_is_real = bool(market.get("modelIsReal", model_val and model_val > 0))

        if model_is_real and model_val:
            model_prob = int(model_val)
        else:
            estimated_prob = 50 + int(edge / 2)
            model_prob = int(min(99, max(50, estimated_prob)))

        raw_odds = market.get("odds", market.get("cuota", "—"))
        decimal_odds = None

        if raw_odds is not None and raw_odds != "—":
            val_odds = safe_float(raw_odds)
            if 1.01 < val_odds < 50.0:
                decimal_odds = val_odds
            else:
                decimal_odds = american_to_decimal(raw_odds)

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

        action_text = market.get("action", "🔴 PASAR")
        trend_text = market.get("trend", "➡️ ESTABLE")

        league_name = market.get("league", "Otras Ligas")

        item = {
            "id": counter,
            "game": game or "Evento desconocido",
            "league": league_name,
            "market": market_name or "Línea estándar",
            "pick": pick or "Sin selección",
            "odds": raw_odds,            
            "action": action_text,
            "actionKey": market.get("actionKey", classify_action(action_text)),
            "trend": trend_text,
            "trendKey": classify_trend(trend_text),
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
            "history": build_pick_history(league_name, game, pick, market_name)
        }
        
        all_items.append(item)

    print(f"[DEBUG] Total de eventos unificados cargados: {len(all_items)}")
    return all_items

# ============================================================
# GENERATE DASHBOARD
# ============================================================
def generate_dashboard():
    print("\n--- [DEBUG START: GENERATE DASHBOARD] ---")

    utc_now = datetime.utcnow()
    cdmx_now = utc_now - timedelta(hours=6)
    now_str = cdmx_now.strftime("%Y-%m-%d %H:%M:%S")

    template_path = os.path.join(CURRENT_DIR, "template.html")
    source_json_path = get_latest_file()

    print(f"[DEBUG] Buscando plantilla: {template_path}")
    print(f"[DEBUG] Archivo fuente de datos: {source_json_path}")

    if not os.path.exists(template_path):
        raise FileNotFoundError(f"No existe template.html: {template_path}")

    if not source_json_path or not os.path.exists(source_json_path):
        raise FileNotFoundError(f"No se encontró sharpie.json en {INPUT_DIR}")

    with open(template_path, "r", encoding="utf-8") as file:
        html_template = file.read()

    with open(source_json_path, "r", encoding="utf-8") as file:
        raw_data = json.load(file)

    all_events = build_picks(raw_data)

    stats = {
        "total": len(all_events),
        "bets": len([x for x in all_events if x.get("actionKey") == "bet"]),
        "whales": len([x for x in all_events if x.get("whale")]),
        "stake": round(sum(x.get("stake", 0) for x in all_events), 2)
    }

    json_data = json.dumps(all_events, ensure_ascii=False)

    print("[DEBUG] Estadísticas finales del dashboard:")
    print(f"  Total eventos: {stats['total']}")
    print(f"  Apuestas sugeridas (bets): {stats['bets']}")
    print(f"  Whales detectados: {stats['whales']}")

    html_content = html_template.replace("__GENERATED_AT__", now_str)
    html_content = html_content.replace("__PICKS_JSON__", json_data)

    output_file = os.path.join(OUTPUT_DIR, "index.html")
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    with open(output_file, "w", encoding="utf-8") as file:
        file.write(html_content)

    print(f"[DEBUG] Dashboard generado con éxito en CDMX ({now_str}): {output_file}")
    print("--- [DEBUG END: GENERATE DASHBOARD ] ---\n")
    return output_file

if __name__ == "__main__":
    generate_dashboard()