def calculate_market_score(handle: float, bets: float) -> int:
    """
    Calcula el score de mercado (0-100) a partir de la divergencia
    handle% vs bets%.

    Bandas de Δ (alineadas a la metodología):
        Δ < 15          -> sin señal / no pick
        15 <= Δ < 40     -> divergencia válida
        Δ >= 40          -> divergencia fuerte

    Args:
        handle: % del dinero (0-100)
        bets: % de boletos/apuestas (0-100)

    Returns:
        Score entero 0-100.

    Raises:
        ValueError: si handle o bets están fuera de [0, 100].
    """
    if not (0 <= handle <= 100):
        raise ValueError(f"handle fuera de rango [0,100]: {handle}")
    if not (0 <= bets <= 100):
        raise ValueError(f"bets fuera de rango [0,100]: {bets}")

    edge = handle - bets
    score = 50.0

    # Divergencia dinero vs boletos — escalado simétrico, sin cliff abrupto
    # (interpolación lineal dentro de cada banda en vez de saltos fijos)
    if edge >= 40:
        score += 45
    elif edge >= 15:
        # interpola 20 -> 45 conforme edge va de 15 a 40
        score += 20 + (edge - 15) * (25 / 25)
    elif edge >= 5:
        score += 10 + (edge - 5) * (10 / 10)
    elif edge > 0:
        score += edge * 2  # 0-5 -> 0-10, gradual
    elif edge < 0:
        # penalización simétrica y proporcional, ya no depende
        # exclusivamente de bets >= 70
        score += max(edge, -50) * 0.7  # cap para no irse a negativo extremo

    # Peso adicional por concentración de dinero
    if handle >= 70:
        score += 5

    # Límites
    score = max(0, min(100, score))

    return round(score)


def market_color(score: float) -> str:
    if score >= 85:
        return "🟢"
    if score >= 65:
        return "🟡"
    return "🔴"