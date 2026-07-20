def detect_pattern(handle, bets):
    """
    Detecta el comportamiento del mercado con un formato de salida estandarizado.
    """
    edge = handle - bets
    
    # Definimos una estructura base común para todos los retornos
    result = {
        "pattern": "Neutral",
        "pattern_score": 50,
        "reason": "Sin divergencia significativa"
    }

    if edge >= 40:
        result.update({
            "pattern": "Sharp Divergence",
            "pattern_score": 100,
            "reason": "Handle supera ampliamente el volumen de boletos"
        })
    elif edge >= 20:
        result.update({
            "pattern": "Sharp Lean",
            "pattern_score": 85,
            "reason": "Concentración de dinero superior al volumen"
        })
    elif abs(edge) <= 5:
        result.update({
            "pattern": "Consenso",
            "pattern_score": 50,
            "reason": "Distribución equilibrada"
        })
    elif edge <= -20:
        result.update({
            "pattern": "Público",
            "pattern_score": 30,
            "reason": "Mayor volumen de boletos sin respaldo de dinero"
        })

    return result