import json
import os
import unicodedata
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from .template_loader import atomic_write_json, atomic_write_text, read_utf8, render_template
except ImportError:
    from template_loader import atomic_write_json, atomic_write_text, read_utf8, render_template


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
SNAPSHOTS_DIR = os.path.join(BASE_DIR, "data", "snapshots")
HISTORY_DIR = os.path.join(BASE_DIR, "data", "history")
OUTPUT_DIR = BASE_DIR

MAX_HISTORY_POINTS = None  # sin tope -- el frontend colapsa a los últimos 5 y expande a pedido

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

    event_dt = _parse_iso(iso_str)
    if event_dt is None:
        return "UPCOMING"

    if event_dt > datetime.now(CDMX_TZ).replace(tzinfo=None):
        return "UPCOMING"

    return "LIVE"


# ============================================================
# CONVERSORES Y VALIDACIONES
# ============================================================
def safe_float(val, default=0.0):
    if val is None:
        return default

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
        return default


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
# EVOLUCIÓN HISTÓRICA & SNAPSHOTS
# ============================================================
_snapshot_cache = {}


def _league_slug(league_name):
    return (league_name or "").strip().lower().replace(" ", "_")


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


def _load_league_snapshots(league_slug):
    if league_slug in _snapshot_cache:
        return _snapshot_cache[league_slug]

    league_folder = os.path.join(SNAPSHOTS_DIR, league_slug)
    indexed = []

    if os.path.isdir(league_folder):
        files = sorted(f for f in os.listdir(league_folder) if f.endswith(".json"))

        for filename in files:
            path = os.path.join(league_folder, filename)

            try:
                with open(path, "r", encoding="utf-8") as file:
                    snap_data = json.load(file)
            except (json.JSONDecodeError, OSError):
                continue

            timestamp_raw = filename.replace(".json", "")

            try:
                dt = datetime.strptime(timestamp_raw, "%Y%m%d_%H%M%S")
                time_label = dt.strftime("%H:%M")
                timestamp_iso = dt.strftime("%Y-%m-%dT%H:%M:%S")  # fecha+hora completa -- necesaria para checkpoints CLV (-4h/-2h/-1h)
            except ValueError:
                time_label = timestamp_raw
                timestamp_iso = None

            market_index = {}

            for game_entry in snap_data.get("games", []):
                game_name = game_entry.get("game")
                raw_time_for_date = game_entry.get("time_raw", game_entry.get("time", ""))
                if raw_time_for_date:
                    game_date, _t, _iso = parse_match_datetime(raw_time_for_date)
                else:
                    game_date = None  # sin texto de hora real -- no confiar en el fallback a "hoy"

                for market in game_entry.get("markets", []):
                    pick = market.get("pick")
                    market_name = market.get("market", market.get("type"))

                    if not game_name or not pick:
                        continue

                    key = _market_unique_key(game_name, pick, market_name, event_date=game_date)

                    raw_bets = market.get("bets_pct", market.get("betsPct", market.get("bets")))
                    raw_handle = market.get("handle_pct", market.get("handlePct", market.get("handle")))
                    raw_odds = market.get("odds", market.get("cuota"))

                    market_index[key] = {
                        "time": time_label,
                        "timestamp": timestamp_iso,
                        "betsPct": safe_pct(raw_bets),
                        "handlePct": safe_pct(raw_handle),
                        "odds": raw_odds if raw_odds not in (None, "—") else None
                    }

            indexed.append(market_index)

    _snapshot_cache[league_slug] = indexed
    return indexed


def _count_changed_points(history_full):
    """
    Replica exactamente la deduplicación que hace el frontend
    (getChangedHistoryEntries en assets/js/dashboard.js): cuenta solo los puntos donde
    Bets, Handle o Cuota realmente CAMBIARON respecto al punto anterior. Un
    pick quieto varios días acumula muchos snapshots idénticos (pipeline cada
    30 min) que no aportan nada -- contar esos como "puntos de seguimiento"
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
    Texto de análisis regenerado con el historial REAL (persistente, cruzando
    corridas), no con el texto que trae analyze.py -- ese se arma con una
    sola lectura del scraper (siempre <=1 punto local), así que decía cosas
    como "un solo punto de historial" incluso cuando la tabla del dashboard
    ya mostraba 4+ puntos reales.
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


def build_pick_history_full(league_name, game, pick, market_name, kickoff_iso=None):
    """
    Historial COMPLETO sin truncar -- fuente de verdad para CLV y para el
    conteo de "historial suficiente". Nunca se le aplica MAX_HISTORY_POINTS
    aquí, porque cortar antes de calcular CLV perdería la apertura real del
    pick (bug ya detectado: MAX_HISTORY_POINTS=8 ~= solo 4h a cadencia de 30min).

    Los puntos con timestamp >= kickoff NO se cuentan: una vez que el evento
    arrancó, esos snapshots son movimiento en vivo, no seguimiento pregame --
    no deben alimentar coherencia, CLV, ni el conteo de "historial suficiente".
    """
    league_slug = _league_slug(league_name)
    event_date = kickoff_iso.split("T")[0] if kickoff_iso else None
    key = _market_unique_key(game, pick, market_name, event_date=event_date)
    snapshots = _load_league_snapshots(league_slug)
    kickoff_dt = _parse_iso(kickoff_iso)

    history = []

    for market_index in snapshots:
        point = market_index.get(key)

        if point is None:
            continue

        # Punto inválido: bets/handle en 0% (o ausentes) -- nunca es un dato
        # real, se descarta por completo en vez de mostrarlo como si lo fuera.
        if not _has_valid_volume(point["betsPct"], point["handlePct"]):
            continue

        # Punto posterior al inicio del evento -- ya no es historial pregame.
        if kickoff_dt is not None:
            point_dt = _parse_iso(point.get("timestamp"))
            if point_dt is not None and point_dt >= kickoff_dt:
                continue

        history.append({
            "time": point["time"],
            "timestamp": point["timestamp"],
            "betsPct": point["betsPct"],
            "handlePct": point["handlePct"],
            "odds": point["odds"]
        })

    return history


def build_pick_history_display(full_history):
    """Recorte SOLO para lo que se manda al frontend (gráfica de evolución)."""
    if MAX_HISTORY_POINTS and len(full_history) > MAX_HISTORY_POINTS:
        return full_history[-MAX_HISTORY_POINTS:]
    return full_history


# Tolerancia para emparejar un checkpoint (-4h/-2h/-1h) con el snapshot real
# más cercano. La cadencia del pipeline es cada 30 min, así que el match
# nunca es exacto -- 20 min de margen cubre eso sin cruzar hacia el checkpoint
# vecino.
CLV_CHECKPOINTS_HOURS = (4, 2, 1)
CLV_MATCH_TOLERANCE_MINUTES = 20


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


def calculate_clv(full_history, kickoff_iso):
    """
    CLV (Closing Line Value) medido en 3 momentos fijos antes del encuentro:
    -4h, -2h y -1h. Se compara la probabilidad implícita de la cuota en cada
    checkpoint contra la probabilidad implícita de la cuota de APERTURA
    (primer punto real del historial). CLV positivo = el mercado se movió a
    favor del pick desde que apareció (buena señal); negativo = se movió en
    contra.
    """
    kickoff_dt = _parse_iso(kickoff_iso)
    if kickoff_dt is None or not full_history:
        return None

    # Apertura: primer punto del historial que tenga cuota real.
    opening_point = next((p for p in full_history if p.get("odds") not in (None, "—")), None)
    if opening_point is None:
        return None

    opening_odds = opening_point["odds"]
    opening_prob = american_implied_probability(opening_odds)
    if opening_prob is None:
        return None

    def _divergence(point):
        bets = point.get("betsPct")
        handle = point.get("handlePct")
        if bets is None or handle is None:
            return None
        return round(handle - bets, 2)

    result = {
        "opening": {
            "odds": opening_odds,
            "prob": round(opening_prob, 2),
            "divergence": _divergence(opening_point),
            "timestamp": opening_point.get("timestamp")
        },
        "checkpoints": {}
    }

    for hours_before in CLV_CHECKPOINTS_HOURS:
        target_dt = kickoff_dt - timedelta(hours=hours_before)

        best_point = None
        best_diff = None

        for point in full_history:
            point_dt = _parse_iso(point.get("timestamp"))
            if point_dt is None or point.get("odds") in (None, "—"):
                continue

            diff_minutes = abs((point_dt - target_dt).total_seconds()) / 60.0
            if diff_minutes > CLV_MATCH_TOLERANCE_MINUTES:
                continue

            if best_diff is None or diff_minutes < best_diff:
                best_diff = diff_minutes
                best_point = point

        label = f"{hours_before}h"

        if best_point is None:
            result["checkpoints"][label] = None
            continue

        checkpoint_prob = american_implied_probability(best_point["odds"])
        if checkpoint_prob is None:
            result["checkpoints"][label] = None
            continue

        result["checkpoints"][label] = {
            "odds": best_point["odds"],
            "prob": round(checkpoint_prob, 2),
            "clv": round(checkpoint_prob - opening_prob, 2),
            "divergence": _divergence(best_point),
            "timestamp": best_point.get("timestamp"),
            "minutesFromTarget": round(best_diff, 1)
        }

    return result


# ============================================================
# LOG DE CLV -- base de datos para calibrar el modelo (de-vig + divergencia)
# ============================================================
# Un registro por pick, escrito/actualizado solo cuando el checkpoint -1h ya
# está disponible (lo más cerca de "cierre" que el pipeline puede capturar
# antes de que el mercado pregame desaparezca). No es tracking en vivo: es la
# tabla de la que después se mide, por rango de divergencia, cuál es el CLV
# promedio real -- de ahí sale el peso calibrado del ajuste del modelo.
CLV_LOG_DIR = os.path.join(BASE_DIR, "data", "results")
CLV_LOG_PATH = os.path.join(CLV_LOG_DIR, "clv_log.json")

_clv_log_cache = None


def _load_clv_log():
    global _clv_log_cache
    if _clv_log_cache is not None:
        return _clv_log_cache

    if os.path.exists(CLV_LOG_PATH):
        try:
            with open(CLV_LOG_PATH, "r", encoding="utf-8") as file:
                _clv_log_cache = json.load(file)
        except (json.JSONDecodeError, OSError):
            _clv_log_cache = {}
    else:
        _clv_log_cache = {}

    return _clv_log_cache


def _save_clv_log():
    if _clv_log_cache is None:
        return
    os.makedirs(CLV_LOG_DIR, exist_ok=True)
    with open(CLV_LOG_PATH, "w", encoding="utf-8") as file:
        json.dump(_clv_log_cache, file, ensure_ascii=False, indent=2)


def _clv_log_key(league, game, pick, market_name, date_str):
    # Incluye la fecha para que un mismo enfrentamiento (mismos equipos) en
    # otra temporada/jornada no colisione con un registro viejo.
    return "||".join([_market_unique_key(game, pick, market_name), _league_slug(league), date_str or ""])


def register_clv_entry(league, game, pick, market_name, date_str, clv, extra=None):
    if not clv:
        return
    if not clv.get("checkpoints", {}).get("1h"):
        return  # todavía no llega a -1h: nada "cercano a cierre" que loggear aún

    log = _load_clv_log()
    key = _clv_log_key(league, game, pick, market_name, date_str)

    entry = {
        "league": league,
        "game": game,
        "pick": pick,
        "market": market_name,
        "date": date_str,
        "opening": clv.get("opening"),
        "checkpoints": clv.get("checkpoints"),
        "loggedAt": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    }

    if extra:
        entry.update(extra)

    log[key] = entry  # upsert -- misma key sobreescribe, no acumula duplicados por corrida


# ============================================================
# CALIBRACIÓN AUTOMÁTICA DEL PESO DE DIVERGENCIA
# ------------------------------------------------------------
# Corre sola en cada ejecución del pipeline (no hay que llamarla a mano).
# Lee TODO clv_log.json acumulado hasta ahora, agrupa por rango de
# divergencia de apertura y mide el CLV real en -1h de cada grupo. De ahí
# sale el peso "medido" que reemplaza a PROVISIONAL_DIVERGENCE_WEIGHT en
# analyze.py cuando haya suficiente muestra.
#
# Con pocos datos el reporte va a salir casi vacío/poco confiable -- por eso
# cada bucket trae "sufficientSample" para saber cuáles ya sirven y cuáles
# todavía no.
# ============================================================
CALIBRATION_OUTPUT_PATH = os.path.join(CLV_LOG_DIR, "calibration_report.json")
MIN_SAMPLES_PER_BUCKET = 5
DIVERGENCE_BUCKETS = [
    (-100, -35), (-35, -25), (-25, -15), (-15, -5), (-5, 5),
    (5, 15), (15, 25), (25, 35), (35, 100)
]


def _bucket_label(low, high):
    if low <= -100:
        return f"< {high}%"
    if high >= 100:
        return f">= {low}%"
    return f"{low}% a {high}%"


def _regression_weight(points):
    """Pendiente por mínimos cuadrados forzando intercepto 0 (clv ~= peso * divergencia)."""
    num = sum(d * c for d, c in points)
    den = sum(d * d for d, c in points)
    if den == 0:
        return None
    return round(num / den, 4)


def _extract_calibration_points(log):
    """
    Un punto por pick: divergencia de APERTURA (lo que el modelo habría visto
    al calcular la probabilidad) vs CLV en el checkpoint -1h (el movimiento
    real de mercado más cercano a cierre que el pipeline logra capturar).
    """
    points = []
    for entry in log.values():
        opening = entry.get("opening") or {}
        checkpoint_1h = (entry.get("checkpoints") or {}).get("1h")

        divergence = opening.get("divergence")
        clv = checkpoint_1h.get("clv") if checkpoint_1h else None

        if divergence is None or clv is None:
            continue

        points.append((divergence, clv))
    return points


def build_calibration_report(log):
    points = _extract_calibration_points(log)

    report = {
        "generatedAt": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "sampleSize": len(points),
        "overallWeight": None,
        "currentProvisionalWeight": 0.15,  # debe coincidir con analyze.PROVISIONAL_DIVERGENCE_WEIGHT
        "buckets": []
    }

    if not points:
        return report

    report["overallWeight"] = _regression_weight(points)

    for low, high in DIVERGENCE_BUCKETS:
        bucket_points = [(d, c) for d, c in points if low <= d < high]
        count = len(bucket_points)

        if count == 0:
            continue

        avg_divergence = round(sum(d for d, _ in bucket_points) / count, 2)
        avg_clv = round(sum(c for _, c in bucket_points) / count, 2)
        implied_weight = round(avg_clv / avg_divergence, 4) if avg_divergence != 0 else None

        report["buckets"].append({
            "range": _bucket_label(low, high),
            "count": count,
            "avgDivergence": avg_divergence,
            "avgClv": avg_clv,
            "impliedWeight": implied_weight,
            "sufficientSample": count >= MIN_SAMPLES_PER_BUCKET
        })

    return report


def _save_calibration_report():
    if _clv_log_cache is None:
        return

    report = build_calibration_report(_clv_log_cache)

    os.makedirs(CLV_LOG_DIR, exist_ok=True)
    with open(CALIBRATION_OUTPUT_PATH, "w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)

    print(f"📊 Calibración CLV actualizada: {report['sampleSize']} picks en el log, peso medido = {report['overallWeight']}")


def build_picks(raw_data):
    _snapshot_cache.clear()
    global _clv_log_cache
    _clv_log_cache = None
    _load_clv_log()

    event_fields = {
        "game", "away", "home", "league", "sourceLeague", "sport",
        "espnSport", "espnLeague", "eventId", "espnEventId", "time",
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
        event_time = market.get("time") or market.get("startIso") or market.get("time_raw") or market.get("date") or ""
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

        implied_prob = round(float(implied_prob), 2)
        model_prob = round(float(model_prob), 2)
        model_edge = round(float(model_edge), 2)
        ev = round(float(ev), 2)
        signed_divergence = round(float(signed_divergence), 2)
        divergence = round(float(divergence), 2)
        stake = float(stake)
        if market_signal not in MARKET_SIGNAL_LABELS:
            continue

        pick_history_full = build_pick_history_full(market.get("league", "Otras Ligas"), game, pick, market_name, kickoff_iso=iso)

        # Historial insuficiente: se oculta del dashboard hasta acumular al
        # menos 2 puntos reales de seguimiento (evita mostrar picks recién
        # aparecidos sin suficiente evidencia de movimiento).
        if len(pick_history_full) < MIN_HISTORY_POINTS:
            continue

        coherence = calculate_coherence(pick_history_full)
        real_reason = build_real_reason(MARKET_SIGNAL_LABELS[market_signal], coherence, _count_changed_points(pick_history_full))
        clv = calculate_clv(pick_history_full, iso)
        pick_history = build_pick_history_display(pick_history_full)

        register_clv_entry(
            market.get("league", "Otras Ligas"), game, pick, market_name, date, clv,
            extra={
                "whale": pick_category == "WHALE",
                "modelSource": market.get("modelSource")
            }
        )

        item = {
            "id": counter,
            "game": game or "Evento desconocido",
            "away": market.get("away", ""),
            "home": market.get("home", ""),
            "league": market.get("league", "Otras Ligas"),
            "sourceLeague": market.get("sourceLeague"),
            "sport": market.get("sport", ""),
            "espnSport": market.get("espnSport"),
            "espnLeague": market.get("espnLeague"),
            "sourceEventId": market.get("espnEventId") or market.get("eventId"),
            "market": market_name or "Línea estándar",
            "pick": pick or "Sin selección",
            "odds": odds_str,
            "action": action_text,
            "actionKey": market.get("actionKey", classify_action(action_text)),
            "pattern": MARKET_SIGNAL_LABELS[market_signal],
            "trend": MARKET_SIGNAL_LABELS[market_signal],
            "trendKey": market_signal,
            "marketSignal": market_signal,
            "marketSignals": market.get("marketSignals", [market_signal]),
            "pickCategory": pick_category,
            "priority": market.get("priority", "👀 OBSERVAR"),
            "priorityKey": classify_priority(market.get("priority", "")),
            "stake": stake,
            "modelProb": round(model_prob, 2) if model_prob is not None else None,
            "fairProb": market.get("fairProb"),
            "flowAdjustment": market.get("flowAdjustment"),
            "modelSource": market.get("modelSource"),
            "lineMove": market.get("lineMove"),
            "lineMoveMinutes": market.get("lineMoveMinutes"),
            "liquidityStatus": market.get("liquidityStatus"),
            "impliedProb": round(implied_prob, 2) if implied_prob is not None else None,
            "modelEdge": round(model_edge, 2),
            
            "ev": ev,
            "coherence": coherence,
            "whale": pick_category == "WHALE",
            "handlePct": round(handle, 2),
            "betsPct": round(bets, 2),
            "divergence": divergence,
            "signedDivergence": signed_divergence,
            "reason": real_reason,
            "date": date,
            "time": time,
            "iso": iso,
            "history": pick_history,
            "clv": clv,
            "status": classify_status(market, iso),
            "result": market.get("result", "PENDING"),
            "roi": market.get("roi"),
        }

        all_items.append(item)

    all_items.reverse()
    _save_clv_log()
    _save_calibration_report()
    return all_items


# ============================================================
# SELECCIÓN EDITORIAL PARA REDES
# ============================================================
FREE_RELEASE_SIGNALS = {
    "SMART_MONEY", "REVERSE_LINE_MOVEMENT", "STEAM_MOVE",
    "SHARP_VS_PUBLIC", "CONSENSUS",
}


def _free_release_score(item):
    signals = set(item.get("marketSignals") or [item.get("marketSignal")])
    signal_weight = sum({
        "REVERSE_LINE_MOVEMENT": 60,
        "STEAM_MOVE": 50,
        "SMART_MONEY": 40,
        "SHARP_VS_PUBLIC": 25,
        "CONSENSUS": 10,
    }.get(signal, 0) for signal in signals)
    return (
        signal_weight
        + float(item.get("ev") or 0) * 10
        + float(item.get("modelEdge") or 0) * 5
        + float(item.get("stake") or 0) * 20
    )


def assign_free_releases(items):
    """Publica todos los VALUE que cumplen los parámetros de Free Release.

    No existe cupo mínimo ni máximo. PREMIUM y WHALE conservan acceso Premium
    y nunca se liberan automáticamente para completar una cuota editorial.
    """
    for item in items:
        item["freeRelease"] = False
        item["freeReleaseRank"] = None
        item["publicationTier"] = None

    eligible = []
    for item in items:
        signals = set(item.get("marketSignals") or [item.get("marketSignal")])
        if item.get("pickCategory") != "VALUE": continue
        if item.get("actionKey") != "bet": continue
        if float(item.get("ev") or 0) < 1.0: continue
        if float(item.get("modelEdge") or 0) <= 0: continue
        if float(item.get("stake") or 0) < 1.0: continue
        if not signals.intersection(FREE_RELEASE_SIGNALS): continue
        eligible.append(item)

    ordered = sorted(eligible, key=_free_release_score, reverse=True)

    for rank, item in enumerate(ordered, start=1):
        item["freeRelease"] = True
        item["freeReleaseRank"] = rank
        item["publicationTier"] = "FREE_RELEASE"

    for item in items:
        if item.get("publicationTier") is not None: continue
        if item.get("pickCategory") in {"PREMIUM", "WHALE"}:
            item["publicationTier"] = "PREMIUM_ONLY"
        elif item.get("pickCategory") == "VALUE":
            item["publicationTier"] = "VALUE_POOL"

    return items


# ============================================================
# HISTORIAL PERSISTENTE DE PICKS CON VALOR
# ============================================================
VALUE_CATEGORIES = {"VALUE", "PREMIUM", "WHALE"}
LEGACY_VALUE_CATEGORIES = VALUE_CATEGORIES | {"FREE"}
HISTORY_SCHEMA_VERSION = 2


def _is_qualified_value_pick(item, allow_legacy=False):
    categories = LEGACY_VALUE_CATEGORIES if allow_legacy else VALUE_CATEGORIES
    if not isinstance(item, dict) or item.get("pickCategory") not in categories:
        return False
    action_key = item.get("actionKey")
    if (not allow_legacy and action_key != "bet") or (allow_legacy and action_key not in {None, "", "bet"}):
        return False
    try:
        ev = float(item.get("ev") or 0)
        return (
            (ev > 0 if allow_legacy else ev >= 1.0)
            and float(item.get("modelEdge") or 0) > 0
            and float(item.get("stake") or 0) >= 1.0
        )
    except (TypeError, ValueError):
        return False


def _history_pick_id(item):
    raw_key = "||".join([
        _normalize_key_part(item.get("date")),
        _normalize_key_part(item.get("league")),
        _market_unique_key(item.get("game"), item.get("pick"), item.get("market")),
    ])
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:24]


def _qualification_snapshot(item, observed_at):
    """Versión compacta para auditar cambios sin duplicar la card completa."""
    return {
        "observedAt": observed_at,
        "pickCategory": item.get("pickCategory"),
        "publicationTier": item.get("publicationTier"),
        "freeRelease": bool(item.get("freeRelease")),
        "odds": item.get("odds"),
        "stake": item.get("stake"),
        "modelProb": item.get("modelProb"),
        "modelEdge": item.get("modelEdge"),
        "ev": item.get("ev"),
        "betsPct": item.get("betsPct"),
        "handlePct": item.get("handlePct"),
        "signedDivergence": item.get("signedDivergence"),
        "marketSignal": item.get("marketSignal"),
        "marketSignals": item.get("marketSignals", []),
        "lineMove": item.get("lineMove"),
    }


def _snapshot_signature(snapshot):
    comparable = {key: value for key, value in snapshot.items() if key != "observedAt"}
    return json.dumps(comparable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _new_history_record(item, observed_at):
    normalized = dict(item)
    if normalized.get("pickCategory") == "FREE":
        normalized["pickCategory"] = "VALUE"
        normalized["freeRelease"] = True
        normalized["publicationTier"] = "FREE_RELEASE"

    history_id = normalized.get("historyId") or _history_pick_id(normalized)
    first_seen = normalized.get("firstQualifiedAt") or observed_at
    snapshots = normalized.get("qualificationSnapshots")
    if not isinstance(snapshots, list) or not snapshots:
        snapshots = [_qualification_snapshot(normalized, first_seen)]

    normalized.update({
        "historyId": history_id,
        "historySchemaVersion": HISTORY_SCHEMA_VERSION,
        "firstQualifiedAt": first_seen,
        "lastQualifiedAt": normalized.get("lastQualifiedAt") or observed_at,
        "qualifiedObservations": int(normalized.get("qualifiedObservations") or 1),
        "qualificationSnapshots": snapshots,
        "latestViable": True,
        "needsSettlement": (normalized.get("settlement") or {}).get("status") not in {"WIN", "LOSS", "PUSH", "VOID", "HALF_WIN", "HALF_LOSS"},
        "settlement": normalized.get("settlement") or {
            "status": "PENDING",
            "source": None,
            "checkedAt": None,
            "settledAt": None,
            "homeScore": None,
            "awayScore": None,
            "notes": None,
        },
        "eventLookup": normalized.get("eventLookup") or {
            "provider": "ESPN",
            "eventId": normalized.get("sourceEventId"),
            "league": normalized.get("league"),
            "sport": normalized.get("sport"),
            "espnSport": normalized.get("espnSport"),
            "espnLeague": normalized.get("espnLeague"),
            "away": normalized.get("away"),
            "home": normalized.get("home"),
            "scheduledAt": normalized.get("iso"),
            "matchStatus": "UNMATCHED",
        },
    })
    return normalized


def _load_existing_value_records(history_file, observed_at):
    if not os.path.exists(history_file):
        return {}
    try:
        with open(history_file, "r", encoding="utf-8") as source:
            payload = json.load(source)
    except (OSError, json.JSONDecodeError):
        print(f"[AVISO] Historial ilegible, se conserva sin sobrescribir: {history_file}")
        return None

    raw_picks = payload.get("picks", []) if isinstance(payload, dict) else payload
    if not isinstance(raw_picks, list):
        return {}

    records = {}
    legacy_time = payload.get("generated_at", observed_at) if isinstance(payload, dict) else observed_at
    for item in raw_picks:
        if not isinstance(item, dict):
            continue
        legacy_item = dict(item)
        try:
            positive_value = float(legacy_item.get("ev") or 0) > 0 and float(legacy_item.get("modelEdge") or 0) > 0
            old_stake = float(legacy_item.get("stake") or 0)
        except (TypeError, ValueError):
            positive_value, old_stake = False, 0.0
        if positive_value and old_stake <= 0:
            legacy_item["stake"] = 1.0
            legacy_item["originalStake"] = item.get("stake")
            legacy_item["stakeNormalized"] = True
            legacy_item["stakeNormalizationReason"] = "LEGACY_STAKE_MODEL"
        if not _is_qualified_value_pick(legacy_item, allow_legacy=True):
            continue
        record = _new_history_record(legacy_item, legacy_time)
        records[record["historyId"]] = record
    return records


def _atomic_write_json(path, payload):
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as output:
        json.dump(payload, output, ensure_ascii=False, indent=2)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temp_path, path)


def save_value_history(all_events, cdmx_now):
    """Upsert por evento: conserva siempre la última versión que tuvo valor.

    Si un pick deja de clasificar en ejecuciones posteriores, no llega a esta
    función y su último registro viable permanece intacto para liquidación.
    """
    observed_at = cdmx_now.strftime("%Y-%m-%dT%H:%M:%S-06:00")
    qualified = [item for item in all_events if _is_qualified_value_pick(item)]
    grouped = {}
    for item in qualified:
        event_date = str(item.get("date") or cdmx_now.strftime("%Y-%m-%d"))[:10]
        grouped.setdefault(event_date, []).append(item)

    saved_count = 0
    for event_date, current_items in grouped.items():
        day_folder = os.path.join(HISTORY_DIR, event_date)
        history_file = os.path.join(day_folder, "sharpie.json")
        os.makedirs(day_folder, exist_ok=True)

        records = _load_existing_value_records(history_file, observed_at)
        if records is None:
            continue

        for item in current_items:
            history_id = _history_pick_id(item)
            previous = records.get(history_id)
            if previous is None:
                records[history_id] = _new_history_record(item, observed_at)
                saved_count += 1
                continue

            settlement = previous.get("settlement") or _new_history_record(item, observed_at)["settlement"]
            event_lookup = dict(previous.get("eventLookup") or _new_history_record(item, observed_at)["eventLookup"])
            if item.get("espnSport") and item.get("espnLeague"):
                event_lookup.update({
                    "espnSport": item.get("espnSport"),
                    "espnLeague": item.get("espnLeague"),
                    "league": item.get("league"),
                    "sport": item.get("sport"),
                })
            snapshots = previous.get("qualificationSnapshots", [])
            new_snapshot = _qualification_snapshot(item, observed_at)
            if not snapshots or _snapshot_signature(snapshots[-1]) != _snapshot_signature(new_snapshot):
                snapshots.append(new_snapshot)

            updated = dict(item)
            updated.update({
                "historyId": history_id,
                "historySchemaVersion": HISTORY_SCHEMA_VERSION,
                "firstQualifiedAt": previous.get("firstQualifiedAt", observed_at),
                "lastQualifiedAt": observed_at,
                "qualifiedObservations": int(previous.get("qualifiedObservations") or 0) + 1,
                "qualificationSnapshots": snapshots,
                "latestViable": True,
                "settlement": settlement,
                "eventLookup": event_lookup,
                "needsSettlement": (settlement or {}).get("status") not in {"WIN", "LOSS", "PUSH", "VOID", "HALF_WIN", "HALF_LOSS"},
            })
            records[history_id] = updated
            saved_count += 1

        ordered_records = sorted(
            records.values(),
            key=lambda record: (record.get("iso") or "", record.get("historyId") or ""),
        )
        payload = {
            "schemaVersion": HISTORY_SCHEMA_VERSION,
            "eventDate": event_date,
            "updatedAt": observed_at,
            "count": len(ordered_records),
            "pendingSettlement": sum(1 for record in ordered_records if record.get("needsSettlement")),
            "picks": ordered_records,
        }
        _atomic_write_json(history_file, payload)
        print(f"[OK] Historial de valor actualizado: {history_file} ({len(ordered_records)} picks)")

    if not qualified:
        print("[INFO] Sin nuevos picks con valor; el historial existente permanece intacto.")
    return saved_count


# ============================================================
# GENERATE DASHBOARD
# ============================================================
def generate_dashboard():
    cdmx_now = datetime.now(CDMX_TZ)
    now_str = cdmx_now.strftime("%Y-%m-%d %H:%M:%S")

    template_path = os.path.join(CURRENT_DIR, "template.html")
    source_json_path = get_latest_file()

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

    all_events = assign_free_releases(build_picks(raw_data))

    # ------------------------------------------------------------
    # BARRERA ANTI-SOBREESCRITURA (BLOQUEA VACÍOS)
    # ------------------------------------------------------------
    if not all_events or len(all_events) == 0:
        print("\n" + "!" * 70)
        print("[⚠️ ALERTA ANTI-SOBREESCRITURA] 0 picks válidos extraídos del JSON fuente.")
        print("[INFO] Se canceló la actualización del historial y del dashboard.")
        print("[INFO] El sitio 'index.html' y los registros previos conservarán su información.")
        print("!" * 70 + "\n")
        return None

    save_value_history(all_events, cdmx_now)

    json_data = json.dumps(all_events, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html_content = render_template(
        template_path,
        {
            "DASHBOARD_CSS": read_utf8(ASSETS_DIR / "css" / "dashboard.css"),
            "THEME_INIT_JS": read_utf8(ASSETS_DIR / "js" / "theme-init.js"),
            "DASHBOARD_BODY": read_utf8(TEMPLATES_DIR / "dashboard_body.html"),
            "DASHBOARD_JS": read_utf8(ASSETS_DIR / "js" / "dashboard.js"),
            "GENERATED_AT": now_str,
            "PICKS_JSON": json_data,
        },
    )

    output_file = os.path.join(OUTPUT_DIR, "index.html")
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    atomic_write_text(output_file, html_content)

    # picks.json separado -- permite que el frontend haga polling liviano
    # (sin volver a descargar todo el HTML) para detectar picks nuevos y
    # refrescarse solo, sin que el usuario tenga que presionar F5.
    picks_json_path = os.path.join(OUTPUT_DIR, "picks.json")
    atomic_write_json(picks_json_path, all_events, compact=True)

    print(f"[OK] Dashboard generado con éxito: {output_file}")
    return output_file


# ============================================================
# EJECUCIÓN
# ============================================================
if __name__ == "__main__":
    generate_dashboard()
