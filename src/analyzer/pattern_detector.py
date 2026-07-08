def detect_pattern(handle, bets):
    """
    Detecta el comportamiento del mercado
    basado en Handle vs Bets
    """

    edge = handle - bets


    # Dinero muy concentrado en pocos tickets
    if edge >= 40:

        return {

            "pattern": "🔥 Sharp Divergence",

            "pattern_score": 100,

            "reason": (
                "Handle supera ampliamente "
                "el porcentaje de boletos"
            )

        }


    # Diferencia importante
    elif edge >= 20:

        return {

            "pattern": "⚡ Sharp Lean",

            "pattern_score": 85,

            "reason": (
                "Existe concentración de dinero "
                "superior al volumen de apuestas"
            )

        }


    # Mercado equilibrado
    elif abs(edge) <= 5:

        return {

            "pattern": "⚪ Consenso",

            "pattern_score": 50,

            "reason": (
                "Handle y boletos muestran "
                "distribución similar"
            )

        }


    # Público cargado
    elif edge <= -20:

        return {

            "pattern": "🚨 Público",

            "pattern_score": 30,

            "reason": (
                "Mayor porcentaje de boletos "
                "sin respaldo proporcional de dinero"
            )

        }


    # Neutral

    return {

        "pattern": "⚪ Neutral",

        "pattern_score": 60,

        "reason": (
            "Sin divergencia significativa"
        )

    }