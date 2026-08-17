# ============================================================
# analyze.py -- Motor de análisis Sharpie v3 (Modelo Híbrido Tipster)
# ============================================================
"""
Motor de evaluación de picks que combina:
  1. Base estadística: divergencia Handle/Bets + EV del modelo + Monte Carlo.
  2. Capa cualitativa ("feeling" de analista): coherencia cuota↔dinero,
     profundidad de historial, redundancia de fuentes, saturación de liquidez.
  3. Decisión unificada de acción/stake (Kelly real, sin bypass de EV).

SCHEMA DE SALIDA: alineado 1:1 con lo que consume template.html.
No se duplica lógica de tendencia/momentum en Python -- el HTML ya la
calcula desde `history` (getEvolutionAnalysis). Este motor solo entrega
la clasificación estática del snapshot actual + los datos crudos.

Fuente única de verdad por campo (sin redundancia):
  - handlePct / betsPct  -> el HTML deriva "edge" y "moneyEdge" de aquí,
    por lo que NO se emite un campo moneyEdge aparte (evita datos que
    puedan desincronizarse).
  - trendKey -> reemplaza a los dos sistemas paralelos previos
    (detect_pattern + calculate_trend), que podían contradecirse.
"""

import json
import os
import random
import re
from datetime import datetime
from typing import Optional

# ============================================================
# RUTAS
# ============================================================
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
INPUT_DIR = os.path.join(BASE_DIR, "data", "analyzed")
OUTPUT_DIR = INPUT_DIR
os.makedirs(OUTPUT_DIR, exist_ok=True)
SHARPIE_PATH = os.path.join(OUTPUT_DIR, "sharpie.json")

# ============================================================
# CONSTANTES / UMBRALES (ajustables en un solo lugar)
# ============================================================
EDGE_CAP = 40                       # Δ Handle-Bets a partir del cual el score satura
CONSENSUS_BAND = 5                  # |Δ| <= esto = consenso de mercado
LEAN_THRESHOLD = 15                 # Δ >= esto = lean marcado (sharp/public)

MAX_PLAUSIBLE_EV_DIVERGENCE = 35    # separación modelo/implícito que dispara sospecha
MAX_PLAUSIBLE_EV = 75               # EV que ya no es creíble (dato corrupto/feed)

MONTE_CARLO_RUNS = 20000            # suficiente para estabilizar sin costo excesivo

# --- Stake (Kelly fraccional real) ---
UNIT_PCT = 0.01
MAX_STAKE_PCT = 0.05
MAX_UNITS = MAX_STAKE_PCT / UNIT_PCT
STAKE_FLOOR_UNITS = 0.5

# --- Umbrales de decisión ---
EV_DISCARD_THRESHOLD = -2.0         # por debajo de esto, se descarta sin importar patrón
PREMIUM_SCORE = 75
PREMIUM_EV = 0.3
VALUE_SCORE = 60
VALUE_EV = -0.5

random.seed()

# ============================================================
# CONVERSORES SEGUROS
# ============================================================
def safe_float(val):
    if val is None:
        return 0.0
    try:
        if isinstance(val, str):
            val = val.replace('%', '').strip()
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def safe_pct(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return round(max(0.0, min(100.0, value)), 1)


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


INVALID_TOKENS = {"—", "", "0", "-0", "-1", "None", "0%", "NaN", None}


def clean_odds(raw_odds):
    """Normaliza cuota cruda; retorna None si es inválida."""
    if raw_odds is None:
        return None
    s = str(raw_odds).strip()
    if s in INVALID_TOKENS:
        return None
    return raw_odds


# ============================================================
# CLASIFICACIÓN DE MERCADO (trendKey) -- fuente única
# ============================================================
def classify_trend_key(edge):
    """Devuelve la clave que el frontend usa para bucket/badge (sharp/mixed/consensus/public/other)."""
    if edge >= LEAN_THRESHOLD:
        return "sharp"
    if edge > CONSENSUS_BAND:
        return "mixed"
    if edge >= -CONSENSUS_BAND:
        return "consensus"
    if edge > -LEAN_THRESHOLD:
        return "mixed"
    return "public"


def pattern_label(edge):
    if edge >= EDGE_CAP:
        return "🔥 Sharp Divergence", "Handle supera ampliamente el volumen de boletos"
    if edge >= LEAN_THRESHOLD:
        return "⚡ Sharp Lean", "Concentración de dinero superior al volumen de apuestas"
    if edge > CONSENSUS_BAND:
        return "⚪ Divergencia leve favorable", "Divergencia leve favorable"
    if edge >= -CONSENSUS_BAND:
        return "⚪ Consenso", "Distribución simétrica de mercado"
    if edge > -LEAN_THRESHOLD:
        return "⚪ Público ligero", "Leve inclinación pública controlable"
    return "🚨 Público Pesado", "Alta concentración de público general"


# ============================================================
# MODELO Y EV
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
        return round(safe_float(raw_ev), 1), False, "feed", safe_float(raw_ev) >= MAX_PLAUSIBLE_EV

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
# HISTORIAL -- normalizado al schema del frontend
# ============================================================
def normalize_history(market):
    """
    Convierte el historial crudo de la fuente a [{time, betsPct, handlePct, odds}],
    agregando el snapshot actual como último punto. Única fuente de verdad para
    todo análisis temporal -- el motor Python NO recalcula tendencia/momentum,
    eso lo hace el frontend a partir de este arreglo.

    Se descartan puntos "fantasma" donde bets==0 Y handle==0 simultáneamente:
    eso no es una lectura real de mercado, es el estado previo a que exista
    volumen (el mercado recién abrió). Tratarlo como dato real genera falsas
    "contradicciones" de coherencia cuota/dinero en cuanto aparece la primera
    lectura real.
    """
    points = []
    raw_history = market.get("history", [])
    if isinstance(raw_history, list):
        for h in raw_history:
            if not isinstance(h, dict):
                continue
            bets = safe_pct(h.get("bets"))
            handle = safe_pct(h.get("handle"))
            odds = clean_odds(h.get("odds"))
            time_raw = h.get("time") or h.get("hora") or ""
            if bets is None and handle is None and odds is None:
                continue
            if bets == 0 and handle == 0:
                continue  # placeholder de "mercado sin volumen aún", no es un snapshot real
            points.append({"time": time_raw, "betsPct": bets, "handlePct": handle, "odds": odds})
    return points


# ============================================================
# CAPA CUALITATIVA -- "FEELING" DE ANALISTA
# ============================================================
def assess_qualitative_signals(handle, bets, edge, odds, history_points, smart_money_raw,
                                model_is_real, ev_is_suspicious):
    """
    Traduce a números el criterio que aplicaría un tipster humano al leer el pick.
    Retorna un multiplicador de confianza [0.55, 1.20] y las notas que lo explican
    (para construir el `reason` en lenguaje natural).
    """
    confidence = 1.0
    notes = []

    # --- Coherencia cuota <-> dinero (steam real vs. contradictorio) ---
    coherence_flag = None
    if len(history_points) >= 2:
        prev, curr = history_points[-2], history_points[-1]
        prev_odds = american_to_decimal(prev.get("odds")) if prev.get("odds") else None
        curr_odds = american_to_decimal(curr.get("odds")) if curr.get("odds") else None
        if prev_odds and curr_odds:
            # cuota decimal más baja = línea se movió a favor del lado con más dinero
            odds_shortened = (prev_odds - curr_odds) > 0.0005
            handle_grew = (curr.get("handlePct") or 0) > (prev.get("handlePct") or 0)
            if handle_grew and odds_shortened:
                confidence += 0.08
                coherence_flag = "confirmada"
                notes.append("la cuota confirma el dinero (steam real)")
            elif handle_grew and not odds_shortened:
                confidence -= 0.18
                coherence_flag = "contradictoria"
                notes.append("el dinero sube pero la cuota no lo confirma (posible outlier o dinero contrario absorbiendo)")

    # --- Redundancia de fuente: Smart Money% == Δ exacto no es confirmación independiente ---
    if smart_money_raw is not None and abs(safe_float(smart_money_raw) - edge) < 0.5:
        notes.append("Smart Money% replica el Δ Handle-Bets, no es una segunda fuente")
    elif smart_money_raw is not None:
        confidence += 0.05
        notes.append("Smart Money% diverge del Δ crudo, aporta señal independiente")

    # --- Profundidad de historial ---
    n_points = len(history_points)
    if n_points <= 1:
        confidence -= 0.12
        notes.append("un solo punto de historial, sin confirmación temporal")
    elif n_points >= 4:
        confidence += 0.05
        notes.append(f"{n_points} mediciones sustentan la lectura")

    # --- Saturación de liquidez sospechosa ---
    if handle >= 97 and n_points <= 1:
        confidence -= 0.08
        notes.append("concentración casi total (≥97%) sin serie temporal — podría ser una sola apuesta grande, no consenso institucional amplio")

    # --- Divergencia modelo/mercado sospechosa ---
    if model_is_real and ev_is_suspicious:
        confidence -= 0.15
        notes.append("el modelo se separa demasiado de la cuota implícita, dato marcado como sospechoso")

    confidence = max(0.55, min(1.20, round(confidence, 3)))
    return confidence, notes, coherence_flag


# ============================================================
# MONTE CARLO -- ahora conectado a la decisión real
# ============================================================
def run_monte_carlo(model_prob, decimal_odds, confidence, runs=MONTE_CARLO_RUNS):
    if decimal_odds is None or decimal_odds <= 1.0 or model_prob <= 0:
        return {"win_probability": 45.0, "expected_roi": 0.0, "runs": runs}

    # La confianza cualitativa ajusta levemente la probabilidad simulada:
    # un pick con señales contradictorias no debe simular como si fuera limpio.
    p_adjusted = max(0.05, min(0.95, (model_prob / 100.0) * (0.85 + 0.15 * confidence)))
    net_odds = decimal_odds - 1.0

    wins = 0
    total_return = 0.0
    for _ in range(runs):
        if random.random() < p_adjusted:
            wins += 1
            total_return += net_odds
        else:
            total_return -= 1.0

    return {
        "win_probability": round((wins / float(runs)) * 100, 2),
        "expected_roi": round((total_return / float(runs)) * 100, 2),
        "runs": runs,
    }


def classify_risk(mc, decimal_odds, coherence_flag, n_history_points):
    win_prob = mc["win_probability"]
    roi = mc["expected_roi"]

    if win_prob >= 58 or (decimal_odds is not None and decimal_odds <= 1.60):
        risk = "LOW"
    elif win_prob >= 46 or roi >= -2.0:
        risk = "MEDIUM"
    else:
        risk = "HIGH"

    # Degradar riesgo solo cuando hay evidencia real de problema:
    # - Contradicción de steam (dinero sube, cuota no confirma) -> degradación completa,
    #   es una señal de calidad de dato genuinamente mala.
    # - Historial insuficiente por sí solo -> ya NO fuerza a HIGH directo; solo evita
    #   que algo recién visto se declare LOW con exceso de confianza (cae a MEDIUM).
    #   Antes esto tumbaba automáticamente TODO pick fresco a HIGH, sin importar
    #   qué tan bueno fuera el resto de la señal.
    if coherence_flag == "contradictoria":
        risk = {"LOW": "MEDIUM", "MEDIUM": "HIGH", "HIGH": "HIGH"}[risk]
    elif n_history_points <= 1 and risk == "LOW":
        risk = "MEDIUM"

    return risk


# ============================================================
# SCORE HÍBRIDO (estadística + feeling)
# ============================================================
def calculate_hybrid_score(handle, bets, edge, ev, confidence):
    # Componente 1: divergencia handle/bets (0-100)
    bonus = max(-45, min(45, edge * (45 / EDGE_CAP)))
    divergence_score = 50 + bonus
    if handle >= 70:
        divergence_score += 5
    divergence_score = max(0, min(100, divergence_score))

    # Componente 2: EV del modelo (0-100), centrado en 50 -> +/-10 pts por cada 1% de EV
    ev_score = max(0, min(100, 50 + ev * 10))

    stat_score = 0.6 * divergence_score + 0.4 * ev_score

    final_score = max(0, min(100, stat_score * confidence))
    return round(final_score, 1), round(divergence_score, 1), round(ev_score, 1)


# ============================================================
# RELIABILITY (confianza del dato en sí, no del pick)
# ============================================================
def calculate_reliability(model_is_real, is_valid_price, ev_is_suspicious, confidence):
    base = 1.00
    if not model_is_real:
        base -= 0.30
    if not is_valid_price:
        base -= 0.30
    if ev_is_suspicious:
        base -= 0.15
    base = max(0.40, base)
    # La confianza cualitativa modera un poco la confiabilidad final
    return round(max(0.35, min(1.0, base * (0.85 + 0.15 * confidence))), 2)


# ============================================================
# STAKE -- KELLY FRACCIONAL REAL (reemplaza valores fijos)
# ============================================================
def calculate_stake(model_prob, decimal_odds, reliability, risk, is_actionable):
    if not is_actionable or model_prob is None or decimal_odds is None:
        return 0.0

    b = decimal_odds - 1.0
    if b <= 0:
        return 0.0

    p = model_prob / 100.0
    kelly_full = (p * decimal_odds - 1.0) / b
    if kelly_full <= 0:
        return 0.0

    kelly_fraction = max(0.15, min(0.55, 0.15 + 0.40 * reliability))
    risk_multiplier = {"LOW": 1.0, "MEDIUM": 0.75, "HIGH": 0.5}.get(risk, 0.5)

    stake_pct = min(kelly_full * kelly_fraction * risk_multiplier, MAX_STAKE_PCT)
    stake_units = round(stake_pct / UNIT_PCT, 1)
    return max(STAKE_FLOOR_UNITS, min(stake_units, MAX_UNITS))


# ============================================================
# DECISIÓN UNIFICADA -- SIN BYPASS POR PATRÓN
# ============================================================
def decide_action(score, ev, risk, coherence_flag, edge):
    """
    Un solo camino de decisión: el patrón (sharp/whale/etc.) ya está incorporado
    en el score vía la capa cualitativa, así que no hay override que ignore el EV.
    """
    if ev <= EV_DISCARD_THRESHOLD or (coherence_flag == "contradictoria" and edge < LEAN_THRESHOLD):
        return {"action": "🔴 DESCARTAR", "priority": "❌ DESCARTAR", "actionKey": "pass", "is_actionable": False}

    if score >= PREMIUM_SCORE and ev > PREMIUM_EV and risk != "HIGH":
        return {"action": "🟢 PREMIUM", "priority": "🔥 AHORA", "actionKey": "bet", "is_actionable": True}

    if score >= VALUE_SCORE and ev > VALUE_EV:
        return {"action": "🟢 VALOR OPERATIVO", "priority": "⚡ PRONTO", "actionKey": "bet", "is_actionable": True}

    return {"action": "🟡 SEGUIMIENTO", "priority": "👀 OBSERVAR", "actionKey": "pass", "is_actionable": False}


# ============================================================
# REASON -- explicación en lenguaje de tipster
# ============================================================
def build_reason(pattern_reason, notes):
    parts = [pattern_reason] + notes
    return ". ".join(dict.fromkeys(parts)) + "."  # dedup preservando orden


# ============================================================
# PROCESAMIENTO PRINCIPAL
# ============================================================
def get_latest_files():
    if not os.path.exists(INPUT_DIR):
        return []
    candidates = []
    for root, _dirs, files in os.walk(INPUT_DIR):
        for file in files:
            if file.lower().endswith(".json") and file.lower() != "sharpie.json":
                candidates.append(os.path.join(root, file))
    return candidates


def process_market(league_name, game, market):
    handle = safe_pct(market.get("handle"))
    bets = safe_pct(market.get("bets"))
    raw_odds = clean_odds(market.get("odds"))

    # Fallback: si la cuota actual es inválida, usar el último dato válido del historial
    if raw_odds is None and "history" in market:
        for hist_run in reversed(market["history"]):
            if isinstance(hist_run, dict):
                candidate = clean_odds(hist_run.get("odds"))
                if candidate is not None:
                    raw_odds = candidate
                    break

    if handle is None or bets is None or raw_odds is None:
        return None  # ruido / dato incompleto

    edge = round(handle - bets, 1)
    market_type = market.get("market", "")
    valid_price = is_price(raw_odds, market_type)
    decimal_odds = american_to_decimal(raw_odds) if valid_price else None
    implied = implied_probability(decimal_odds) if decimal_odds else None

    model_prob, model_is_real, model_source = calculate_model_probability(market, decimal_odds, valid_price)
    raw_ev = market.get("ev")
    ev, ev_is_estimated, ev_source, ev_is_suspicious = calculate_ev(
        model_prob, model_is_real, decimal_odds, valid_price, raw_ev, implied
    )

    history_points = normalize_history(market)
    # Asegurar que el snapshot actual quede reflejado como último punto del historial
    if not history_points or history_points[-1].get("handlePct") != handle or history_points[-1].get("betsPct") != bets:
        history_points.append({
            "time": market.get("time_raw", datetime.now().strftime("%H:%M")),
            "betsPct": bets, "handlePct": handle, "odds": raw_odds,
        })

    smart_money_raw = market.get("smart_money")
    confidence, notes, coherence_flag = assess_qualitative_signals(
        handle, bets, edge, raw_odds, history_points, smart_money_raw, model_is_real, ev_is_suspicious
    )

    score, divergence_score, ev_score = calculate_hybrid_score(handle, bets, edge, ev, confidence)

    mc = run_monte_carlo(model_prob, decimal_odds, confidence)
    risk = classify_risk(mc, decimal_odds, coherence_flag, len(history_points))

    reliability = calculate_reliability(model_is_real, valid_price, ev_is_suspicious, confidence)

    decision = decide_action(score, ev, risk, coherence_flag, edge)
    stake = calculate_stake(model_prob, decimal_odds, reliability, risk, decision["is_actionable"])

    trend_key = classify_trend_key(edge)
    _pattern_name, pattern_reason = pattern_label(edge)
    reason = build_reason(pattern_reason, notes)

    # Whale = confirmación institucional REAL (no solo cruzar un umbral numérico):
    # requiere lean marcado, cuota confirmando el dinero, historial suficiente y
    # dato confiable. Se calcula una sola vez aquí -- el frontend ya no debe
    # re-derivarlo con su propio heurístico si este campo viene presente.
    whale = (
        trend_key == "sharp"
        and coherence_flag == "confirmada"
        and len(history_points) >= 2
        and reliability >= 0.7
    )

    return {
        "league": league_name,
        "game": game.get("game"),
        "away": game.get("away", ""),
        "home": game.get("home", ""),
        "time": game.get("time_raw", ""),
        "market": market.get("market"),
        "pick": market.get("pick"),

        "odds": raw_odds,
        "isPrice": valid_price,

        "handlePct": handle,
        "betsPct": bets,
        "edge": edge,

        "score": score,
        "divergenceScore": divergence_score,
        "evScore": ev_score,
        "confidence": confidence,

        "modelProb": model_prob,
        "modelIsReal": model_is_real,
        "modelSource": model_source,

        "ev": ev,
        "evEstimated": ev_is_estimated,
        "evSource": ev_source,
        "evSuspicious": ev_is_suspicious,

        "monteCarlo": mc,
        "risk": risk,

        "reliability": reliability,
        "trendKey": trend_key,
        "coherence": coherence_flag,   # "confirmada" | "contradictoria" | None (datos insuficientes)
        "whale": whale,                 # confirmación real, no heurística de umbral crudo
        "reason": reason,

        "history": history_points,

        "action": decision["action"],
        "actionKey": decision["actionKey"],
        "priority": decision["priority"],
        "stake": stake,
        "stakeEstimated": ev_is_estimated or not model_is_real,
    }


def analyze_all(parsed_files=None):
    if parsed_files is None:
        parsed_files = get_latest_files()

    results = []

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
                processed = process_market(league_name, game, market)
                if processed is not None:
                    league_result["markets"].append(processed)

        if league_result["markets"]:
            results.append(league_result)

    with open(SHARPIE_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=4, ensure_ascii=False)

    return SHARPIE_PATH


if __name__ == "__main__":
    analyze_all()