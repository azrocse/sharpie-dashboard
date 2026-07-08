def calculate_market_score(
    handle,
    bets
):

    edge = handle - bets


    score = 50



    # Divergencia dinero vs boletos

    if edge >= 40:

        score += 45


    elif edge >= 25:

        score += 30


    elif edge >= 15:

        score += 20


    elif edge >= 5:

        score += 10



    # Peso adicional por concentración de dinero

    if handle >= 70:

        score += 5



    # Penalización público

    if bets >= 70 and handle < bets:

        score -= 25



    # Limites

    if score > 100:

        score = 100



    if score < 0:

        score = 0



    return score





def market_color(score):


    if score >= 85:

        return "🟢"



    if score >= 65:

        return "🟡"



    return "🔴"