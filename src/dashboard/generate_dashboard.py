import json
import os
from datetime import datetime, timedelta

# ============================================================
# RUTAS
# ============================================================
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
INPUT_DIR = os.path.join(BASE_DIR, "data", "analyzed")
OUTPUT_DIR = BASE_DIR

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
            # ET -> CDMX
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

def classify_event_status(iso):
    try:
        event_time = datetime.fromisoformat(iso)
    except:
        return "finished"

    now = datetime.now()
    diff = (event_time - now).total_seconds()

    if diff > 0:
        return "upcoming"
    if diff > -18000:
        return "live"
    return "finished"

# ============================================================
# CLASIFICADORES
# ============================================================
def classify_action(text):
    text = (text or "").upper()
    if "APOSTAR" in text:
        return "bet"
    return "pass"

def classify_trend(text):
    t = (text or "").lower()
    if "sharp" in t or "🔥" in t:
        return "sharp"
    if "mixto" in t:
        return "mixed"
    if "consenso" in t:
        return "consensus"
    if "public" in t or "público" in t:
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

    handle = safe_pct(market.get("handle_pct"))
    bets = safe_pct(market.get("bets_pct"))

    if handle is not None and bets is not None:
        if handle - bets >= 15:
            return True

    blob = " ".join(
        str(market.get(k, ""))
        for k in ["priority", "action", "reason", "market_trend"]
    ).lower()

    return "whale" in blob or "🐋" in blob

# ============================================================
# BUILD PICKS
# ============================================================
def build_picks(raw_data):
    print("\n[DEBUG] Iniciando análisis universal de mercados...")
    events = {
        "upcoming": [],
        "live": [],
        "finished": []
    }

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

    counter = 0
    seen_picks = set()

    for market in markets:
        game = market.get("game")
        pick = market.get("pick")

        if not game and not pick:
            continue
        if not market.get("market") and not market.get("type"):
            continue

        unique_key = f"{game}||{pick}||{market.get('market', market.get('type'))}"
        if unique_key in seen_picks:
            continue
        seen_picks.add(unique_key)

        counter += 1

        # Fechas y estatus
        date, time, iso = parse_match_datetime(market.get("time", ""))
        status = classify_event_status(iso)

        # 1. Extracción segura de volumen de dinero (BETS y HANDLE)
        raw_bets = market.get("bets_pct", market.get("betsPct", market.get("bets")))
        raw_handle = market.get("handle_pct", market.get("handlePct", market.get("handle")))

        bets = int(safe_float(raw_bets)) if safe_float(raw_bets) is not None else 50
        handle = int(safe_float(raw_handle)) if safe_float(raw_handle) is not None else 50
        divergence = abs(handle - bets)

        # 2. Score y Confianza
        market_score = safe_score(market.get("market_score", 0))
        confidence = safe_score(market.get("confidence", market_score))
        edge = safe_score(market.get("edge", 0))

        # Cálculo dinámico del Score Combinado utilizando la divergencia real calculada
        sharp_score = round(
            (market_score * .45 + confidence * .35 + max(divergence, 0) * .20),
            1
        )

        # Determinar Riesgo en base al Score
        risk = "MEDIUM"
        if sharp_score >= 80:
            risk = "LOW"
        elif sharp_score < 55:
            risk = "HIGH"

        # 3. Extracción de Modelo
        raw_model = market.get("model_prob", market.get("model_pct", market.get("modelProb")))
        model_val = safe_pct(raw_model)

        if model_val and model_val > 0:
            model_prob = int(model_val)
        else:
            estimated_prob = 50 + int(edge / 2)
            model_prob = int(min(99, max(50, estimated_prob)))

        # 4. Cálculo exacto de EV usando cuotas de DraftKings
        raw_odds = market.get("draftkings_odds", market.get("dk_odds", market.get("odds", market.get("price"))))
        decimal_odds = None

        if raw_odds is not None:
            val_odds = safe_float(raw_odds)
            if 1.01 < val_odds < 50.0:
                decimal_odds = val_odds
            else:
                decimal_odds = american_to_decimal(raw_odds)

        # Extraer EV del JSON o calcularlo matemáticamente
        raw_ev = market.get("ev")
        ev_val = safe_float(raw_ev)

        if ev_val is not None and ev_val > 0:
            ev = ev_val
        elif decimal_odds is not None and model_prob > 0:
            p_model_dec = model_prob / 100.0
            calculated_ev = (p_model_dec * decimal_odds) - 1.0
            ev = round(calculated_ev * 100.0, 1)
        else:
            ev = round(edge * 0.8, 1) if edge > 0 else 0.0

        # Objeto de datos final limpio para JS
        item = {
            "id": counter,
            "game": game or "Evento desconocido",
            "league": market.get("league", "Otras Ligas"),
            "market": market.get("market", market.get("type", "Línea estándar")),
            "pick": pick or "Sin selección",
            "action": market.get("action", "🔴 PASAR"),
            "actionKey": classify_action(market.get("action", "")),
            "trend": market.get("market_trend", "🟡 Mixto"),
            "trendKey": classify_trend(market.get("market_trend", "")),
            "priority": market.get("priority", ""),
            "priorityKey": classify_priority(market.get("priority", "")),
            "stake": safe_float(market.get("stake", 0)),
            "score": sharp_score,
            "marketScore": market_score,
            "confidence": confidence,
            "edge": edge,
            "modelProb": model_prob,
            "ev": ev,
            "risk": risk,
            "reason": market.get("reason", ""),
            "date": date,
            "time": time,
            "iso": iso,
            "status": status,
            "whale": detect_whale(market),
            "handlePct": handle,
            "betsPct": bets,
            "divergence": divergence
        }
        
        events[status].append(item)

    print("[DEBUG] Resultado:")
    print(f"  Próximos: {len(events['upcoming'])}")
    print(f"  Live: {len(events['live'])}")
    print(f"  Finalizados: {len(events['finished'])}")

    return events

# ============================================================
# GENERATE DASHBOARD
# ============================================================
def generate_dashboard(events_data):
    print("\n--- [DEBUG START: GENERATE DASHBOARD] ---")

    # Obtener la hora actual exacta ajustada a la CDMX (UTC-6 de forma manual y robusta para entornos cloud)
    utc_now = datetime.utcnow()
    cdmx_now = utc_now - timedelta(hours=6)
    now_str = cdmx_now.strftime("%Y-%m-%d %H:%M:%S")

    current_dir = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(current_dir, "template.html")

    print(f"[DEBUG] Buscando plantilla: {template_path}")

    if not os.path.exists(template_path):
        raise FileNotFoundError(f"No existe template.html: {template_path}")

    with open(template_path, "r", encoding="utf-8") as file:
        html_template = file.read()

    upcoming = events_data.get("upcoming", [])
    live = events_data.get("live", [])
    finished = events_data.get("finished", [])

    all_events = upcoming + live + finished

    stats = {
        "total": len(all_events),
        "upcoming": len(upcoming),
        "live": len(live),
        "finished": len(finished),
        "bets": len([x for x in all_events if x.get("actionKey") == "bet"]),
        "whales": len([x for x in all_events if x.get("whale")]),
        "stake": round(sum(x.get("stake", 0) for x in all_events), 2)
    }

    json_data = json.dumps(all_events, ensure_ascii=False)

    print("[DEBUG] Datos preparados:")
    print(f"  Total eventos: {stats['total']}")
    print(f"  Próximos: {stats['upcoming']}")
    print(f"  Live: {stats['live']}")
    print(f"  Finalizados: {stats['finished']}")

    # Inyecciones en el HTML de salida
    html_content = html_template.replace("__GENERATED_AT__", now_str)
    html_content = html_content.replace("__PICKS_JSON__", json_data)

    repo_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
    output_file = os.path.join(repo_root, "index.html")

    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    with open(output_file, "w", encoding="utf-8") as file:
        file.write(html_content)

    print(f"[DEBUG] Dashboard generado con hora CDMX ({now_str}): {output_file}")
    print("--- [DEBUG END: GENERATE DASHBOARD ] ---\n")