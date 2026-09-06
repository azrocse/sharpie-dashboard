"""Motor matemático unificado de Sharpie.

Cascada única: cuota -> base sin vig -> divergencia Handle-Bets ->
probabilidad modelo -> Edge -> EV -> medio Kelly -> stake.
"""
import json
import os
import re
from datetime import datetime, timezone

try:
    from pipeline.settle_history_espn import infer_primary_route
except ImportError:
    from settle_history_espn import infer_primary_route

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
INPUT_DIR = os.path.join(BASE_DIR, "data", "parsed")
OUTPUT_DIR = os.path.join(BASE_DIR, "data", "analyzed")
os.makedirs(OUTPUT_DIR, exist_ok=True)
SHARPIE_PATH = os.path.join(OUTPUT_DIR, "sharpie.json")

PROVISIONAL_DIVERGENCE_WEIGHT = 0.15
MAX_DIVERGENCE_ADJUSTMENT = 8.0
KELLY_FRACTION = 0.50
MAX_KELLY_FRACTION_PCT = 10.0
STAKE_MIN_UNITS = 1.0
STAKE_MAX_UNITS = 5.0
OPERATIONAL_STAKE_MAX_UNITS = 3.0
LONGSHOT_ODDS_MIN = 151
LONGSHOT_STAKE_CAP = 0.5
EXTREME_LONGSHOT_ODDS_MIN = 251
VALUE_EDGE_MIN = 2.0
VALUE_EV_MIN = 3.0
PREMIUM_EDGE_MIN = 4.0
PREMIUM_EV_MIN = 6.0
LONGSHOT_EDGE_MIN = 2.0
LONGSHOT_EV_MIN = 5.0
EXTREME_LONGSHOT_EDGE_MIN = 3.0
EXTREME_LONGSHOT_EV_MIN = 8.0
INVALID_TOKENS = {"—", "", "0", "-0", "-1", "NONE", "0%", "NAN"}
MARKET_SIGNAL_LABELS = {
    "STEAM_MOVE": "💨 STEAM MOVE",
    "REVERSE_LINE_MOVEMENT": "↩️ REVERSE LINE MOVEMENT",
    "SMART_MONEY": "🐋 SMART MONEY",
    "PUBLIC_HEAVY": "🚨 PUBLIC HEAVY",
    "CONSENSUS": "📊 CONSENSUS",
    "SHARP_VS_PUBLIC": "⚔️ SHARP VS PUBLIC",
    "BALANCED_ACTION": "⚖️ BALANCED ACTION",
    "LOW_LIQUIDITY": "💧 LOW LIQUIDITY",
    "NO_ACTION": "⚪ NO ACTION",
}
ROUTE_LABELS = {
    ("baseball", "mlb"): "MLB", ("baseball", "kbo"): "KBO",
    ("baseball", "jpn.1"): "NPB", ("baseball", "college-baseball"): "NCAA BASEBALL",
    ("football", "nfl"): "NFL", ("football", "college-football"): "NCAA FOOTBALL",
    ("football", "ufl"): "UFL", ("basketball", "nba"): "NBA",
    ("basketball", "wnba"): "WNBA",
    ("basketball", "mens-college-basketball"): "NCAA BASKETBALL",
    ("basketball", "womens-college-basketball"): "NCAA WOMENS BASKETBALL",
    ("hockey", "nhl"): "NHL", ("hockey", "mens-college-hockey"): "NCAA ICE HOCKEY",
    ("mma", "ufc"): "UFC", ("soccer", "fifa.world"): "WORLD CUP",
    ("soccer", "uefa.champions"): "CHAMPIONS LEAGUE",
    ("soccer", "uefa.europa"): "EUROPA LEAGUE", ("soccer", "eng.1"): "PREMIER LEAGUE",
    ("soccer", "esp.1"): "LA LIGA", ("soccer", "ita.1"): "SERIE A",
    ("soccer", "fra.1"): "LIGUE 1", ("soccer", "ger.1"): "BUNDESLIGA",
    ("soccer", "mex.1"): "LIGA MX", ("soccer", "usa.1"): "MLS",
}

def safe_pct(value):
    try: value = float(value)
    except (TypeError, ValueError): return None
    if not 0.0 <= value <= 100.0: return None
    return round(value, 2)

def clean_odds(raw_odds):
    if raw_odds is None: return None
    text = str(raw_odds).strip().upper().replace("−", "-")
    if text in INVALID_TOKENS: return None
    return "+100" if text == "EVEN" else text

def is_price(raw_odds, market_type=None):
    try: value = float(raw_odds)
    except (TypeError, ValueError): return False
    if abs(value) >= 100: return True
    if 1.01 <= abs(value) <= 50:
        if market_type and re.search(r"\b(spread|handicap|hándicap|total|line|línea|puntos|goles)\b", str(market_type).lower()):
            return False
        return True
    return False

def american_to_decimal(odds):
    try: value = float(odds)
    except (TypeError, ValueError): return None
    if value == 0: return None
    if 1.01 <= abs(value) <= 50: return abs(value)
    return value / 100.0 + 1.0 if value > 0 else 100.0 / abs(value) + 1.0

def implied_probability(decimal_odds):
    if decimal_odds is None or decimal_odds <= 1.0: return None
    return round(100.0 / decimal_odds, 2)

def devig_probability(decimal_odds, all_decimal_odds):
    """Normaliza todos los resultados homólogos; admite mercados 2 y 3 vías."""
    valid = [odd for odd in all_decimal_odds if odd is not None and odd > 1.0]
    if decimal_odds is None or len(valid) < 2: return None
    overround = sum(1.0 / odd for odd in valid)
    if overround <= 0: return None
    return round(((1.0 / decimal_odds) / overround) * 100.0, 2)

def calculate_divergence(handle, bets):
    return round(handle - bets, 2)

def apply_divergence_adjustment(base_prob, divergence):
    adjustment = divergence * PROVISIONAL_DIVERGENCE_WEIGHT
    adjustment = max(-MAX_DIVERGENCE_ADJUSTMENT, min(MAX_DIVERGENCE_ADJUSTMENT, adjustment))
    return round(max(1.0, min(99.0, base_prob + adjustment)), 2)

def calculate_model_probability(decimal_odds, all_decimal_odds, divergence):
    """Siempre calcula modelProb desde cuota y flujo; ignora feeds heredados."""
    if decimal_odds is None or decimal_odds <= 1.0:
        return None, None, None, "sin_cuota_valida"
    fair_prob = devig_probability(decimal_odds, all_decimal_odds)
    if fair_prob is None:
        fair_prob, source = implied_probability(decimal_odds), "implicita_divergencia_sin_devig"
    else:
        source = "propio_devig_divergencia"
    if fair_prob is None:
        return None, None, None, "sin_cuota_valida"
    model_prob = apply_divergence_adjustment(fair_prob, divergence)
    return model_prob, fair_prob, round(model_prob - fair_prob, 2), source

def calculate_model_edge(model_prob, implied_prob):
    if model_prob is None or implied_prob is None: return None
    return round(model_prob - implied_prob, 2)

def calculate_ev(model_prob, decimal_odds):
    if model_prob is None or decimal_odds is None: return None
    return round(((model_prob / 100.0) * decimal_odds - 1.0) * 100.0, 2)

def american_odds_value(raw_odds):
    """Convierte una cuota americana/decimal a su equivalente americano."""
    try:
        value = float(raw_odds)
    except (TypeError, ValueError):
        return None
    if abs(value) >= 100:
        return value
    if 1.01 <= abs(value) <= 50:
        decimal = abs(value)
        return (decimal - 1.0) * 100.0 if decimal >= 2.0 else -100.0 / (decimal - 1.0)
    return None

def classify_odds_risk(raw_odds):
    american = american_odds_value(raw_odds)
    if american is not None and american >= EXTREME_LONGSHOT_ODDS_MIN:
        return "EXTREME_LONGSHOT", "ALTA", LONGSHOT_STAKE_CAP
    if american is not None and american >= LONGSHOT_ODDS_MIN:
        return "LONGSHOT", "ALTA", LONGSHOT_STAKE_CAP
    if american is not None and american >= 101:
        return "VALUE_ODDS", "MEDIA", 1.5
    return "STANDARD", "CONTROLADA", OPERATIONAL_STAKE_MAX_UNITS

def calculate_confidence_score(model_prob, model_edge, ev, divergence, market_signals, raw_odds, liquidity):
    """Mide confianza sin convertir un EV alto en certeza.

    La confianza mide la ventaja relativa contra la cuota, no exige una
    probabilidad absoluta de 55%. EV aporta de forma limitada y las cuotas
    longshot, divergencias extremas y baja liquidez añaden penalización.
    """
    if model_prob is None:
        return 0.0
    signals = set(market_signals or [])
    professional = {"SMART_MONEY", "REVERSE_LINE_MOVEMENT", "STEAM_MOVE", "SHARP_VS_PUBLIC"}
    edge_points = max(0.0, min(40.0, float(model_edge or 0.0) / 10.0 * 40.0))
    signal_points = 15.0 if signals.intersection(professional) else (5.0 if "CONSENSUS" in signals else 0.0)
    divergence_points = max(0.0, min(15.0, float(divergence or 0.0) / 35.0 * 15.0))
    ev_points = max(0.0, min(10.0, float(ev or 0.0)))
    score = edge_points + signal_points + divergence_points + ev_points
    risk_class, _risk_level, _cap = classify_odds_risk(raw_odds)
    if risk_class == "LONGSHOT": score -= 15.0
    elif risk_class == "EXTREME_LONGSHOT": score -= 25.0
    if abs(float(divergence or 0.0)) >= 35.0: score -= 10.0
    if liquidity == "LOW": score -= 25.0
    return round(max(0.0, min(100.0, score)), 1)

def confidence_band(score):
    if score >= 80.0: return "MUY_ALTA", 3.0
    if score >= 70.0: return "ALTA", 2.5
    if score >= 60.0: return "SOLIDA", 2.0
    if score >= 50.0: return "MEDIA", 1.5
    if score >= 40.0: return "BAJA", 1.0
    return "ESPECULATIVA", 0.5

def calculate_stake(model_prob, decimal_odds, ev, confidence_score, odds_stake_cap, actionable):
    """Medio Kelly limitado por confianza, riesgo de cuota y techo operativo."""
    if (not actionable or model_prob is None or decimal_odds is None
            or decimal_odds <= 1.0 or ev is None or ev <= 0):
        return 0.0
    b, p = decimal_odds - 1.0, model_prob / 100.0
    kelly_full = (b * p - (1.0 - p)) / b
    if kelly_full <= 0: return 0.0
    fractional_pct = kelly_full * KELLY_FRACTION * 100.0
    raw_units = STAKE_MIN_UNITS + min(fractional_pct, MAX_KELLY_FRACTION_PCT) / MAX_KELLY_FRACTION_PCT * (STAKE_MAX_UNITS - STAKE_MIN_UNITS)
    _band, confidence_cap = confidence_band(confidence_score)
    final_units = min(raw_units, confidence_cap, odds_stake_cap, OPERATIONAL_STAKE_MAX_UNITS)
    return round(max(LONGSHOT_STAKE_CAP, final_units) * 2.0) / 2.0

def evaluate_market_signals(divergence, bets, handle, ev, model_edge, line_move, move_minutes, liquidity):
    """Devuelve todas las señales compatibles, ordenadas por fuerza informativa."""
    if liquidity == "LOW": return ["LOW_LIQUIDITY"]
    signals = []
    if bets <= 40.0 and divergence >= 15.0 and line_move >= 1.0:
        signals.append("REVERSE_LINE_MOVEMENT")
    if divergence >= 10.0 and line_move >= 1.5 and move_minutes is not None and move_minutes <= 60.0:
        signals.append("STEAM_MOVE")
    if divergence >= 15.0 and ev >= 3.0 and model_edge >= 2.0:
        signals.append("SMART_MONEY")
    if bets <= 40.0 and handle >= 60.0 and divergence >= 20.0:
        signals.append("SHARP_VS_PUBLIC")
    if bets >= 65.0 and divergence <= -15.0:
        signals.append("PUBLIC_HEAVY")
    if bets >= 65.0 and handle >= 65.0 and abs(divergence) <= 10.0:
        signals.append("CONSENSUS")
    if 40.0 <= bets <= 60.0 and 40.0 <= handle <= 60.0 and abs(divergence) <= 10.0:
        signals.append("BALANCED_ACTION")
    return signals or ["NO_ACTION"]

def classify_pick_category(ev, model_edge, market_signals, divergence, model_prob, raw_odds, confidence_score):
    """Jerarquía editorial única, evaluada de mayor a menor exigencia.

    LONGSHOT: pick con valor pero cuota americana >= +151; nunca es oportunidad principal.
    PREMIUM: EV > 6% respaldado por señal profesional y confianza sólida.
    VALUE: EV moderado de 1% a 6% con señal válida de valor o consenso.

    PUBLIC_HEAVY, BALANCED_ACTION, LOW_LIQUIDITY y NO_ACTION son señales de
    contexto/precaución; por sí solas no convierten un pick en recomendación.
    """
    signals = set(market_signals or [])
    professional_signals = {
        "SMART_MONEY", "REVERSE_LINE_MOVEMENT", "STEAM_MOVE", "SHARP_VS_PUBLIC"
    }
    free_signals = professional_signals | {"CONSENSUS"}

    if model_prob is None or model_edge is None or ev is None:
        return None
    risk_class = classify_odds_risk(raw_odds)[0]
    if risk_class == "EXTREME_LONGSHOT":
        if (model_edge >= EXTREME_LONGSHOT_EDGE_MIN and ev >= EXTREME_LONGSHOT_EV_MIN
                and signals.intersection(professional_signals)):
            return "LONGSHOT"
        return None
    if risk_class == "LONGSHOT":
        if (model_edge >= LONGSHOT_EDGE_MIN and ev >= LONGSHOT_EV_MIN
                and signals.intersection(professional_signals)):
            return "LONGSHOT"
        return None
    qualifies_premium = (ev >= PREMIUM_EV_MIN and model_edge >= PREMIUM_EDGE_MIN
                          and signals.intersection(professional_signals) and confidence_score >= 60.0)
    qualifies_value = (ev >= VALUE_EV_MIN and model_edge >= VALUE_EDGE_MIN
                        and signals.intersection(free_signals) and confidence_score >= 40.0)
    if qualifies_premium:
        return "PREMIUM"
    if qualifies_value:
        return "VALUE"
    return None

def action_from_category(category):
    if category == "PREMIUM": return "🟢 PREMIUM", "bet", "🔥 AHORA"
    if category == "VALUE": return "🟢 VALUE PICK", "bet", "⚡ PRONTO"
    if category == "LONGSHOT": return "🟠 LONGSHOT", "speculative", "🎲 OPCIONAL"
    return "🟡 SEGUIMIENTO", "pass", "👀 OBSERVAR"

def normalize_history(market):
    points = []
    seen = set()
    for item in market.get("history", []):
        if not isinstance(item, dict): continue
        bets = safe_pct(item.get("betsPct", item.get("bets")))
        handle = safe_pct(item.get("handlePct", item.get("handle")))
        odds = clean_odds(item.get("odds"))
        if bets is None and handle is None and odds is None: continue
        if bets == 0 and handle == 0: continue
        point = {"time": item.get("time") or item.get("observed_at") or item.get("hora") or "", "betsPct": bets, "handlePct": handle, "odds": odds}
        signature = (point["time"], bets, handle, odds)
        if signature not in seen:
            seen.add(signature)
            points.append(point)
    return points

def _parse_history_time(value):
    text = str(value or "").strip()
    if not text: return None
    try: return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError: pass
    for fmt in ("%H:%M:%S", "%H:%M"):
        try: return datetime.strptime(text, fmt)
        except ValueError: continue
    return None

def calculate_line_movement(history):
    """Cambio de probabilidad implícita entre los dos últimos precios válidos."""
    priced = []
    for point in history:
        decimal = american_to_decimal(point.get("odds"))
        probability = implied_probability(decimal)
        if probability is not None:
            priced.append((point, probability))
    if len(priced) < 2: return 0.0, None
    previous, current = priced[-2], priced[-1]
    line_move = round(current[1] - previous[1], 2)
    previous_time = _parse_history_time(previous[0].get("time"))
    current_time = _parse_history_time(current[0].get("time"))
    if previous_time is None or current_time is None: return line_move, None
    if (previous_time.tzinfo is None) != (current_time.tzinfo is None):
        return line_move, None
    minutes = abs((current_time - previous_time).total_seconds()) / 60.0
    return line_move, round(minutes, 1)

def explicit_liquidity_status(market):
    """No infiere liquidez desde porcentajes; solo acepta una marca real del feed."""
    value = str(market.get("liquidity") or market.get("liquidityStatus") or "").upper()
    return "LOW" if value in {"LOW", "LOW_LIQUIDITY", "BAJA"} else None

def get_latest_files():
    if not os.path.exists(INPUT_DIR): return []
    return sorted(
        os.path.join(INPUT_DIR, name)
        for name in os.listdir(INPUT_DIR)
        if name.lower().endswith(".json") and name.lower() != "sharpie.json"
    )

def _group_market_indices(markets):
    groups = {}
    for index, market in enumerate(markets):
        market_name = str(market.get("market", "")).strip().casefold()
        explicit_group = market.get("marketGroup")
        key = (market_name, str(explicit_group)) if explicit_group is not None else (market_name, None)
        groups.setdefault(key, []).append(index)
    resolved = {}
    for (_market_name, explicit_group), indices in groups.items():
        chunks = [indices] if explicit_group is not None or len(indices) == 3 else [indices[i:i + 2] for i in range(0, len(indices), 2)]
        for chunk in chunks:
            for index in chunk:
                resolved[index] = chunk
    return resolved

def _current_odds(market):
    odds = clean_odds(market.get("odds"))
    if odds is not None: return odds
    for snapshot in reversed(market.get("history", [])):
        if isinstance(snapshot, dict):
            odds = clean_odds(snapshot.get("odds"))
            if odds is not None: return odds
    return None

def process_market(league_name, game, market, grouped_markets):
    if market.get("marketValid") is False: return None
    handle, bets, raw_odds = safe_pct(market.get("handle")), safe_pct(market.get("bets")), _current_odds(market)
    if handle is None or bets is None or raw_odds is None: return None
    market_type = market.get("market", "")
    if not is_price(raw_odds, market_type): return None
    decimal_odds = american_to_decimal(raw_odds)
    implied_prob = implied_probability(decimal_odds)
    divergence = calculate_divergence(handle, bets)
    all_decimal_odds = []
    for item in grouped_markets:
        odds = _current_odds(item)
        if odds is not None and is_price(odds, item.get("market", "")): all_decimal_odds.append(american_to_decimal(odds))
    model_prob, fair_prob, flow_adjustment, model_source = calculate_model_probability(decimal_odds, all_decimal_odds, divergence)
    model_edge = calculate_model_edge(model_prob, implied_prob)
    ev = calculate_ev(model_prob, decimal_odds)
    history = normalize_history(market)
    if (not history or history[-1].get("handlePct") != handle
            or history[-1].get("betsPct") != bets or history[-1].get("odds") != raw_odds):
        observed_at = market.get("observed_at") or market.get("updatedAt") or datetime.now(timezone.utc).isoformat(timespec="seconds")
        history.append({"time": observed_at, "betsPct": bets, "handlePct": handle, "odds": raw_odds})
    line_move, line_move_minutes = calculate_line_movement(history)
    liquidity = explicit_liquidity_status(market)
    market_signals = evaluate_market_signals(
        divergence, bets, handle, ev, model_edge, line_move, line_move_minutes, liquidity
    )
    market_signal = market_signals[0]
    risk_class, risk_level, odds_stake_cap = classify_odds_risk(raw_odds)
    confidence_score = calculate_confidence_score(
        model_prob, model_edge, ev, divergence, market_signals, raw_odds, liquidity
    )
    confidence, confidence_stake_cap = confidence_band(confidence_score)
    pick_category = classify_pick_category(
        ev, model_edge, market_signals, divergence, model_prob, raw_odds, confidence_score
    )
    action, action_key, priority = action_from_category(pick_category)
    stake = calculate_stake(
        model_prob, decimal_odds, ev, confidence_score, odds_stake_cap,
        action_key in {"bet", "speculative"},
    )
    game_time = game.get("time_raw") or game.get("startIso") or game.get("time") or market.get("time_raw") or datetime.now().strftime("%H:%M")
    route_probe = {
        "league": league_name, "sport": game.get("sport") or market.get("sport"),
        "game": game.get("game"), "away": game.get("away"), "home": game.get("home"),
        "market": market_type, "pick": market.get("pick"),
    }
    espn_route = infer_primary_route(route_probe)
    resolved_league = ROUTE_LABELS.get(espn_route, league_name)
    return {
        "league": resolved_league, "sourceLeague": league_name,
        "sport": espn_route[0] if espn_route else (game.get("sport") or market.get("sport") or ""),
        "espnSport": espn_route[0] if espn_route else None,
        "espnLeague": espn_route[1] if espn_route else None,
        "game": game.get("game"), "away": game.get("away", ""), "home": game.get("home", ""),
        "date": game.get("date"), "startIso": game.get("startIso"),
        "sourceTimeRaw": game.get("sourceTimeRaw"), "timezone": game.get("timezone"),
        "time": game_time, "market": market_type, "pick": market.get("pick"), "odds": raw_odds,
        "decimalOdds": round(decimal_odds, 4), "impliedProb": implied_prob, "fairProb": fair_prob,
        "handlePct": handle, "betsPct": bets, "divergence": divergence, "signedDivergence": divergence,
        "flowAdjustment": flow_adjustment, "modelProb": model_prob, "modelSource": model_source,
        "modelEdge": model_edge, "ev": ev, "stake": stake, "marketSignal": market_signal,
        "marketSignals": market_signals,
        "confidenceScore": confidence_score, "confidence": confidence,
        "confidenceStakeCap": confidence_stake_cap, "oddsStakeCap": odds_stake_cap,
        "riskClass": risk_class, "riskLevel": risk_level,
        "lineMove": line_move, "lineMoveMinutes": line_move_minutes, "liquidityStatus": liquidity,
        "trendKey": market_signal, "pattern": MARKET_SIGNAL_LABELS[market_signal], "pickCategory": pick_category,
        "whale": "SMART_MONEY" in market_signals, "history": history, "action": action, "actionKey": action_key, "priority": priority,
    }

def analyze_all(parsed_files=None):
    parsed_files = get_latest_files() if parsed_files is None else parsed_files
    results = []
    for filepath in parsed_files:
        try:
            with open(filepath, encoding="utf-8") as source: data = json.load(source)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict): continue
        league_name = data.get("league", "UNKNOWN")
        league_result = {"league": league_name, "date": datetime.now().strftime("%Y-%m-%d"), "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"), "markets": []}
        for game in data.get("games", []):
            markets = game.get("markets", [])
            grouped_indices = _group_market_indices(markets)
            for index, market in enumerate(markets):
                group = [markets[i] for i in grouped_indices.get(index, [index])]
                processed = process_market(league_name, game, market, group)
                if processed is not None: league_result["markets"].append(processed)
        if league_result["markets"]: results.append(league_result)
    temporary = f"{SHARPIE_PATH}.tmp"
    with open(temporary, "w", encoding="utf-8") as output:
        json.dump(results, output, indent=4, ensure_ascii=False)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, SHARPIE_PATH)
    return SHARPIE_PATH

if __name__ == "__main__": analyze_all()
