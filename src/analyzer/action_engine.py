def calculate_action(score, trend, pattern):
    """
    Motor de decisión Sharpie

    Decide:
    - Acción
    - Stake
    - Prioridad
    """


    # -----------------------
    # Sharp Divergence fuerte
    # -----------------------

    if (
        "Sharp Divergence" in pattern
        and score >= 90
        and trend == "📈"
    ):

        return {

            "action": "🟢 APOSTAR",

            "stake": 5.0,

            "priority": "🔥 AHORA"

        }



    # -----------------------
    # Sharp Lean
    # -----------------------

    if (
        "Sharp Lean" in pattern
        and score >= 85
    ):

        return {

            "action": "🔵 INCLINACIÓN",

            "stake": 4.0,

            "priority": "⚡ PRONTO"

        }



    # -----------------------
    # Consenso
    # -----------------------

    if "Consenso" in pattern:

        return {

            "action": "🟡 VIGILAR",

            "stake": 0,

            "priority": "👀 OBSERVAR"

        }



    # -----------------------
    # Público
    # -----------------------

    if "Público" in pattern:

        return {

            "action": "🔴 PASAR",

            "stake": 0,

            "priority": "❌ DESCARTAR"

        }



    # -----------------------
    # Score general
    # -----------------------

    if score >= 70:

        return {

            "action": "🟠 PRECAUCIÓN",

            "stake": 1.0,

            "priority": "⏳ ESPERAR"

        }



    return {

        "action": "🔴 PASAR",

        "stake": 0,

        "priority": "❌ DESCARTAR"

    }