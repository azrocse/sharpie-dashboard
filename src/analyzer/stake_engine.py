def calculate_stake(score, pattern):
    """
    Calcula unidades recomendadas.

    Retorna:
    stake: unidades
    """

    # Sharp Divergence

    if "Sharp Divergence" in pattern:

        if score >= 95:
            return 5.0

        elif score >= 90:
            return 4.0

        elif score >= 85:
            return 3.0



    # Sharp Lean

    if "Sharp Lean" in pattern:

        if score >= 85:
            return 3.0

        elif score >= 75:
            return 2.0



    # Consenso

    if "Consenso" in pattern:

        return 0.0



    # Público

    if "Público" in pattern:

        return 0.0



    return 0.0