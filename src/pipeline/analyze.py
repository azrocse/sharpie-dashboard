"""Motor matemático unificado de Sharpie.

Cascada única: cuota -> base sin vig -> divergencia Handle-Bets ->
probabilidad modelo -> Edge -> EV -> Kelly fraccional -> stake público.
"""
import json
import math
import os
import re
import statistics
from datetime import datetime, timezone

from config.league_config import enabled_leagues, league_slug
from storage import atomic_write_json

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
INPUT_DIR = os.path.join(BASE_DIR, "data", "parsed")
OUTPUT_DIR = os.path.join(BASE_DIR, "data", "analyzed")
SHARPIE_PATH = os.path.join(OUTPUT_DIR, "sharpie.json")

PROVISIONAL_DIVERGENCE_WEIGHT = 0.12
MAX_DIVERGENCE_ADJUSTMENT = 6.0
KELLY_FRACTION = 0.125
PERSONAL_KELLY_FRACTION = 0.5
MAX_KELLY_FRACTION_PCT = 10.0
STAKE_MIN_UNITS = 1.0
STAKE_MAX_UNITS = 5.0
OPERATIONAL_STAKE_MAX_UNITS = 5.0
LONGSHOT_ODDS_MIN = 151
LONGSHOT_STAKE_CAP = 1.0
PERSONAL_LONGSHOT_STAKE_CAP = 3.0
EXTREME_LONGSHOT_ODDS_MIN = 251
VALUE_EDGE_MIN = 2.0
VALUE_EV_MIN = 3.0
PREMIUM_EDGE_MIN = 4.0
PREMIUM_EV_MIN = 6.5
WHALE_EDGE_MIN = 5.5
WHALE_EV_MIN = 9.0
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

def normalize_market_type(value):
    """Homologa las variantes del feed en los tres rubros visibles."""
    text = str(value or "").strip()
    folded = text.casefold()
    if folded in {"moneyline", "money line", "ml"}:
        return "Moneyline"
    if folded in {"spread", "run line", "puck line", "handicap", "hándicap"}:
        return "Spread"
    if folded == "total" or folded.startswith("ou ") or folded in {"over/under", "totals"}:
        return "Total"
    return None

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
        return "VALUE_ODDS", "MEDIA", OPERATIONAL_STAKE_MAX_UNITS
    return "STANDARD", "CONTROLADA", OPERATIONAL_STAKE_MAX_UNITS

def personal_odds_stake_cap(raw_odds):
    american = american_odds_value(raw_odds)
    if american is not None and american >= LONGSHOT_ODDS_MIN:
        return PERSONAL_LONGSHOT_STAKE_CAP
    return OPERATIONAL_STAKE_MAX_UNITS

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

def _fractional_kelly_stake(model_prob, decimal_odds, ev, fraction, category_caps,
                            minimum, odds_stake_cap, actionable=True, category=None):
    if (not actionable or model_prob is None or decimal_odds is None
            or decimal_odds <= 1.0 or ev is None or ev <= 0):
        return 0.0
    b, p = decimal_odds - 1.0, model_prob / 100.0
    kelly_full = (b * p - (1.0 - p)) / b
    if kelly_full <= 0: return 0.0
    raw_units = kelly_full * fraction * 100.0
    category_cap = category_caps.get(category, OPERATIONAL_STAKE_MAX_UNITS)
    final_units = min(raw_units, category_cap, odds_stake_cap, OPERATIONAL_STAKE_MAX_UNITS)
    return max(minimum, math.floor(final_units * 2.0) / 2.0)

def calculate_stake(model_prob, decimal_odds, ev, confidence_score=None, odds_stake_cap=5.0, actionable=True, category=None):
    """Stake público: 1/8 Kelly, mínimo 1u y saltos de 0.5u."""
    return _fractional_kelly_stake(
        model_prob, decimal_odds, ev, KELLY_FRACTION,
        {"FREE": 2.0, "PREMIUM": 3.5, "WHALE": 5.0}, 1.0,
        odds_stake_cap, actionable, category,
    )

def calculate_personal_stake(model_prob, decimal_odds, ev, raw_odds, actionable=True, category=None):
    """Stake privado: 1/2 Kelly, mínimo 3u y topes FREE/PREMIUM/WHALE."""
    return _fractional_kelly_stake(
        model_prob, decimal_odds, ev, PERSONAL_KELLY_FRACTION,
        {"FREE": 3.0, "PREMIUM": 4.0, "WHALE": 5.0}, 3.0,
        personal_odds_stake_cap(raw_odds), actionable, category,
    )

def evaluate_market_signals(divergence, bets, handle, ev, model_edge, line_move, move_minutes, liquidity):
    """Solo expone las dos señales útiles; no dependen de edge ni EV."""
    signals = []
    if divergence >= 15.0:
        signals.append("SMART_MONEY")
    if bets >= 65.0 and handle >= 65.0 and abs(divergence) <= 10.0:
        signals.append("CONSENSUS")
    return signals or ["NO_ACTION"]

def classify_pick_category(ev, model_edge, market_signals, divergence, model_prob, raw_odds, confidence_score=None, handle=None):
    """Clasifica solo valor financiero respaldado por una señal útil de DK."""
    if model_prob is None or model_edge is None or ev is None:
        return None
    signals = set(market_signals or [])
    if not signals.intersection({"SMART_MONEY", "CONSENSUS"}):
        return None
    american = american_odds_value(raw_odds)
    if american is None or american < -200 or american > 200:
        return None
    if ("SMART_MONEY" in signals and model_edge >= WHALE_EDGE_MIN
            and ev >= WHALE_EV_MIN and divergence >= 35
            and (handle is None or handle >= 65)):
        return "WHALE"
    if ev >= PREMIUM_EV_MIN and model_edge >= PREMIUM_EDGE_MIN:
        return "PREMIUM"
    if ev >= VALUE_EV_MIN and model_edge >= VALUE_EDGE_MIN:
        return "FREE"
    return None

def action_from_category(category):
    if category == "WHALE": return "🐋 WHALE", "bet", "🔥 AHORA"
    if category == "PREMIUM": return "🟢 PREMIUM", "bet", "🔥 AHORA"
    if category == "FREE": return "🔓 FREE PICK", "bet", "⚡ PRONTO"
    return "🟡 SEGUIMIENTO", "pass", "👀 OBSERVAR"

def normalize_history(market, source_specific=False):
    points = []
    seen = set()
    source_points = (
        market.get("playdoitHistory", [])
        if source_specific and market.get("oddsSource") == "PLAYDOIT"
        else market.get("history", [])
    )
    for item in source_points:
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

def get_current_files():
    """El análisis independiente usa únicamente las ligas habilitadas."""
    return [
        os.path.join(INPUT_DIR, f"{league_slug(league['league'])}.json")
        for league in enabled_leagues()
    ]

def _group_market_indices(markets):
    groups = {}
    for index, market in enumerate(markets):
        market_name = (normalize_market_type(market.get("market")) or "").casefold()
        explicit_group = market.get("marketGroup")
        line = market.get("line")
        try: line_key = abs(float(str(line).replace("−", "-")))
        except (TypeError, ValueError): line_key = None
        exact_line = line_key if market_name in {"spread", "total"} else None
        key = (market_name, str(explicit_group), exact_line) if explicit_group is not None else (market_name, None, exact_line)
        groups.setdefault(key, []).append(index)
    resolved = {}
    for (_market_name, explicit_group, _line), indices in groups.items():
        chunks = [indices] if explicit_group is not None or len(indices) == 3 else [indices[i:i + 2] for i in range(0, len(indices), 2)]
        for chunk in chunks:
            for index in chunk:
                resolved[index] = chunk
    return resolved

def _history_map(market):
    result = {}
    for point in normalize_history(market, source_specific=True):
        try:
            stamp = datetime.fromisoformat(str(point.get("time")).replace("Z", "+00:00")).replace(second=0, microsecond=0)
        except (TypeError, ValueError):
            continue
        result[stamp] = point
    return result

def historical_fair_model(market, grouped_markets, decimal_odds, divergence):
    """60% fair actual, 30% mediana 60m, 10% apertura, con flujo limitado."""
    # En este feed los tres mercados admitidos se evalúan contra una sola
    # contraparte exacta. Moneyline es binario; nunca se fabrica un empate.
    if normalize_market_type(market.get("market")) and len(grouped_markets) != 2:
        return None, None, None, "mercado_incompleto", 0
    current_odds = [american_to_decimal(_current_odds(item)) for item in grouped_markets]
    valid_current = [odd for odd in current_odds if odd is not None and odd > 1]
    overround = sum(100 / odd for odd in valid_current)
    # DK puede publicar únicamente las dos contrapartes que ofrece para un
    # Moneyline. Aunque la suma implícita sea menor a 100, ambas se deviguean
    # como el mercado binario recibido; no se fabrica una tercera selección.
    if len(valid_current) < 2 or not 0 < overround <= 115:
        return None, None, None, "mercado_incompleto", 0
    current_fair = devig_probability(decimal_odds, current_odds)
    if current_fair is None:
        return None, None, None, "sin_contraparte", 0
    maps = [_history_map(item) for item in grouped_markets]
    target_index = grouped_markets.index(market)
    common = sorted(set.intersection(*(set(values) for values in maps))) if maps else []
    fair_points = []
    for stamp in common:
        decimals = [american_to_decimal(values[stamp].get("odds")) for values in maps]
        if any(value is None for value in decimals):
            continue
        point_overround = sum(100 / value for value in decimals)
        if not 0 < point_overround <= 115:
            continue
        fair = devig_probability(decimals[target_index], decimals)
        if fair is not None:
            fair_points.append((stamp, fair))
    if fair_points:
        latest = fair_points[-1][0]
        recent = [fair for stamp, fair in fair_points if (latest-stamp).total_seconds() <= 3600]
        base = .60 * current_fair + .30 * statistics.median(recent) + .10 * fair_points[0][1]
    else:
        base = current_fair
    adjustment = max(-MAX_DIVERGENCE_ADJUSTMENT, min(MAX_DIVERGENCE_ADJUSTMENT, divergence * PROVISIONAL_DIVERGENCE_WEIGHT))
    return (round(max(1, min(99, base + adjustment)), 2), current_fair,
            round(adjustment, 2), "sharpie_v2", len(fair_points))

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
    market_type = normalize_market_type(market.get("market"))
    if market_type is None: return None
    if not is_price(raw_odds, market_type): return None
    decimal_odds = american_to_decimal(raw_odds)
    implied_prob = implied_probability(decimal_odds)
    divergence = calculate_divergence(handle, bets)
    all_decimal_odds = []
    for item in grouped_markets:
        odds = _current_odds(item)
        if odds is not None and is_price(odds, item.get("market", "")): all_decimal_odds.append(american_to_decimal(odds))
    model_prob, fair_prob, flow_adjustment, model_source, model_history_points = historical_fair_model(market, grouped_markets, decimal_odds, divergence)
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
    pick_category = classify_pick_category(
        ev, model_edge, market_signals, divergence, model_prob, raw_odds, handle=handle
    )
    action, action_key, priority = action_from_category(pick_category)
    stake = calculate_stake(
        model_prob, decimal_odds, ev, odds_stake_cap=odds_stake_cap,
        actionable=action_key == "bet", category=pick_category,
    )
    game_time = game.get("time_raw") or game.get("startIso") or game.get("time") or market.get("time_raw") or datetime.now().strftime("%H:%M")
    return {
        "league": league_name, "sourceLeague": league_name,
        "sport": game.get("sport") or market.get("sport") or "",
        "game": game.get("game"), "away": game.get("away", ""), "home": game.get("home", ""),
        "date": game.get("date"), "startIso": game.get("startIso"),
        "sourceTimeRaw": game.get("sourceTimeRaw"), "timezone": game.get("timezone"),
        "time": game_time, "market": market_type, "pick": market.get("pick"), "odds": raw_odds,
        "oddsSource": market.get("oddsSource", "DRAFTKINGS_FALLBACK"),
        "draftKingsOdds": market.get("draftKingsOdds"),
        "decimalOdds": round(decimal_odds, 4), "impliedProb": implied_prob, "fairProb": fair_prob,
        "handlePct": handle, "betsPct": bets, "divergence": divergence, "signedDivergence": divergence,
        "flowAdjustment": flow_adjustment, "modelProb": model_prob, "modelSource": model_source,
        "modelHistoryPoints": model_history_points,
        "modelEdge": model_edge, "ev": ev, "stake": stake, "marketSignal": market_signal,
        "marketSignals": market_signals,
        "oddsStakeCap": odds_stake_cap,
        "riskClass": risk_class, "riskLevel": risk_level,
        "lineMove": line_move, "lineMoveMinutes": line_move_minutes, "liquidityStatus": liquidity,
        "trendKey": market_signal, "pattern": MARKET_SIGNAL_LABELS[market_signal], "pickCategory": pick_category,
        "whale": pick_category == "WHALE", "history": history, "action": action, "actionKey": action_key, "priority": priority,
    }

def apply_exposure_limits(results):
    """Máximo 5u por evento y 10u por fecha CDMX, priorizando calidad y valor."""
    picks = [pick for group in results for pick in group["markets"] if pick.get("actionKey") == "bet"]
    rank = {"WHALE": 3, "PREMIUM": 2, "FREE": 1}
    picks.sort(key=lambda p: (-rank.get(p.get("pickCategory"), 0), -float(p.get("ev") or 0), -float(p.get("modelEdge") or 0), p.get("startIso") or ""))
    event_used, day_used = {}, {}
    for pick in picks:
        event_key = (pick.get("date"), pick.get("game"))
        day_key = pick.get("date")
        available = min(5.0-event_used.get(event_key, 0), 10.0-day_used.get(day_key, 0))
        stake = min(float(pick.get("stake") or 0), math.floor(max(0, available)*2)/2)
        if stake < 1:
            pick.update(stake=0.0, pickCategory=None, action="🟡 INFORMATIVO", actionKey="pass", priority="👀 OBSERVAR", exposureLimited=True)
            continue
        pick["stake"] = stake
        event_used[event_key] = event_used.get(event_key, 0) + stake
        day_used[day_key] = day_used.get(day_key, 0) + stake

def prefer_exact_leagues(results):
    """Elimina duplicados de SPORTS cuando DK ofrece la liga exacta."""
    winners = {}
    for group in results:
        for pick in group.get("markets", []):
            key = tuple(
                " ".join(str(value or "").casefold().split())
                for value in (pick.get("date"), pick.get("game"), pick.get("market"), pick.get("pick"))
            )
            priority = 0 if pick.get("league") == "SPORTS" else 1
            current = winners.get(key)
            if current is None or priority > current[0]:
                winners[key] = (priority, pick)
    winner_ids = {id(value[1]) for value in winners.values()}
    cleaned = []
    for group in results:
        markets = [pick for pick in group.get("markets", []) if id(pick) in winner_ids]
        if markets:
            cleaned.append({**group, "markets": markets})
    return cleaned

def analyze_all(parsed_files=None):
    parsed_files = get_current_files() if parsed_files is None else parsed_files
    if not parsed_files:
        raise ValueError("No hay datos actuales para analizar")
    results = []
    for filepath in parsed_files:
        with open(filepath, encoding="utf-8") as source:
            data = json.load(source)
        if not isinstance(data, dict) or not isinstance(data.get("games"), list):
            raise ValueError(f"Estado actual inválido: {filepath}")
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
    if not results:
        raise ValueError("El análisis no produjo mercados válidos; se conserva la salida anterior")
    results = prefer_exact_leagues(results)
    apply_exposure_limits(results)
    atomic_write_json(SHARPIE_PATH, results, compact=True)
    return SHARPIE_PATH

if __name__ == "__main__": analyze_all()
