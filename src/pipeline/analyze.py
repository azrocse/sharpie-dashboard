import json
import os
from datetime import datetime
from analyzer.market_score import calculate_market_score, market_color

# --- MANTENEMOS TU ESTRUCTURA ---
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUTPUT = os.path.join(BASE_DIR, "data", "analyzed")
os.makedirs(OUTPUT, exist_ok=True)

# --- NUEVA FUNCIÓN DE VALIDACIÓN ---
def is_price(value):
    """Valida si un valor es un momio (cuota) o una línea (spread/total)."""
    try:
        val = float(value)
        # Los momios americanos suelen ser >= 100 o <= -100 (ej. +120, -110)
        # O valores decimales tipo 1.90. Una línea de spread suele ser pequeña (-4, 1.5, 183.5)
        return abs(val) >= 100 or (1.0 < abs(val) < 5.0)
    except:
        return False

# --- TUS FUNCIONES EXISTENTES (INTEGRAS) ---
def edge_score(edge):
    value = abs(edge)
    if value >= 40: return 100
    if value >= 25: return 85
    if value >= 15: return 70
    if value >= 5: return 50
    return 35

def handle_score(handle, bets):
    edge = handle - bets
    if edge >= 40: return 100
    if edge >= 25: return 90
    if edge >= 15: return 75
    if edge >= 5: return 60
    return 40

def detect_pattern(handle, bets):
    edge = handle - bets
    if edge >= 30:
        return {"name": "🔥 Sharp Divergence", "reason": "Handle supera ampliamente el porcentaje de boletos", "score": 100}
    if abs(edge) <= 5:
        return {"name": "⚪ Consenso", "reason": "Handle y boletos muestran distribución similar", "score": 50}
    if edge <= -20:
        return {"name": "🚨 Público", "reason": "Mayor porcentaje de boletos sin respaldo proporcional de dinero", "score": 30}
    return {"name": "🟡 Mixto", "reason": "Movimiento sin ventaja clara", "score": 60}

def calculate_score(edge, handle, bets):
    pattern = detect_pattern(handle, bets)
    scores = {
        "edge_score": edge_score(edge),
        "handle_score": handle_score(handle, bets),
        "pattern_score": pattern["score"],
        "stability_score": 80
    }
    final = round((scores["edge_score"] * 0.35 + scores["handle_score"] * 0.30 + scores["pattern_score"] * 0.20 + scores["stability_score"] * 0.15))
    return final, scores, pattern

def action_engine(score):
    if score >= 85: return {"action": "🟢 APOSTAR", "stake": 5.0, "priority": "🔥 AHORA"}
    if score >= 70: return {"action": "🔵 INCLINACIÓN", "stake": 3.0, "priority": "⚡ PRONTO"}
    if score >= 55: return {"action": "🟡 VIGILAR", "stake": 0, "priority": "👀 OBSERVAR"}
    return {"action": "🔴 PASAR", "stake": 0, "priority": "❌ DESCARTAR"}

# --- ANALYZE_ALL CORREGIDO ---
def analyze_all(parsed_files):
    results = []
    for file in parsed_files:
        with open(file, encoding="utf-8") as f:
            data = json.load(f)

        league_name = data.get("league", "UNKNOWN")
        league_result = {"league": league_name, "date": datetime.now().strftime("%Y-%m-%d"), "markets": []}

        for game in data["games"]:
            for market in game["markets"]:
                handle = market["handle"]
                bets = market["bets"]
                edge = handle - bets

                score, components, pattern = calculate_score(edge, handle, bets)
                market_score = calculate_market_score(handle, bets)
                action = action_engine(score)
                
                # LA CORRECCIÓN: Separación lógica
                raw_odds = market.get("odds", "—")
                
                # Si el sistema detecta que es una línea, la marcamos para no usarla en cálculos de EV
                # Si es Moneyline, lo tratamos como precio
                display_odds = raw_odds

                league_result["markets"].append({
                    "league": league_name,
                    "sharpie": score,
                    "market_trend": pattern["name"],
                    "game": game["game"],
                    "away": game.get("away", ""),
                    "home": game.get("home", ""),
                    "time": game.get("time_raw", ""),
                    "market": market["market"],
                    "pick": market["pick"],
                    "odds": display_odds,
                    "is_price": is_price(raw_odds), # Flag útil para el dashboard
                    "handle": handle,
                    "bets": bets,
                    "edge": edge,
                    "market_score": market_score,
                    "market_status": market_color(market_score),
                    "score": score,
                    "pattern": pattern["name"],
                    "reason": pattern["reason"],
                    "action": action["action"],
                    "stake": action["stake"],
                    "priority": action["priority"],
                    "components": components
                })
        results.append(league_result)

    output = os.path.join(OUTPUT, "sharpie.json")
    with open(output, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=4, ensure_ascii=False)
    
    print(f"✓ Sharpie generado: {output}")
    return output