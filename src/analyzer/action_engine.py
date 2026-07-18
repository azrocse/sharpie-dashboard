from typing import TypedDict


class Decision(TypedDict):
    action: str
    stake: float
    priority: str


def calculate_action(
    score: float,
    trend: str,
    pattern: str,
    kelly_fraction: float = 1.0,
) -> Decision:
    """
    Motor de decisión Sharpie.

    Args:
        score: score compuesto (0-100). NOTA: si esto no incorpora ya
            el Δ handle%-bets%, hay que fusionarlo antes de llamar aquí.
        trend: "📈" | "📉" | "➡️"
        pattern: descripción del patrón detectado, e.g. "Sharp Divergence",
            "Sharp Lean", "Consenso", "Público". Se asume un solo patrón
            dominante por pick (ver validación abajo).
        kelly_fraction: fracción de Kelly a aplicar sobre el stake base
            (default 1.0 = full Kelly de la banda). Pásale <1.0 para
            Kelly fraccional según tu regla de exposición.

    Returns:
        Decision con action, stake (en unidades) y priority.

    Raises:
        ValueError: si score no es numérico o pattern es None/vacío.
    """
    if not isinstance(score, (int, float)):
        raise ValueError(f"score debe ser numérico, recibido: {type(score)}")
    if not pattern:
        raise ValueError("pattern no puede ser None o vacío")

    # -----------------------
    # Sharp Divergence fuerte
    # -----------------------
    if "Sharp Divergence" in pattern and score >= 90 and trend == "📈":
        return {
            "action": "🟢 APOSTAR",
            "stake": round(5.0 * kelly_fraction, 2),
            "priority": "🔥 AHORA",
        }

    # -----------------------
    # Sharp Lean (ahora exige trend no-bajista)
    # -----------------------
    if "Sharp Lean" in pattern and score >= 85 and trend != "📉":
        return {
            "action": "🔵 INCLINACIÓN",
            "stake": round(4.0 * kelly_fraction, 2),
            "priority": "⚡ PRONTO",
        }

    # -----------------------
    # Consenso
    # -----------------------
    if "Consenso" in pattern:
        return {"action": "🟡 VIGILAR", "stake": 0, "priority": "👀 OBSERVAR"}

    # -----------------------
    # Público
    # -----------------------
    if "Público" in pattern:
        return {"action": "🔴 PASAR", "stake": 0, "priority": "❌ DESCARTAR"}

    # -----------------------
    # Score general
    # -----------------------
    if score >= 70:
        return {
            "action": "🟠 PRECAUCIÓN",
            "stake": round(1.0 * kelly_fraction, 2),
            "priority": "⏳ ESPERAR",
        }

    return {"action": "🔴 PASAR", "stake": 0, "priority": "❌ DESCARTAR"}