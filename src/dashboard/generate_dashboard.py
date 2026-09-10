import json
import math
import os
import unicodedata
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dashboard.template_loader import read_utf8, render_template
from storage import atomic_write_json, atomic_write_text
from opportunities import save_opportunities
from tracking import update_tracking
from telegram_alerts import subscription_url
from dashboard.generate_opportunities_viewer import generate_opportunities_viewer
from config.league_config import enabled_leagues
from pipeline.analyze import american_to_decimal, calculate_personal_stake


# ============================================================
# RUTAS
# ============================================================
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
TEMPLATES_DIR = Path(CURRENT_DIR) / "templates"
ASSETS_DIR = Path(CURRENT_DIR) / "assets"
CDMX_TZ = ZoneInfo("America/Mexico_City")
NEW_YORK_TZ = ZoneInfo("America/New_York")

INPUT_DIR = os.path.join(BASE_DIR, "data", "analyzed")
OUTPUT_DIR = BASE_DIR


# Mínimo de puntos de historial REALES (bets% y handle% ambos > 0) que debe
# tener un pick antes de mostrarse en el dashboard. Por debajo de este umbral
# se considera que el dato es demasiado nuevo/incompleto para confiar en él.
MIN_HISTORY_POINTS = 2

# Tolerancia tras el inicio del evento antes de ocultarlo del dashboard --
# pasado este tiempo ya no es una apuesta pregame válida.
GAME_START_HIDE_TOLERANCE_MINUTES = 0  # sin tolerancia -- se oculta apenas inicia el evento


# ============================================================
# LOCALIZAR ARCHIVO FUENTE
# ============================================================


# ============================================================
# FECHAS Y HORAS
# ============================================================
def parse_match_datetime(raw):
    now = datetime.now(CDMX_TZ)

    if not raw:
        return (
            now.strftime("%Y-%m-%d"),
            "--:--",
            now.strftime("%Y-%m-%dT00:00:00")
        )

    raw = str(raw).strip()

    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone(CDMX_TZ)
        return (
            dt.strftime("%Y-%m-%d"),
            dt.strftime("%H:%M"),
            dt.strftime("%Y-%m-%dT%H:%M:%S"),
        )
    except (TypeError, ValueError):
        pass

    try:
        dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
        return (
            dt.strftime("%Y-%m-%d"),
            dt.strftime("%H:%M"),
            dt.strftime("%Y-%m-%dT%H:%M:%S"),
        )
    except ValueError:
        pass

    try:
        if "," in raw:
            date_part, time_part = [
                x.strip()
                for x in raw.split(",", 1)
            ]

            year = now.year
            full = f"{date_part}/{year} {time_part}"

            source_dt = datetime.strptime(
                full,
                "%m/%d/%Y %I:%M%p"
            ).replace(tzinfo=NEW_YORK_TZ)
            dt = source_dt.astimezone(CDMX_TZ)

            return (
                dt.strftime("%Y-%m-%d"),
                dt.strftime("%H:%M"),
                dt.strftime("%Y-%m-%dT%H:%M:%S")
            )

    except (TypeError, ValueError):
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


def classify_status(market, iso_str):
    explicit = market.get("status")

    if explicit:
        return explicit

    if not iso_str:
        return "UPCOMING"

    event_dt = _parse_iso(iso_str)
    if event_dt is None:
        return "UPCOMING"

    if event_dt > datetime.now(CDMX_TZ).replace(tzinfo=None):
        return "UPCOMING"

    return "LIVE"


# ============================================================
# CONVERSORES Y VALIDACIONES
# ============================================================


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


# ============================================================
# PARTE 3: SEÑALES DE MERCADO -- 5 categorías exclusivas, homologadas a
# inglés. Única fuente de verdad (antes se recalculaba distinto en backend
# y frontend -- ahora vive solo aquí).
# ============================================================
MARKET_SIGNAL_LABELS = {
    "STEAM_MOVE": "💨 STEAM MOVE",
    "REVERSE_LINE_MOVEMENT": "↩️ REVERSE LINE MOVEMENT",
    "SMART_MONEY": "🐋 SMART MONEY",
    "PUBLIC_HEAVY": "🚨 PUBLIC HEAVY",
    "CONSENSUS": "📊 CONSENSUS",
    "SHARP_VS_PUBLIC": "⚔️ SHARP VS PUBLIC",
    "BALANCED_ACTION": "⚖️ BALANCED ACTION",
    "LOW_LIQUIDITY": "💧 LOW LIQUIDITY",
    "NO_ACTION": "⚪ NO ACTION"
}


# ============================================================
# OBSERVACIONES DEL MERCADO ACTUAL
# ============================================================


def _normalize_key_part(text):
    """
    Normalización defensiva para que un mismo pick (ej. "Cowboys -3.5") siempre
    produzca la misma clave, sin importar espacios extra, mayúsculas o
    variantes de unicode que DraftKings pueda introducir al reaparecer un
    mercado en el HTML. NO toca el valor de la línea (-3.5 vs -4.5 siguen
    siendo picks distintos a propósito -- eso es continuidad real, no un bug).
    """
    if text is None:
        return ""
    text = str(text)
    text = unicodedata.normalize("NFKC", text)   # unifica variantes de unicode
    text = text.replace("\u2212", "-")            # signo menos unicode -> guion ascii
    text = " ".join(text.split())                 # colapsa espacios/tabs/saltos repetidos
    return text.strip().casefold()


def _market_unique_key(game, pick, market_name, event_date=None):
    parts = [
        _normalize_key_part(game),
        _normalize_key_part(pick),
        _normalize_key_part(market_name)
    ]
    if event_date:
        parts.append(_normalize_key_part(event_date))
    return "||".join(parts)


def _has_valid_volume(bets_pct, handle_pct):
    """
    Bets% y Handle% nunca deberían ser 0% en un mercado real -- si aparece 0%
    es una lectura incompleta/rota, no un dato válido. Se descarta el punto
    entero (no solo se ignora el campo) para no contaminar el historial ni el
    conteo de "historial suficiente".
    """
    return (
        bets_pct is not None and handle_pct is not None
        and bets_pct > 0 and handle_pct > 0
    )


def _count_changed_points(history_full):
    """
    Replica exactamente la deduplicación que hace el frontend
    (getChangedHistoryEntries en assets/js/dashboard.js): cuenta solo los puntos donde
    Bets, Handle o Cuota realmente CAMBIARON respecto al punto anterior. Un
    pick quieto acumula lecturas idénticas que no aportan cambios;
    contar esas lecturas como "puntos de seguimiento"
    infla el número y ya no coincide con lo que se ve en la tabla expandida.
    """
    valid = [h for h in history_full if h.get("betsPct") is not None or h.get("handlePct") is not None or h.get("odds") not in (None, "—")]
    if not valid:
        return 0

    has_odds = any(h.get("odds") not in (None, "—") for h in valid)

    count = 0
    for i, h in enumerate(valid):
        if i == 0:
            count += 1
            continue
        prev = valid[i - 1]
        changed = (
            h.get("betsPct") != prev.get("betsPct")
            or h.get("handlePct") != prev.get("handlePct")
            or (has_odds and h.get("odds") != prev.get("odds"))
        )
        if changed:
            count += 1
    return count


def build_real_reason(pattern_tag, coherence, history_count):
    """
    Explica la señal usando las observaciones recientes del mercado actual.
    """
    parts = [pattern_tag.split(" ", 1)[-1] if " " in pattern_tag else pattern_tag]

    if coherence == "confirmada":
        parts.append("cuota y dinero se mueven en la misma dirección, coherencia confirmada")
    elif coherence == "contradictoria":
        parts.append("la cuota se movió en contra de la dirección del dinero, coherencia contradictoria")
    elif history_count >= 2:
        parts.append(f"{history_count} puntos de seguimiento, sin señal de coherencia clara todavía")
    else:
        parts.append("historial insuficiente para evaluar coherencia")

    return ". ".join(dict.fromkeys(parts)) + "."


def calculate_coherence(history):
    """
    Coherencia cuota <-> dinero: compara la APERTURA (primer punto real) contra
    el punto MÁS RECIENTE, no solo los últimos dos. Comparar solo 2 puntos
    consecutivos es frágil -- si el último paso individual quedó plano (misma
    cuota que el punto anterior), se perdía la tendencia real que sí se ve
    comparando contra la apertura (ej. handle sube 46%->50% mientras la cuota
    se alarga +153->+168 en el camino: eso SÍ es contradictorio aunque el
    último paso no haya movido nada).
    """
    if not isinstance(history, list) or len(history) < 2:
        return None

    valid_points = [
        h for h in history
        if h.get("odds") not in (None, "—") and h.get("handlePct") is not None
    ]

    if len(valid_points) < 2:
        return None

    opening, current = valid_points[0], valid_points[-1]
    opening_odds = american_to_decimal(opening.get("odds"))
    current_odds = american_to_decimal(current.get("odds"))
    opening_handle = opening.get("handlePct")
    current_handle = current.get("handlePct")

    if opening_odds is None or current_odds is None:
        return None

    odds_shortened = (opening_odds - current_odds) > 0.0005
    handle_grew = current_handle > opening_handle

    if handle_grew and odds_shortened:
        return "confirmada"
    if handle_grew and not odds_shortened:
        return "contradictoria"
    return None


def _parse_iso(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(CDMX_TZ).replace(tzinfo=None)
        return parsed
    except (ValueError, TypeError):
        return None


# ============================================================
# OBSERVACIONES RECIENTES
# ============================================================
def build_market_observations(points, kickoff_iso):
    """Observaciones recientes del estado actual; excluye lecturas en vivo."""
    kickoff = _parse_iso(kickoff_iso)
    observations = {}
    for point in points or []:
        if not isinstance(point, dict):
            continue
        bets = safe_pct(point.get("betsPct", point.get("bets")))
        handle = safe_pct(point.get("handlePct", point.get("handle")))
        timestamp = point.get("timestamp") or point.get("time")
        observed = _parse_iso(timestamp)
        if not _has_valid_volume(bets, handle) or observed is None:
            continue
        if kickoff is not None and observed >= kickoff:
            continue
        observations[observed] = {
            "time": observed.strftime("%H:%M"),
            "timestamp": observed.replace(tzinfo=CDMX_TZ).isoformat(timespec="seconds"),
            "betsPct": bets,
            "handlePct": handle,
            "odds": point.get("odds"),
        }
    return [observations[key] for key in sorted(observations)][-200:]


def build_picks(raw_data):

    event_fields = {
        "game", "away", "home", "league", "sourceLeague", "sport",
        "time",
        "time_raw", "startIso", "date",
    }

    def extract_markets(node, inherited=None):
        found = []
        inherited = inherited or {}
        if isinstance(node, list):
            for item in node:
                found.extend(extract_markets(item, inherited))
        elif isinstance(node, dict):
            context = dict(inherited)
            context.update({key: node[key] for key in event_fields if node.get(key) not in (None, "")})
            if "markets" in node and isinstance(node["markets"], list):
                for market in node["markets"]:
                    if isinstance(market, dict):
                        found.append({**context, **market})
                    else:
                        found.extend(extract_markets(market, context))
            elif "game" in node or "pick" in node:
                found.append({**context, **node})
            for key, value in node.items():
                if key == "markets":
                    continue
                if isinstance(value, (dict, list)):
                    found.extend(extract_markets(value, context))
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
        # Un mercado ya analizado trae `iso`; debe prevalecer sobre una hora
        # suelta para no reasignar el evento accidentalmente al día actual.
        event_time = market.get("iso") or market.get("startIso") or market.get("time") or market.get("time_raw") or market.get("date") or ""
        date, time, iso = parse_match_datetime(event_time)
        unique_key = _market_unique_key(game, pick, market_name, event_date=date)

        if unique_key in seen_picks:
            continue

        seen_picks.add(unique_key)
        counter += 1

        # Al iniciar el evento deja de ser una apuesta pregame válida.
        kickoff_dt = _parse_iso(iso)
        if kickoff_dt is not None:
            now_cdmx = datetime.now(CDMX_TZ).replace(tzinfo=None)
            minutes_since_kickoff = (now_cdmx - kickoff_dt).total_seconds() / 60.0
            if minutes_since_kickoff > GAME_START_HIDE_TOLERANCE_MINUTES:
                continue

        # ----------------------------------------------------
        # 1. MÉTRICAS DE VOLUMEN (HANDLE / BETS / MONEY EDGE)
        # ----------------------------------------------------
        raw_bets = market.get("betsPct", market.get("bets_pct", market.get("bets", 50.0)))
        raw_handle = market.get("handlePct", market.get("handle_pct", market.get("handle", 50.0)))

        bets = safe_pct(raw_bets) if safe_pct(raw_bets) is not None else 50.0
        handle = safe_pct(raw_handle) if safe_pct(raw_handle) is not None else 50.0

        # Bets/Handle en 0% = lectura en vivo incompleta/rota (nunca es un
        # valor real) -- se oculta el pick de este ciclo en vez de mostrarlo
        # con un dato que sabemos que está mal.
        if not _has_valid_volume(bets, handle):
            continue
        
        # (Edge Dinero eliminado -- era el mismo cálculo que Divergencia, handle-bets, con otro nombre)

        # ----------------------------------------------------
        # 2. CUOTA Y PROBABILIDAD IMPLÍCITA
        # ----------------------------------------------------
        raw_odds = market.get("odds", "—")
        odds_str = str(raw_odds).strip() if raw_odds is not None else "—"
        implied_prob = market.get("impliedProb")

        # ----------------------------------------------------
        # 3. PROBABILIDAD DEL MODELO Y MODEL EDGE
        # ----------------------------------------------------
        model_prob = market.get("modelProb")
        model_edge = market.get("modelEdge")

        # ----------------------------------------------------
        # 4. EV Y ESTIMACIÓN
        # ----------------------------------------------------
        ev = market.get("ev")

        action_text = market.get("action", "🔴 PASAR")

        signed_divergence = market.get("signedDivergence")
        divergence = market.get("divergence")

        # Señal de mercado (Parte 3) y categoría de pick (Parte 2): única
        # fuente de verdad en inglés, ya no se recalculan heurísticamente en
        # el frontend ni con el texto viejo en español.
        market_signal = market.get("marketSignal")
        pick_category = market.get("pickCategory")
        stake = market.get("stake")

        required_metrics = (
            implied_prob, model_prob, model_edge, ev, signed_divergence,
            divergence, market_signal, stake,
        )
        if any(value is None for value in required_metrics):
            continue

        model_prob = round(float(model_prob), 2)
        model_edge = round(float(model_edge), 2)
        ev = round(float(ev), 2)
        signed_divergence = round(float(signed_divergence), 2)
        divergence = round(float(divergence), 2)
        stake = float(stake)
        if market_signal not in MARKET_SIGNAL_LABELS:
            continue

        pick_history_full = build_market_observations(market.get("history"), iso)

        # Historial insuficiente: se oculta del dashboard hasta acumular al
        # menos 2 puntos reales de seguimiento (evita mostrar picks recién
        # aparecidos sin suficiente evidencia de movimiento).
        if len(pick_history_full) < MIN_HISTORY_POINTS:
            continue

        coherence = calculate_coherence(pick_history_full)
        real_reason = build_real_reason(MARKET_SIGNAL_LABELS[market_signal], coherence, _count_changed_points(pick_history_full))
        pick_history = pick_history_full

        item = {
            "id": counter,
            "game": game or "Evento desconocido",
            "away": market.get("away", ""),
            "home": market.get("home", ""),
            "league": market.get("league", "Otras Ligas"),
            "sourceLeague": market.get("sourceLeague"),
            "sport": market.get("sport", ""),
            "market": market_name or "Línea estándar",
            "pick": pick or "Sin selección",
            "odds": odds_str,
            "actionKey": market.get("actionKey", classify_action(action_text)),
            "trendKey": market_signal,
            "marketSignal": market_signal,
            "marketSignals": market.get("marketSignals", [market_signal]),
            "pickCategory": pick_category,
            "stake": stake,
            "modelProb": model_prob,
            "modelEdge": model_edge,
            "modelHistoryPoints": int(market.get("modelHistoryPoints") or 0),
            
            "ev": ev,
            "whale": "SMART_MONEY" in set(market.get("marketSignals") or [market_signal]),
            "handlePct": round(handle, 2),
            "betsPct": round(bets, 2),
            "divergence": divergence,
            "signedDivergence": signed_divergence,
            "reason": real_reason,
            "date": date,
            "time": time,
            "iso": iso,
            "history": pick_history,
            "status": classify_status(market, iso),
        }

        all_items.append(item)

    all_items.reverse()
    return all_items


# ============================================================
# SELECCIÓN EDITORIAL PARA REDES
# ============================================================
FREE_RELEASE_SIGNALS = {
    "SMART_MONEY", "REVERSE_LINE_MOVEMENT", "STEAM_MOVE",
    "SHARP_VS_PUBLIC", "CONSENSUS",
}


def assign_free_releases(items):
    """Compatibilidad visual: FREE es ya una categoría, no otra selección."""
    for item in items:
        item["freeRelease"] = item.get("pickCategory") == "FREE"

    return items


def _raw_kelly_fraction(item):
    """Kelly completo previo al fraccionamiento, redondeo y topes de stake."""
    try:
        american = float(str(item.get("odds")).replace("+", "").replace("−", "-"))
        decimal = 1 + (american / 100 if american > 0 else 100 / abs(american))
        probability = float(item.get("modelProb")) / 100
        return max(0.0, (probability * decimal - 1) / (decimal - 1))
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def assign_medals(items):
    """Asigna 🥇🥈🥉 sin crear una puntuación sintética ni duplicar métricas."""
    category_rank = {"FREE": 1, "PREMIUM": 2, "WHALE": 3}

    def signal_rank(item):
        signals = set(item.get("marketSignals") or [item.get("marketSignal")])
        if "SMART_MONEY" in signals and float(item.get("signedDivergence") or 0) > 0:
            return 2
        return 1 if "CONSENSUS" in signals else 0

    def kickoff_priority(item):
        parsed = _parse_iso(item.get("iso"))
        return -parsed.timestamp() if parsed is not None else float("-inf")

    eligible = [item for item in items if item.get("actionKey") == "bet" and item.get("pickCategory") in category_rank]
    ordered = sorted(eligible, key=lambda item: (
        category_rank[item["pickCategory"]],
        _raw_kelly_fraction(item),
        float(item.get("modelEdge") or 0),
        float(item.get("ev") or 0),
        int(item.get("modelHistoryPoints") or 0),
        signal_rank(item),
        kickoff_priority(item),
    ), reverse=True)
    for item in items:
        item.pop("medalRank", None)
    for rank, item in enumerate(ordered[:3], 1):
        item["medalRank"] = rank
    return items


def assign_personal_stakes(items):
    """Calcula el perfil privado y limita su cartera sin alterar los picks públicos."""
    category_rank = {"FREE": 1, "PREMIUM": 2, "WHALE": 3}
    for item in items:
        decimal = american_to_decimal(item.get("odds"))
        item["personalStake"] = calculate_personal_stake(
            item.get("modelProb"), decimal, item.get("ev"), item.get("odds"),
            actionable=item.get("actionKey") == "bet", category=item.get("pickCategory"),
        )

    candidates = sorted(
        (item for item in items if item.get("personalStake", 0) > 0),
        key=lambda item: (
            -category_rank.get(item.get("pickCategory"), 0),
            -float(item.get("ev") or 0),
            -float(item.get("modelEdge") or 0),
            item.get("iso") or "",
        ),
    )
    event_used, day_used, day_count = {}, {}, {}
    for item in candidates:
        event_key = (item.get("date"), item.get("game"))
        day_key = item.get("date")
        try:
            weekend = datetime.fromisoformat(str(day_key)).weekday() >= 5
        except (TypeError, ValueError):
            weekend = False
        pick_limit = 6 if weekend else 4
        day_cap = 30.0 if weekend else 20.0
        if day_count.get(day_key, 0) >= pick_limit:
            item["personalStake"] = 0.0
            continue
        available = min(8.0 - event_used.get(event_key, 0.0), day_cap - day_used.get(day_key, 0.0))
        adjusted = min(float(item["personalStake"]), max(0.0, available))
        adjusted = math.floor(adjusted * 2.0) / 2.0
        if adjusted < 3.0:
            item["personalStake"] = 0.0
            continue
        item["personalStake"] = adjusted
        event_used[event_key] = event_used.get(event_key, 0.0) + adjusted
        day_used[day_key] = day_used.get(day_key, 0.0) + adjusted
        day_count[day_key] = day_count.get(day_key, 0) + 1
    return items


def without_private_fields(value):
    """Evita publicar el stake personal en HTML, JSON u Opportunities."""
    if isinstance(value, dict):
        return {key: without_private_fields(item) for key, item in value.items() if key != "personalStake"}
    if isinstance(value, list):
        return [without_private_fields(item) for item in value]
    return value


# ============================================================
# GENERACIÓN DEL DASHBOARD ACTUAL
# ============================================================
def generate_dashboard(source_json_path=None, output_dir=None):
    cdmx_now = datetime.now(CDMX_TZ)
    now_str = cdmx_now.strftime("%Y-%m-%d %H:%M:%S")

    template_path = os.path.join(CURRENT_DIR, "template.html")
    source_json_path = source_json_path or os.path.join(INPUT_DIR, "sharpie.json")
    output_dir = output_dir or OUTPUT_DIR

    if not os.path.exists(template_path):
        raise FileNotFoundError(f"No existe template.html: {template_path}")

    if not source_json_path or not os.path.exists(source_json_path):
        raise FileNotFoundError(f"No se encontró sharpie.json en {INPUT_DIR}")

    try:
        with open(source_json_path, "r", encoding="utf-8") as file:
            raw_data = json.load(file)

    except json.JSONDecodeError as e:
        print(f"[ERROR CRÍTICO] El archivo {source_json_path} está corrupto o truncado: {e}")
        raise SystemExit("Proceso detenido para evitar generar un index.html corrupto.")

    all_events = assign_personal_stakes(assign_medals(assign_free_releases(build_picks(raw_data))))
    runtime = Path(output_dir) / '.runtime'
    update_tracking(all_events, runtime / 'tracking.json', now=cdmx_now)
    public_events = without_private_fields(all_events)
    telegram_url = None
    try:
        telegram_url = subscription_url(runtime)
    except ValueError:
        print('[AVISO] Telegram requiere revisar su configuración privada.')

    # Una descarga válida sin picks pregame muestra el estado vacío actual.
    json_data = json.dumps(public_events, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    league_data = json.dumps(
        [league["league"] for league in enabled_leagues()],
        ensure_ascii=False,
        separators=(",", ":"),
    ).replace("</", "<\\/")
    html_content = render_template(
        template_path,
        {
            "DASHBOARD_CSS": read_utf8(ASSETS_DIR / "css" / "dashboard.css"),
            "IDENTITY_CSS": read_utf8(ASSETS_DIR / "css" / "identity.css"),
            "DASHBOARD_SKIN": read_utf8(ASSETS_DIR / "css" / "dashboard-skin.css"),
            "THEME_INIT_JS": read_utf8(ASSETS_DIR / "js" / "theme-init.js"),
            "DASHBOARD_BODY": read_utf8(TEMPLATES_DIR / "dashboard_body.html"),
            "DASHBOARD_JS": read_utf8(ASSETS_DIR / "js" / "dashboard.js"),
            "GENERATED_AT": now_str,
            "PICKS_JSON": json_data,
            "LEAGUES_JSON": league_data,
            "TELEGRAM_URL": json.dumps(telegram_url),
        },
    )

    output_file = os.path.join(output_dir, "index.html")
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    save_opportunities(public_events, Path(output_dir) / "data" / "opportunities.json", now=cdmx_now)
    generate_opportunities_viewer(output_dir=output_dir)
    atomic_write_text(output_file, html_content)

    # picks.json separado -- permite que el frontend haga polling liviano
    # (sin volver a descargar todo el HTML) para detectar picks nuevos y
    # refrescarse solo, sin que el usuario tenga que presionar F5.
    picks_json_path = os.path.join(output_dir, "picks.json")
    atomic_write_json(picks_json_path, public_events, compact=True)

    print(f"[OK] Dashboard generado con éxito: {output_file}")
    return output_file


# ============================================================
# EJECUCIÓN
# ============================================================
if __name__ == "__main__":
    generate_dashboard()
