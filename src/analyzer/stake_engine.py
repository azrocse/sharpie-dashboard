def calculate_stake(score, pattern, odds):
    """
    Calcula unidades basadas en Kelly con escala granular completa:
    0.25, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 5.0
    """
    if any(p in pattern for p in ["Consenso", "Público"]):
        return 0.0

    # Cálculo de Kelly
    p = score / 100.0
    b = odds - 1
    q = 1 - p
    
    if (b * p - q) <= 0:
        return 0.0
    
    kelly_pct = (b * p - q) / b

    # Tabla de rangos: (Umbral_Kelly_Minimo, Stake_Asignado)
    # Ordenado de mayor a menor para capturar primero el stake más alto
    escalas = [
        (0.12, 5.0),
        (0.09, 3.5),
        (0.07, 3.0),
        (0.05, 2.5),
        (0.04, 2.0),
        (0.03, 1.5),
        (0.02, 1.0),
        (0.01, 0.5),
        (0.005, 0.25)
    ]

    for umbral, stake in escalas:
        if kelly_pct >= umbral:
            return stake

    return 0.0