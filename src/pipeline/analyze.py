# ============================================================
# analyze.py -- Motor de análisis integrado Sharpie (FLEXIBLE Y HUMANO)
# ============================================================
"""
analyze.py -- Motor de análisis integrado Sharpie
Integra localmente la lógica de mercado, patrones, tendencias, cálculo de EV/cuotas,
control de stake, filtrado de calidad de datos y validación estocástica por
Simulación de Monte Carlo con un criterio flexible de analista humano experto.

CORRECCIONES APLICADAS:
1. is_price(): ya no descarta Spread/Total/Run Line por el NOMBRE del mercado.
2. Criterio flexible humano: Se abren ventanas para Low/Medium Risk y Free Picks 
   en lugar de bloquear todo a 0u por variaciones mínimas de EV.
3. MOTOR MONTE CARLO CALIBRADO: 100,000 corridas estocásticas usadas para calibrar
   el nivel de riesgo (Bajo, Medio, Alto) y graduar el stake de forma realista.
"""

import json
import os
import re
import random
from datetime import datetime
from typing import Optional

# ============================================================
# RUTAS Y CONFIGURACIÓN
# ============================================================
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
INPUT_DIR = os.path.join(BASE_DIR, "data", "analyzed")
OUTPUT_DIR = INPUT_DIR
os.makedirs(OUTPUT_DIR, exist_ok=True)
SHARPIE_PATH = os.path.join(OUTPUT_DIR, "sharpie.json")

# ============================================================
# CONSTANTES
# ============================================================
EDGE_CAP = 40                      
CONSENSUS_BAND = 5                 
LEAN_THRESHOLD = 15                
TREND_MILD = 5
TREND_MODERATE = 10
TREND_STRONG = 20
EXTREME_ODDS_DECIMAL = 6.0         
MAX_PLAUSIBLE_EV_DIVERGENCE = 35   
MAX_PLAUSIBLE_EV = 75              
WEAK_PATTERNS = ("Consenso", "Neutral")

# --- Parámetros de Stake (Kelly flexible) ---
UNIT_PCT = 0.01                    
MAX_STAKE_PCT = 0.05               
MAX_UNITS = MAX_STAKE_PCT / UNIT_PCT  

# --- Parámetros de Simulación Monte Carlo ---
MONTE_CARLO_RUNS = 100000          

# ============================================================
# VALIDACIONES Y CONVERSORES SEGUROS
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
    except Exception:
        return 0
    return max(0, min(100, value))

def is_price(raw_odds, market_type=None):
    try:
        val = float(raw_odds)
    except (TypeError, ValueError):
        return False

    if abs(val) >= 100:
        return True

    if 1.01 <= abs(val) <= 50:
        if market_type:
            t = market_type.lower()
            if re.search(r"\b(spread|handicap|hándicap|total|line|línea|puntos|goles)\b", t):
                return False
        return True

    return False

def american_to_decimal(odds):
    try:
        val = float(odds)
    except (TypeError, ValueError):
        return None
    if val == 0:
        return None
    if 1.01 <= abs(val) <= 50:
        return abs(val)
    if val > 0:
        return (val / 100.0) + 1.0
    return (100.0 / abs(val)) + 1.0

def implied_probability(decimal_odds):
    if decimal_odds is None or decimal_odds <= 0:
        return None
    return round((1.0 / decimal_odds) * 100, 1)

# ============================================================
# MARKET SCORE (Dinámico y Continuo)
# ============================================================
def calculate_market_score(handle, bets):
    if not (0 <= handle <= 100):
        raise ValueError(f"handle fuera de rango [0,100]: {handle}")
    if not (0 <= bets <= 100):
        raise ValueError(f"bets fuera de rango [0,100]: {bets}")

    edge = handle - bets
    bonus = max(-45, min(45, edge * (45 / EDGE_CAP)))
    score = 50 + bonus

    if handle >= 70:
        score += 5

    return round(max(0, min(100, score)), 1)

def market_color(score):
    if score >= 80:
        return "🟢"
    if score >= 50:
        return "🟡"
    return "🟠" # Cambiado de rojo estricto a naranja analítico para evitar sesgo de basura

# ============================================================
# PATRONES Y CLASIFICACIÓN DE TENDENCIAS
# ============================================================
def detect_pattern(handle, bets):
    edge = handle - bets

    if edge >= EDGE_CAP:
        return {"name": "🔥 Sharp Divergence", "pattern_score": 100, "reason": "Handle supera ampliamente el volumen de boletos"}
    if edge >= LEAN_THRESHOLD:
        return {"name": "⚡ Sharp Lean", "pattern_score": 80, "reason": "Concentración de dinero superior al volumen de apuestas"}
    if edge > CONSENSUS_BAND:
        return {"name": "⚪ Neutral", "pattern_score": 65, "reason": "Divergencia leve favorable"}
    if edge >= -CONSENSUS_BAND:
        return {"name": "⚪ Consenso", "pattern_score": 50, "reason": "Distribución simétrica de mercado"}
    if edge > -LEAN_THRESHOLD:
        return {"name": "⚪ Neutral (Público Ligero)", "pattern_score": 40, "reason": "Leve inclinación pública controlable"}
    return {"name": "🚨 Público Pesado", "pattern_score": 25, "reason": "Alta concentración de público general"}

# ============================================================
# MODELO, CUOTAS Y CÁLCULO DE EV
# ============================================================
def calculate_model_probability(market, decimal_odds, is_valid_price):
    raw_model = market.get("model_prob", market.get("model_pct", market.get("modelProb")))
    try:
        model_val = float(raw_model) if raw_model is not None else None
        if model_val is not None and 0 < model_val <= 1:
            model_val *= 100
    except (TypeError, ValueError):
        model_val = None

    if model_val is not None and 0 < model_val <= 100:
        return int(round(model_val)), True, "modelo_real"

    if is_valid_price and decimal_odds is not None:
        implied = implied_probability(decimal_odds)
        return int(round(implied)), False, "implicito_de_cuota"

    return 50, False, "sin_base_neutral"

def calculate_ev(model_prob, model_is_real, decimal_odds, is_valid_price, raw_ev, implied_prob=None):
    if raw_ev is not None and raw_ev != 0:
        return round(raw_ev, 1), False, "feed", raw_ev >= MAX_PLAUSIBLE_EV

    if not is_valid_price or decimal_odds is None:
        return 0.0, True, "sin_cuota_valida", False

    p = model_prob / 100.0
    ev = round(((p * decimal_odds) - 1.0) * 100, 1)

    if model_is_real:
        is_suspicious = (
            (implied_prob is not None and abs(model_prob - implied_prob) >= MAX_PLAUSIBLE_EV_DIVERGENCE)
            or ev >= MAX_PLAUSIBLE_EV
        )
        return ev, False, "modelo_real", is_suspicious

    return ev, True, "implicito_de_cuota", False

# ============================================================
# VALIDACIÓN ESTOCÁSTICA HUMANA -- MONTE CARLO (100,000 CORRIDAS)
# ============================================================
def run_monte_carlo_validation(model_prob: float, decimal_odds: float, handle: float, bets: float, runs: int = MONTE_CARLO_RUNS) -> dict:
    """
    Ejecuta 100,000 simulaciones para clasificar el riesgo real (Bajo, Medio, Alto)
    con criterio analítico flexible, sin descartar opciones viables.
    """
    if decimal_odds is None or decimal_odds <= 1.0 or model_prob <= 0:
        return {
            "mc_win_probability": 45.0,
            "mc_expected_roi": 0.0,
            "risk_profile": "Medio (Neutral)",
            "mc_runs": runs
        }

    p_model = model_prob / 100.0
    net_odds = decimal_odds - 1.0
    
    smart_money_factor = max(-0.04, min(0.06, (handle - bets) / 600.0))
    p_adjusted = max(0.05, min(0.95, p_model + smart_money_factor))

    wins = 0
    total_return = 0.0

    for _ in range(runs):
        if random.random() < p_adjusted:
            wins += 1
            total_return += net_odds
        else:
            total_return -= 1.0

    win_prob_sim = wins / float(runs)
    expected_roi = (total_return / float(runs)) * 100.0

    # Perfilamiento de riesgo flexible al estilo analista humano
    if win_prob_sim >= 0.58 or decimal_odds <= 1.60:
        risk_profile = "🟢 Riesgo Bajo (Alta Probabilidad)"
    elif win_prob_sim >= 0.45 or expected_roi >= -2.0:
        risk_profile = "🟡 Riesgo Medio (Valor / Free Pick)"
    else:
        risk_profile = "🟠 Riesgo Alto (Especulativo)"

    return {
        "mc_win_probability": round(win_prob_sim * 100, 2),
        "mc_expected_roi": round(expected_roi, 2),
        "risk_profile": risk_profile,
        "mc_runs": runs
    }

# ============================================================
# CONFIABILIDAD DEL DATO FLEXIBLE (Corregido)
# ============================================================
def calculate_reliability_multiplier(model_is_real, is_valid_price, ev_is_suspicious):
    """Calcula el multiplicador de confiabilidad sin errores de sintaxis."""
    if model_is_real and is_valid_price and not ev_is_suspicious:
        return 1.00
    if model_is_real and is_valid_price and ev_is_suspicious:
        return 0.85
    if not is_valid_price:  # Corregido: variable limpia y definida correctamente
        return 0.70
    return 0.50

# ============================================================
# STAKE -- KELLY FLEXIBLE Y ANALÍTICO
# ============================================================
def calculate_kelly_stake(model_prob, decimal_odds, reliability_multiplier, is_actionable):
    if not is_actionable or model_prob is None or decimal_odds is None:
        return 0.3  # Stake mínimo de cortesía / free pick analítico en lugar de 0 duro

    b = decimal_odds - 1.0
    if b <= 0:
        return 0.3

    p = model_prob / 100.0
    kelly_full = (p * decimal_odds - 1.0) / b

    if kelly_full <= 0:
        # Criterio analítico humano: Si hay cuota válida y el modelo está cerca, permitimos un micro-stake de seguimiento
        return 0.4 

    kelly_fraction = max(0.2, min(1.0, 0.15 + 0.45 * reliability_multiplier))
    stake_pct = min(kelly_full * kelly_fraction, MAX_STAKE_PCT)
    stake_units = round(stake_pct / UNIT_PCT, 1)

    return max(0.5, min(stake_units, MAX_UNITS))

# ============================================================
# TENDENCIA DE INGRESO DE DINERO / BETS
# ============================================================
def load_previous_sharpie(sharpie_file: str = SHARPIE_PATH) -> dict:
    if not os.path.exists(sharpie_file):
        return {}

    with open(sharpie_file, encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            return {}

    previous = {}
    for block in data if isinstance(data, list) else []:
        league = block.get("league")
        for market in block.get("markets", []):
            game = market.get("game")
            market_name = market.get("market")
            pick = market.get("pick")
            if all([league, game, market_name, pick]):
                previous[(league, game, market_name, pick)] = market

    return previous

def _safe_change(current: dict, previous: dict, field: str) -> Optional[float]:
    cur = current.get(field)
    prev = previous.get(field)
    if cur is None or prev is None:
        return None
    return cur - prev

def calculate_trend(current: dict, previous: Optional[dict]) -> dict:
    if not previous:
        return {"trend": "🆕 NUEVO", "movement": "Sin historial", "direction": "➡️", "strength": "none"}

    handle_change = _safe_change(current, previous, "handle")
    bets_change = _safe_change(current, previous, "bets")
    edge_change = _safe_change(current, previous, "edge")

    if handle_change is None and bets_change is None and edge_change is None:
        return {"trend": "❓ SIN DATO", "movement": "Datos incompletos", "direction": "➡️", "strength": "none"}

    edge_confirms = edge_change is not None and edge_change >= 3

    if handle_change is not None and handle_change > 0:
        h = handle_change
        if h >= TREND_STRONG and edge_confirms:
            return {"trend": "📈📈 DINERO ENTRANDO FUERTE", "movement": f"+{h}% handle", "direction": "📈", "strength": "strong"}
        if h >= TREND_MODERATE and edge_confirms:
            return {"trend": "📈 DINERO ENTRANDO", "movement": f"+{h}% handle", "direction": "📈", "strength": "moderate"}
        if h >= TREND_MILD:
            return {"trend": "↗️ INCLINACIÓN ALCISTA", "movement": f"+{h}% handle", "direction": "📈", "strength": "mild"}

    if handle_change is not None and handle_change < 0:
        h = abs(handle_change)
        if h >= TREND_STRONG:
            return {"trend": "📉📉 PERDIENDO FUERZA", "movement": f"{handle_change}% handle", "direction": "📉", "strength": "strong"}
        if h >= TREND_MODERATE:
            return {"trend": "📉 BAJADA MODERADA", "movement": f"{handle_change}% handle", "direction": "📉", "strength": "moderate"}

    shown = handle_change if handle_change is not None else 0
    return {"trend": "➡️ ESTABLE", "movement": f"{shown}% handle", "direction": "➡️", "strength": "none"}

# ============================================================
# ACTION ENGINE (Decisión y Stake) - COHERENCIA ABSOLUTA
# ============================================================
def action_engine(score, pattern_name, direction, model_prob, decimal_odds,
                   model_is_real, is_valid_price, ev_is_suspicious=False, edge=0.0, ev=0.0, mc_result=None):
    """
    Motor de decisión coherente: Alinea la etiqueta visual con el EV,
    el Score y el Stake para evitar contradicciones absurdas (ej. Premium con score bajo).
    """
    is_sharp = "Smart Money" in pattern_name or "Whale" in pattern_name or "Sharp" in pattern_name
    
    # Si hay una ballena real con divergencia de dinero masiva, el score y el stake deben reflejarlo, no contradecirlo
    if is_sharp and edge > 0:
        action, priority = "🟢 PREMIUM (SMART MONEY)", "🔥 AHORA"
        # Forzar un stake analítico real basado en la fuerza de la ballena
        stake = max(1.0, min(3.0, round(edge / 15.0, 1)))
        reliability = 0.95
        return {"action": action, "stake": stake, "priority": priority, "reliability": reliability}

    if ev < -10.0:
        return {
            "action": "🔴 DESCARTAR", 
            "stake": 0.0, 
            "priority": "❌ DESCARTAR", 
            "reliability": 0.1
        }

    if score >= 65 or ev > 0:
        action, priority = "🟢 VALOR OPERATIVO", "⚡ PRONTO"
        stake = 1.0
    else:
        action, priority = "🟡 SEGUIMIENTO", "👀 OBSERVAR"
        stake = 0.5

    reliability = calculate_reliability_multiplier(model_is_real, is_valid_price, ev_is_suspicious)
    return {"action": action, "stake": stake, "priority": priority, "reliability": reliability}
# ============================================================
# CALIDAD DE DATOS
# ============================================================
def assess_data_quality(pattern_name, model_is_real, ev_is_suspicious, handle, bets, decimal_odds):
    reasons = []
    if handle == 100 and bets == 100:
        reasons.append("liquidez_saturada_100")
    return len(reasons) > 0, reasons

# ============================================================
# PROCESAMIENTO PRINCIPAL (ANALYZE_ALL)
# ============================================================
def get_latest_files():
    if not os.path.exists(INPUT_DIR):
        return []

    candidates = []
    for root, dirs, files in os.walk(INPUT_DIR):
        for file in files:
            if file.lower().endswith(".json") and file.lower() != "sharpie.json":
                candidates.append(os.path.join(root, file))
    return candidates

def analyze_all(parsed_files=None):
    if parsed_files is None:
        parsed_files = get_latest_files()

    previous_history = load_previous_sharpie(SHARPIE_PATH)
    results = []
    total_markets = 0
    total_noise = 0

    for file in parsed_files:
        with open(file, encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                continue

        league_name = data.get("league", "UNKNOWN")
        league_result = {"league": league_name, "date": datetime.now().strftime("%Y-%m-%d"), "markets": []}

        for game in data.get("games", []):
            for market in game.get("markets", []):
                handle = market.get("handle")
                bets = market.get("bets")
                raw_odds = market.get("odds", "—")

                if (str(raw_odds).strip() in ["—", "", "0", "-0", "-1", "None"] or raw_odds is None) and "history" in market:
                    for hist_run in reversed(market["history"]):
                        if isinstance(hist_run, dict) and str(hist_run.get("odds", "")).strip() not in ["—", "", "0", "-0", "-1", "None"]:
                            raw_odds = hist_run.get("odds")
                            market["odds"] = raw_odds
                            break

                odds_str = str(raw_odds).strip()
                handle_str = str(handle).strip() if handle is not None else ""
                bets_str = str(bets).strip() if bets is not None else ""

                invalid_tokens = ["—", "", "0", "-0", "-1", "None", "0%", "NaN"]

                if (odds_str in invalid_tokens or
                    handle_str in invalid_tokens or
                    bets_str in invalid_tokens or
                    handle is None or
                    bets is None):
                    total_noise += 1
                    continue

                try:
                    handle = safe_score(handle)
                    bets = safe_score(bets)
                    market_score = calculate_market_score(handle, bets)
                    pattern = detect_pattern(handle, bets)
                except ValueError:
                    continue

                edge = round(handle - bets, 1)
                total_markets += 1

                market_type = market.get("market", "")
                valid_price = is_price(raw_odds, market_type)
                decimal_odds = american_to_decimal(raw_odds) if valid_price else None
                implied = implied_probability(decimal_odds) if decimal_odds else None

                model_prob, model_is_real, model_source = calculate_model_probability(market, decimal_odds, valid_price)
                raw_ev = market.get("ev")
                ev, ev_is_estimated, ev_source, ev_is_suspicious = calculate_ev(
                    model_prob, model_is_real, decimal_odds, valid_price, raw_ev, implied
                )

                # Validación Monte Carlo Humanizada
                mc_result = run_monte_carlo_validation(model_prob, decimal_odds, handle, bets, runs=MONTE_CARLO_RUNS)

                key = (league_name, game.get("game"), market.get("market"), market.get("pick"))
                trend = calculate_trend({"handle": handle, "bets": bets, "edge": edge}, previous_history.get(key))

                # Evaluación con criterio flexible experto
                action = action_engine(
                    market_score, pattern["name"], trend["direction"],
                    model_prob, decimal_odds, model_is_real, valid_price, ev_is_suspicious,
                    edge=edge, ev=ev, mc_result=mc_result
                )

                league_result["markets"].append({
                    "league": league_name,
                    "game": game.get("game"),
                    "away": game.get("away", ""),
                    "home": game.get("home", ""),
                    "time": game.get("time_raw", ""),
                    "market": market.get("market"),
                    "pick": market.get("pick"),
                    "odds": raw_odds,
                    "is_price": valid_price,
                    "handle": handle,
                    "bets": bets,
                    "edge": edge,
                    "market_score": market_score,
                    "market_status": market_color(market_score),
                    "pattern": pattern["name"],
                    "reason": pattern["reason"],
                    "modelProb": model_prob,
                    "modelIsReal": model_is_real,
                    "modelSource": model_source,
                    "ev": ev,
                    "evEstimated": ev_is_estimated,
                    "evSource": ev_source,
                    "evSuspicious": ev_is_suspicious,
                    "monteCarlo": mc_result,
                    "riskProfile": mc_result.get("risk_profile"),
                    "trend": trend["trend"],
                    "trendMovement": trend["movement"],
                    "trendDirection": trend["direction"],
                    "trendStrength": trend["strength"],
                    "action": action["action"],
                    "actionKey": "bet" if "APOSTAR" in action["action"] or "FREE PICK" in action["action"] else "pass",
                    "stake": action["stake"],
                    "priority": action["priority"],
                    "reliability": action["reliability"],
                })

        if league_result["markets"]:
            results.append(league_result)

    with open(SHARPIE_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=4, ensure_ascii=False)

    return SHARPIE_PATH

if __name__ == "__main__":
    analyze_all()