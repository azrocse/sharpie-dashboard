import json
import os
from datetime import datetime, timedelta


# ============================================================
# RUTAS
# ============================================================
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))

INPUT_DIR = os.path.join(BASE_DIR, "data", "analyzed")
SNAPSHOTS_DIR = os.path.join(BASE_DIR, "data", "snapshots")
HISTORY_DIR = os.path.join(BASE_DIR, "data", "history")
OUTPUT_DIR = BASE_DIR

MAX_HISTORY_POINTS = 8


# ============================================================
# LOCALIZAR ARCHIVO FUENTE
# ============================================================
def get_latest_file():
    direct = os.path.join(INPUT_DIR, "sharpie.json")

    if os.path.exists(direct):
        return direct

    if not os.path.exists(INPUT_DIR):
        return None

    candidates = []

    for root, dirs, files in os.walk(INPUT_DIR):
        for file in files:
            if file.lower() == "sharpie.json":
                candidates.append(os.path.join(root, file))

    if not candidates:
        return None

    return max(candidates, key=os.path.getmtime)


# ============================================================
# FECHAS Y HORAS
# ============================================================
def parse_match_datetime(raw):
    now = datetime.now()

    if not raw:
        return (
            now.strftime("%Y-%m-%d"),
            "--:--",
            now.strftime("%Y-%m-%dT00:00:00")
        )

    raw = str(raw).strip()

    formats = [
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(raw, fmt)

            return (
                dt.strftime("%Y-%m-%d"),
                dt.strftime("%H:%M"),
                dt.strftime("%Y-%m-%dT%H:%M:%S")
            )

        except Exception:
            pass

    try:
        if "," in raw:
            date_part, time_part = [
                x.strip()
                for x in raw.split(",", 1)
            ]

            year = now.year
            full = f"{date_part}/{year} {time_part}"

            dt = datetime.strptime(
                full,
                "%m/%d/%Y %I:%M%p"
            )

            dt = dt - timedelta(hours=2)

            return (
                dt.strftime("%Y-%m-%d"),
                dt.strftime("%H:%M"),
                dt.strftime("%Y-%m-%dT%H:%M:%S")
            )

    except Exception:
        pass

    return (
        now.strftime("%Y-%m-%d"),
        raw,
        now.strftime("%Y-%m-%dT00:00:00")
    )


# ============================================================
# CLASIFICADORES
# ============================================================
def classify_action(text):
    text = (text or "").upper()

    if any(
        k in text
        for k in [
            "APOSTAR",
            "INCLINACIÓN",
            "BET",
            "SHARP LEAN",
            "LEAN",
            "TAKE",
            "PREMIUM",
            "VALOR OPERATIVO",
            "VALOR"
        ]
    ):
        return "bet"

    return "pass"


def classify_trend(text):
    t = (text or "").lower()

    if any(
        k in t
        for k in [
            "sharp",
            "🔥",
            "alcista",
            "entrando",
            "divergence",
            "whale"
        ]
    ):
        return "sharp"

    if any(
        k in t
        for k in [
            "mixto",
            "cambio",
            "estable"
        ]
    ):
        return "mixed"

    if "consenso" in t:
        return "consensus"

    if any(
        k in t
        for k in [
            "público",
            "public",
            "bajista",
            "perdiendo",
            "trap"
        ]
    ):
        return "public"

    return "other"


def classify_priority(text):
    t = (text or "").upper()

    if "AHORA" in t:
        return "now"

    if "PRONTO" in t:
        return "soon"

    return "watch"


def classify_status(market, iso_str):
    explicit = market.get("status")

    if explicit:
        return explicit

    if not iso_str:
        return "UPCOMING"

    try:
        event_dt = datetime.strptime(
            iso_str,
            "%Y-%m-%dT%H:%M:%S"
        )

    except ValueError:
        return "UPCOMING"

    if event_dt > datetime.now():
        return "UPCOMING"

    return "LIVE"


# ============================================================
# CONVERSORES Y VALIDACIONES
# ============================================================
def safe_float(val):
    if val is None:
        return 0.0

    try:
        if isinstance(val, str):
            val = (
                val
                .replace("%", "")
                .replace("$", "")
                .strip()
            )

        return float(val)

    except Exception:
        return 0.0


def safe_score(value):
    try:
        value = float(value)

    except Exception:
        return 0.0

    return max(
        0.0,
        min(
            100.0,
            value
        )
    )


def safe_edge(value):
    try:
        value = float(value)

    except Exception:
        return 0.0

    return max(
        -100.0,
        min(
            100.0,
            value
        )
    )


def safe_pct(val):
    if val is None:
        return None

    try:
        if isinstance(val, str):
            val = (
                val
                .replace("%", "")
                .strip()
            )

        num = float(val)

        if 0 < num < 1:
            return num * 100.0

        return num

    except Exception:
        return None


# ============================================================
# CUOTAS AMERICANAS
# ============================================================
def american_to_decimal(american_odds):
    try:
        odds = float(american_odds)

        if odds == 0:
            return None

        if odds > 0:
            return (
                odds / 100.0
            ) + 1.0

        return (
            100.0 / abs(odds)
        ) + 1.0

    except (
        ValueError,
        TypeError
    ):
        return None


def american_implied_probability(american_odds):
    """
    Probabilidad implícita de la cuota.

    +120 = 45.45%
    -110 = 52.38%
    -140 = 58.33%
    """

    try:
        odds = float(american_odds)

        if odds == 0:
            return None

        if odds > 0:
            probability = (
                100.0 /
                (odds + 100.0)
            )

        else:
            probability = (
                abs(odds) /
                (abs(odds) + 100.0)
            )

        return probability * 100.0

    except (
        ValueError,
        TypeError
    ):
        return None


# ============================================================
# WHALE / SHARP MONEY
# ============================================================
def detect_whale(market):
    # Si el motor de análisis confirmó whale institucional real (coherencia +
    # historial), esa es la verdad. Si dice False, NO se corta el heurístico --
    # su confirmación es intencionalmente estricta (exige 2+ snapshots con
    # steam confirmado), así que un False solo significa "no confirmado aún",
    # no "descartado"; el heurístico numérico sigue como red de seguridad.
    if market.get("whale") is True:
        return True

    handle = safe_pct(
        market.get(
            "handle_pct",
            market.get(
                "handle"
            )
        )
    )

    bets = safe_pct(
        market.get(
            "bets_pct",
            market.get(
                "bets"
            )
        )
    )

    if (
        handle is not None
        and bets is not None
    ):
        diff = handle - bets

        if (
            diff >= 30
            or (
                diff >= 15
                and handle >= 70
            )
        ):
            return True

    blob = " ".join(
        str(
            market.get(
                k,
                ""
            )
        )
        for k in [
            "priority",
            "action",
            "reason",
            "market_trend",
            "trend",
            "pattern"
        ]
    ).lower()

    return any(
        k in blob
        for k in [
            "whale",
            "🐋",
            "divergence",
            "sharp lean"
        ]
    )


# ============================================================
# CONFIABILIDAD DEL DATO (multiplicador continuo)
# ============================================================
def calculate_reliability_multiplier(
    model_is_real,
    is_valid_price,
    ev_is_suspicious
):
    if model_is_real and is_valid_price and not ev_is_suspicious:
        return 1.00

    if model_is_real and is_valid_price and ev_is_suspicious:
        return 0.80

    if not model_is_real and is_valid_price:
        return 0.65

    return 0.40


# ============================================================
# SCORE DE MODEL EDGE (Sensibilidad Ampliada)
# ============================================================
def calculate_model_edge_score(model_edge):
    if model_edge is None:
        return 0.0
    elif model_edge <= 0:
        return max(0.0, 20.0 + (model_edge * 20.0))
    elif model_edge < 0.5:
        score = (model_edge / 0.5) * 40.0
    elif model_edge < 1.0:
        score = 40.0 + ((model_edge - 0.5) / 0.5) * 20.0
    elif model_edge < 2.0:
        score = 60.0 + ((model_edge - 1.0) / 1.0) * 20.0
    else:
        score = 100.0

    return round(max(0.0, min(100.0, score)), 1)


# ============================================================
# SCORE DE EV (Valor Esperado Ampliado)
# ============================================================
def calculate_ev_score(ev):
    if ev is None:
        return 0.0
    elif ev <= 0:
        return max(0.0, 20.0 + (ev * 20.0))
    elif ev < 0.5:
        score = (ev / 0.5) * 40.0
    elif ev < 1.0:
        score = 40.0 + ((ev - 0.5) / 0.5) * 20.0
    elif ev < 2.0:
        score = 60.0 + ((ev - 1.0) / 1.0) * 20.0
    else:
        score = 100.0

    return round(max(0.0, min(100.0, score)), 1)


# ============================================================
# VALUE SCORE
# ============================================================
def calculate_value_score(
    model_edge_score,
    ev_score
):
    score = (
        model_edge_score * 0.60
        +
        ev_score * 0.40
    )

    return round(
        max(
            0.0,
            min(
                100.0,
                score
            )
        ),
        1
    )


# ============================================================
# FINAL SCORE (CORREGIDO PARA DAR PESO REAL AL SMART MONEY)
# ============================================================
def calculate_final_score(
    value_score,
    market_score,
    reliability_multiplier,
    edge_dinero,
    is_whale,
    signal_type
):
    # Base por Edge de Dinero (Divergencia institucional)
    if edge_dinero is None:
        dinero_score = 0.0
    else:
        dinero_score = min(100.0, max(0.0, 50.0 + (edge_dinero * 1.25)))

    # Ponderación dinámica adaptada para empujar los Premium con Smart Money
    if is_whale or "Smart Money" in str(signal_type):
        base_score = (value_score * 0.20) + (market_score * 0.20) + (dinero_score * 0.60)
        base_score = max(base_score, 55.0) # Piso mínimo garantizado para ballenas
    else:
        base_score = (value_score * 0.40) + (market_score * 0.30) + (dinero_score * 0.30)

    base_score = max(0.0, min(100.0, base_score))
    final = base_score * reliability_multiplier

    return round(
        max(
            0.0,
            min(
                100.0,
                final
            )
        ),
        1
    )


# ============================================================
# EVALUACIÓN GENERAL
# ============================================================
def classify_evaluation(final_score):
    if final_score >= 55:
        return "PREMIUM"
    if final_score >= 40:
        return "STRONG"
    if final_score >= 25:
        return "LEAN"
    if final_score >= 15:
        return "WATCH"
    return "DESCARTAR"


# ============================================================
# STAKE -- calculado aquí, con las MISMAS variables que deciden
# evaluación/riesgo, para que nunca se desalinee con lo que el
# usuario ve en el badge (antes: stake venía de analyze.py con su
# propio score interno, que casi nunca coincidía con final_score).
# ============================================================
def calculate_stake_units(final_score, risk, reliability_multiplier, evaluation, ev):
    if evaluation == "DESCARTAR" or final_score < 25 or ev <= -0.5:
        return 0.0

    kelly_like = max(0.0, (final_score - 25.0) / 75.0)  # 0 en el piso de "LEAN", 1 en score=100
    risk_multiplier = {"LOW": 1.0, "MEDIUM": 0.7, "HIGH": 0.4}.get(risk, 0.4)

    stake = kelly_like * risk_multiplier * reliability_multiplier * 3.0  # techo ~3u
    stake = max(0.5, min(3.0, stake)) if stake > 0 else 0.0
    return round(stake, 1)


# ============================================================
# RIESGO (con ajuste por Monte Carlo, si viene del motor de análisis)
# ============================================================
def calculate_risk(
    final_score,
    reliability_multiplier,
    odds_str,
    monte_carlo=None
):
    try:
        odds_val = int(
            str(
                odds_str
            )
            .replace(
                "+",
                ""
            )
            .strip()
        )

    except (
        ValueError,
        TypeError
    ):
        odds_val = -110

    if final_score >= 80:
        risk = "LOW"

    elif final_score >= 65:
        risk = "LOW" if reliability_multiplier >= 0.80 else "MEDIUM"

    elif final_score >= 50:
        risk = "MEDIUM"

    else:
        risk = "HIGH"

    if risk == "LOW" and odds_val >= 200:
        risk = "MEDIUM"

    # Antes esta simulación se calculaba en analyze.py y nunca llegaba a
    # ninguna decisión real -- aquí sí se usa: una probabilidad de victoria
    # simulada muy baja no debería mostrarse como riesgo bajo aunque el
    # score de mercado se vea bien, y viceversa no mejora el riesgo, solo
    # puede empeorarlo (la simulación es una segunda opinión, no un bono).
    if isinstance(monte_carlo, dict):
        mc_win = monte_carlo.get("win_probability")
        if mc_win is not None:
            order = ["LOW", "MEDIUM", "HIGH"]
            idx = order.index(risk) if risk in order else 2
            if mc_win < 35:
                idx = min(idx + 2, 2)
            elif mc_win < 48:
                idx = min(idx + 1, 2)
            risk = order[idx]

    return risk


# ============================================================
# EVOLUCIÓN HISTÓRICA
# ============================================================
_snapshot_cache = {}


def _league_slug(league_name):
    return (
        league_name or ""
    ).strip().lower().replace(
        " ",
        "_"
    )


def _market_unique_key(
    game,
    pick,
    market_name
):
    return (
        f"{game}||"
        f"{pick}||"
        f"{market_name}"
    )


def _load_league_snapshots(
    league_slug
):
    if league_slug in _snapshot_cache:
        return _snapshot_cache[
            league_slug
        ]

    league_folder = os.path.join(
        SNAPSHOTS_DIR,
        league_slug
    )

    indexed = []

    if os.path.isdir(
        league_folder
    ):
        files = sorted(
            f
            for f in os.listdir(
                league_folder
            )
            if f.endswith(
                ".json"
            )
        )

        for filename in files:
            path = os.path.join(
                league_folder,
                filename
            )

            try:
                with open(
                    path,
                    "r",
                    encoding="utf-8"
                ) as file:
                    snap_data = json.load(
                        file
                    )

            except (
                json.JSONDecodeError,
                OSError
            ):
                continue

            timestamp_raw = (
                filename.replace(
                    ".json",
                    ""
                )
            )

            try:
                dt = datetime.strptime(
                    timestamp_raw,
                    "%Y%m%d_%H%M%S"
                )

                time_label = dt.strftime(
                    "%H:%M"
                )

            except ValueError:
                time_label = timestamp_raw

            market_index = {}

            for game_entry in snap_data.get(
                "games",
                []
            ):
                game_name = game_entry.get(
                    "game"
                )

                for market in game_entry.get(
                    "markets",
                    []
                ):
                    pick = market.get(
                        "pick"
                    )

                    market_name = market.get(
                        "market",
                        market.get(
                            "type"
                        )
                    )

                    if (
                        not game_name
                        or not pick
                    ):
                        continue

                    key = _market_unique_key(
                        game_name,
                        pick,
                        market_name
                    )

                    raw_bets = market.get(
                        "bets_pct",
                        market.get(
                            "betsPct",
                            market.get(
                                "bets"
                            )
                        )
                    )

                    raw_handle = market.get(
                        "handle_pct",
                        market.get(
                            "handlePct",
                            market.get(
                                "handle"
                            )
                        )
                    )

                    raw_odds = market.get(
                        "odds",
                        market.get(
                            "cuota"
                        )
                    )

                    market_index[key] = {
                        "time": time_label,
                        "betsPct": safe_pct(
                            raw_bets
                        ),
                        "handlePct": safe_pct(
                            raw_handle
                        ),
                        "odds": (
                            raw_odds
                            if raw_odds
                            not in (
                                None,
                                "—"
                            )
                            else None
                        )
                    }

            indexed.append(
                market_index
            )

    _snapshot_cache[
        league_slug
    ] = indexed

    return indexed


def build_pick_history(
    league_name,
    game,
    pick,
    market_name
):
    league_slug = _league_slug(
        league_name
    )

    key = _market_unique_key(
        game,
        pick,
        market_name
    )

    snapshots = _load_league_snapshots(
        league_slug
    )

    history = []

    for market_index in snapshots:
        point = market_index.get(
            key
        )

        if point is None:
            continue

        if (
            point["betsPct"] is None
            and point["handlePct"] is None
            and point["odds"] is None
        ):
            continue

        history.append(
            {
                "time": point[
                    "time"
                ],
                "betsPct": point[
                    "betsPct"
                ],
                "handlePct": point[
                    "handlePct"
                ],
                "odds": point[
                    "odds"
                ]
            }
        )

    if (
        MAX_HISTORY_POINTS is not None
        and len(history)
        > MAX_HISTORY_POINTS
    ):
        history = history[
            -MAX_HISTORY_POINTS:
        ]

    return history


# ============================================================
# BUILD PICKS
# ============================================================
def build_picks(raw_data):
    _snapshot_cache.clear()

    def extract_markets(node):
        found = []
        if isinstance(node, list):
            for item in node:
                found.extend(extract_markets(item))
        elif isinstance(node, dict):
            if "markets" in node and isinstance(node["markets"], list):
                found.extend(node["markets"])
            elif "game" in node or "pick" in node:
                found.append(node)
            for value in node.values():
                if isinstance(value, (dict, list)):
                    found.extend(extract_markets(value))
        return found

    markets = extract_markets(raw_data)
    all_items = []
    counter = 0
    seen_picks = set()

    for market in reversed(markets):
        game = market.get("game")
        pick = market.get("pick")

        if not game and not pick:
            continue

        if not market.get("market") and not market.get("type"):
            continue

        market_name = market.get("market", market.get("type"))
        unique_key = f"{game}||{pick}||{market_name}"

        if unique_key in seen_picks:
            continue

        seen_picks.add(unique_key)
        counter += 1

        date, time, iso = parse_match_datetime(market.get("time", ""))

        # ----------------------------------------------------
        # 1. METRICAS DE VOLUMEN (HANDLE / BETS / MONEY EDGE)
        # ----------------------------------------------------
        raw_bets = market.get("bets", 50.0)
        raw_handle = market.get("handle", 50.0)

        bets = safe_pct(raw_bets) if safe_pct(raw_bets) is not None else 50.0
        handle = safe_pct(raw_handle) if safe_pct(raw_handle) is not None else 50.0
        
        json_money_edge = float(market.get("edge", handle - bets))

        # ----------------------------------------------------
        # 2. CUOTA Y PROBABILIDAD IMPLÍCITA
        # ----------------------------------------------------
        raw_odds = market.get("odds", "—")
        odds_str = str(raw_odds).strip() if raw_odds is not None else "—"
        implied_prob = american_implied_probability(odds_str) if odds_str != "—" else None

        # ----------------------------------------------------
        # 3. PROBABILIDAD DEL MODELO Y MODEL EDGE REAL
        # ----------------------------------------------------
        raw_model = market.get("modelProb")
        model_prob = None

        if raw_model is not None:
            try:
                val = float(raw_model)
                model_prob = val * 100.0 if 0 < val <= 1.0 else val
            except (ValueError, TypeError):
                model_prob = None

        if model_prob is not None and implied_prob is not None:
            model_edge = model_prob - implied_prob
        else:
            model_edge = 0.0

        model_is_real = bool(market.get("modelIsReal", False))

        # ----------------------------------------------------
        # 4. EV Y ESTRUCTURA DE SCORE
        # ----------------------------------------------------
        raw_ev = market.get("ev")
        if raw_ev is not None and safe_float(raw_ev) != 0:
            ev = round(safe_float(raw_ev), 2)
            ev_estimated = bool(market.get("evEstimated", False))
        else:
            decimal_odds = american_to_decimal(odds_str) if odds_str != "—" else None
            if model_prob is not None and decimal_odds is not None:
                ev = round(((model_prob / 100.0) * decimal_odds - 1.0) * 100.0, 2)
                ev_estimated = False
            else:
                ev = 0.0
                ev_estimated = True

        action_text = market.get("action", "🔴 PASAR")
        # trendKey: si el motor de análisis ya lo clasificó, esa es la fuente de verdad.
        # Solo se re-deriva por texto para datos legado que no traen trendKey.
        pattern_tag = market.get("pattern", market.get("trend", market.get("reason", "⚪ Neutral")))
        explicit_trend_key = market.get("trendKey")

        # market_score restaurado: analyze.py v3 renombró este campo a "score" para
        # calzar con el HTML, y luego a "divergenceScore" para el desglose -- aquí se
        # busca en ese orden en vez de asumir el nombre viejo que ya no existe.
        market_score = safe_score(market.get("divergenceScore", market.get("market_score", 0)))

        signed_divergence = round(handle - bets, 1)
        divergence = round(abs(signed_divergence), 1)

        reliability_multiplier = market.get("reliability")
        if reliability_multiplier is None:
            reliability_multiplier = calculate_reliability_multiplier(
                model_is_real,
                bool(market.get("is_price", False)),
                bool(market.get("evSuspicious", False))
            )
        reliability_multiplier = max(0.0, min(1.0, safe_float(reliability_multiplier)))

        model_edge_score = calculate_model_edge_score(model_edge)
        ev_score = calculate_ev_score(ev)
        value_score = calculate_value_score(model_edge_score, ev_score)
        
        # Detección de ballena para el cálculo optimizado del score final
        is_whale_flag = detect_whale(market)
        final_score = calculate_final_score(
            value_score, 
            market_score, 
            reliability_multiplier, 
            json_money_edge, 
            is_whale_flag, 
            pattern_tag
        )

        monte_carlo = market.get("monteCarlo") if isinstance(market.get("monteCarlo"), dict) else None
        evaluation = classify_evaluation(final_score)
        # Un EV negativo no debe mostrarse con una etiqueta de "STRONG/PREMIUM" aunque
        # el resto del score (dominado por divergencia institucional) se vea bien --
        # el texto del badge debe ser consistente con que ya no es accionable.
        if ev <= -0.5 and evaluation in ("PREMIUM", "STRONG"):
            evaluation = "LEAN"
        risk = calculate_risk(final_score, reliability_multiplier, odds_str, monte_carlo)
        stake = calculate_stake_units(final_score, risk, reliability_multiplier, evaluation, ev)

        # Confianza cualitativa REAL del motor de análisis (0.55-1.20, es un
        # multiplicador, no un porcentaje ya escalado). Antes esta clave se
        # sobreescribía con reliability_multiplier*100 -- eso ya vive en su
        # propia clave "reliability" más abajo, no hace falta duplicarlo aquí
        # con otra escala distinta bajo el mismo nombre.
        qualitative_confidence = market.get("confidence")
        if qualitative_confidence is None:
            qualitative_confidence = 1.0
        else:
            qualitative_confidence = safe_float(qualitative_confidence)

        # ----------------------------------------------------
        # 5. OBJETO FINAL PARA EL DASHBOARD
        # ----------------------------------------------------
        item = {
            "id": counter,
            "game": game or "Evento desconocido",
            "league": market.get("league", "Otras Ligas"),
            "market": market_name or "Línea estándar",
            "pick": pick or "Sin selección",
            "odds": odds_str,
            "action": action_text,
            "actionKey": market.get("actionKey", classify_action(action_text)),
            "pattern": pattern_tag,
            "trend": pattern_tag,
            "trendKey": explicit_trend_key if explicit_trend_key else classify_trend(pattern_tag),
            "priority": market.get("priority", "👀 OBSERVAR"),
            "priorityKey": classify_priority(market.get("priority", "")),
            "stake": stake,
            "score": final_score,
            "finalScore": final_score,
            "valueScore": value_score,
            "sharpScore": market_score,
            "modelEdgeScore": model_edge_score,
            "evScore": ev_score,
            "marketScore": market_score,
            "divergenceScore": market_score,
            "confidence": qualitative_confidence,

            "modelProb": round(model_prob, 2) if model_prob is not None else None,
            "modelEstimated": not model_is_real,
            "impliedProb": round(implied_prob, 2) if implied_prob is not None else None,
            "modelEdge": round(model_edge, 2),
            "moneyEdge": round(json_money_edge, 2),
            
            "ev": ev,
            "evEstimated": ev_estimated,
            "evaluation": evaluation,
            "risk": risk,
            "monteCarlo": monte_carlo,
            "coherence": market.get("coherence"),
            "reliability": round(reliability_multiplier, 2),
            "whale": is_whale_flag,
            "handlePct": round(handle, 2),
            "betsPct": round(bets, 2),
            "divergence": divergence,
            "signedDivergence": signed_divergence,
            "reason": market.get("reason", ""),
            "date": date,
            "time": time,
            "iso": iso,
            "history": build_pick_history(market.get("league", "Otras Ligas"), game, pick, market_name),
            "status": classify_status(market, iso),
            "result": market.get("result", "PENDING"),
            "roi": market.get("roi"),
        }

        # freePick ahora sale de la evaluación real (coherente con lo que el
        # usuario ve en el badge), no de comparar contra un texto de acción
        # que "action_text" nunca produce literalmente. Piso de EV explícito:
        # el peso que "final_score" le da al dinero institucional puede tapar
        # un EV negativo (fue el hueco original detectado en TB Rays), así
        # que un EV claramente negativo veta freePick sin importar qué tan
        # alto salga el score combinado.
        item["freePick"] = (
            evaluation in ("PREMIUM", "STRONG", "LEAN")
            and risk != "HIGH"
            and ev > -0.5
        )
        all_items.append(item)

    all_items.reverse()
    return all_items


# ============================================================
# GUARDAR HISTORIAL DIARIO
# ============================================================
def save_daily_history(
    all_events,
    cdmx_now
):
    date_str = (
        cdmx_now.strftime(
            "%Y-%m-%d"
        )
    )

    day_folder = os.path.join(
        HISTORY_DIR,
        date_str
    )

    os.makedirs(
        day_folder,
        exist_ok=True
    )

    history_file = os.path.join(
        day_folder,
        "sharpie.json"
    )

    payload = {
        "generated_at":
            cdmx_now.strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
        "count":
            len(
                all_events
            ),
        "picks":
            all_events
    }

    with open(
        history_file,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            payload,
            f,
            ensure_ascii=False,
            indent=2
        )

    print(
        "[OK] Historial del día "
        f"guardado en: {history_file}"
    )


# ============================================================
# GENERATE DASHBOARD
# ============================================================
def generate_dashboard():
    utc_now = datetime.utcnow()

    cdmx_now = (
        utc_now
        - timedelta(
            hours=6
        )
    )

    now_str = (
        cdmx_now.strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )

    template_path = os.path.join(
        CURRENT_DIR,
        "template.html"
    )

    source_json_path = (
        get_latest_file()
    )

    if not os.path.exists(
        template_path
    ):
        raise FileNotFoundError(
            "No existe template.html: "
            f"{template_path}"
        )

    if (
        not source_json_path
        or not os.path.exists(
            source_json_path
        )
    ):
        raise FileNotFoundError(
            "No se encontró sharpie.json "
            f"en {INPUT_DIR}"
        )

    with open(
        template_path,
        "r",
        encoding="utf-8"
    ) as file:
        html_template = file.read()

    try:
        with open(
            source_json_path,
            "r",
            encoding="utf-8"
        ) as file:
            raw_data = json.load(
                file
            )

    except json.JSONDecodeError as e:
        print(
            "[ERROR CRÍTICO] "
            f"El archivo {source_json_path} "
            f"está corrupto o truncado: {e}"
        )

        raise SystemExit(
            "Proceso detenido para evitar "
            "generar un index.html corrupto."
        )

    all_events = build_picks(
        raw_data
    )

    save_daily_history(
        all_events,
        cdmx_now
    )

    json_data = json.dumps(
        all_events,
        ensure_ascii=False
    )

    html_content = (
        html_template.replace(
            "__GENERATED_AT__",
            now_str
        )
    )

    html_content = (
        html_content.replace(
            "__PICKS_JSON__",
            json_data
        )
    )

    output_file = os.path.join(
        OUTPUT_DIR,
        "index.html"
    )

    os.makedirs(
        os.path.dirname(
            output_file
        ),
        exist_ok=True
    )

    with open(
        output_file,
        "w",
        encoding="utf-8"
    ) as file:
        file.write(
            html_content
        )

    print(
        "[OK] Dashboard generado "
        f"con éxito: {output_file}"
    )

    return output_file


# ============================================================
# EJECUCIÓN
# ============================================================
if __name__ == "__main__":
    generate_dashboard()