from pipeline.download import download_all
from pipeline.parse import parse_all
from pipeline.analyze import analyze_all
from pipeline.settle_history_espn import settle_history
from pipeline.history_integrity import normalize_history_storage

from dashboard.generate_dashboard import generate_dashboard
from dashboard.generate_results_viewer import generate_results_viewer
from maintenance import cleanup_downloaded_raw, run_maintenance

from datetime import datetime, timedelta
from pathlib import Path
from time import perf_counter
from zoneinfo import ZoneInfo


CDMX_TIMEZONE = ZoneInfo("America/Mexico_City")
BASE_DIR = Path(__file__).resolve().parent.parent
SETTLEMENT_STATE_DIR = BASE_DIR / "data" / "results"
BACKFILL_MARKER = SETTLEMENT_STATE_DIR / ".espn_backfill_date"
SETTLEMENT_CHECK_MARKER = SETTLEMENT_STATE_DIR / ".espn_last_check"
BACKFILL_VERSION = "canonical-history-and-espn-v8"
SETTLEMENT_INTERVAL_MINUTES = 30
RESULTS_HTML = BASE_DIR / "results.html"
HISTORY_DIR = BASE_DIR / "data" / "history"


def _atomic_marker(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def settlement_is_due(interval_minutes=SETTLEMENT_INTERVAL_MINUTES):
    try:
        previous = datetime.fromisoformat(SETTLEMENT_CHECK_MARKER.read_text(encoding="utf-8").strip())
        if previous.tzinfo is None:
            previous = previous.replace(tzinfo=CDMX_TIMEZONE)
    except (OSError, ValueError):
        return True
    return datetime.now(CDMX_TIMEZONE) - previous >= timedelta(minutes=interval_minutes)


def results_view_is_stale():
    if not RESULTS_HTML.exists():
        return True
    try:
        output_mtime = RESULTS_HTML.stat().st_mtime
        history_changed = any(path.stat().st_mtime > output_mtime for path in HISTORY_DIR.glob("????-??-??/sharpie.json"))
        viewer_sources = (
            BASE_DIR / "src" / "dashboard" / "generate_results_viewer.py",
            BASE_DIR / "src" / "dashboard" / "templates" / "results.html",
            BASE_DIR / "src" / "dashboard" / "templates" / "results_body.html",
            BASE_DIR / "src" / "dashboard" / "assets" / "css" / "results.css",
            BASE_DIR / "src" / "dashboard" / "assets" / "js" / "results.js",
        )
        viewer_changed = any(path.exists() and path.stat().st_mtime > output_mtime for path in viewer_sources)
        return history_changed or viewer_changed
    except OSError:
        return True


def settle_recent_history(days=2):
    """Liquida hoy y ayer sin bloquear el pipeline si ESPN no responde."""
    cdmx_today = datetime.now(CDMX_TIMEZONE).date()
    totals = {}

    for offset in range(days):
        date_text = (cdmx_today - timedelta(days=offset)).isoformat()
        day_label = "hoy" if offset == 0 else "ayer" if offset == 1 else date_text
        print(f"   🔎 ESPN está revisando {day_label} ({date_text})...", flush=True)
        try:
            summary = settle_history(date_filter=date_text, timeout=8.0)
        except Exception as exc:
            print(f"   ⚠️ ESPN no respondió para {date_text}: {exc}")
            continue

        for key, value in summary.items():
            totals[key] = totals.get(key, 0) + value

    if totals:
        outcomes = [
            f"{key}={totals.get(key, 0)}"
            for key in ("WIN", "HALF_WIN", "LOSS", "HALF_LOSS", "PUSH", "VOID", "PENDING", "REVIEW", "NORMALIZED", "EXCLUDED", "ERROR")
            if totals.get(key, 0)
        ]
        print("   🏁 Marcadores · " + (" · ".join(outcomes) if outcomes else "sin novedades"))

    return totals


def settle_history_pipeline(days=2):
    """Liquida el rezago diario y lo reciente cada 30 minutos."""
    if not settlement_is_due():
        print(f"   💤 ESPN descansa · nueva revisión al cumplir {SETTLEMENT_INTERVAL_MINUTES} min")
        return None

    cdmx_today = datetime.now(CDMX_TIMEZONE).date().isoformat()
    try:
        last_backfill = BACKFILL_MARKER.read_text(encoding="utf-8").strip()
    except OSError:
        last_backfill = ""

    marker_value = f"{cdmx_today}|{BACKFILL_VERSION}"
    try:
        if last_backfill == marker_value:
            summary = settle_recent_history(days=days)
        else:
            print("   🕵️ ESPN abre el expediente histórico pendiente...", flush=True)
            try:
                summary = settle_history()
            except Exception as exc:
                print(f"   ⚠️ El expediente histórico quedó incompleto: {exc}")
                summary = settle_recent_history(days=days)

            outcomes = [
                f"{key}={summary.get(key, 0)}"
                for key in ("WIN", "HALF_WIN", "LOSS", "HALF_LOSS", "PUSH", "VOID", "PENDING", "REVIEW", "NORMALIZED", "EXCLUDED", "ERROR")
                if summary.get(key, 0)
            ]
            print("   🗂️ Expediente ESPN · " + (" · ".join(outcomes) if outcomes else "sin picks pendientes"))
            _atomic_marker(BACKFILL_MARKER, marker_value)
        return summary
    finally:
        _atomic_marker(SETTLEMENT_CHECK_MARKER, datetime.now(CDMX_TIMEZONE).isoformat(timespec="seconds"))


def main():
    started_at = perf_counter()
    print("\n╭──────────────────────────────────────────────────────────────╮")
    print("│  🔮 SHARPIE EN VIVO · buscando dónde se está moviendo el dinero │")
    print("╰──────────────────────────────────────────────────────────────╯")

    print("\n🧹 0/5 · PONIENDO ORDEN")
    run_maintenance()

    print("\n🌐 1/5 · ESCUCHANDO AL MERCADO")
    downloaded = download_all()
    try:
        print("\n🧩 2/5 · ARMANDO EL ROMPECABEZAS")
        parsed = parse_all(downloaded)
    finally:
        removed = cleanup_downloaded_raw(downloaded)
        if removed:
            print(f"   🧹 Evidencia temporal retirada · {removed} RAW eliminados")

    print("\n🧠 3/5 · SEPARANDO VALOR DE PURO HUMO")
    analyze_all(
        parsed
    )

    # generate_dashboard construye los eventos, actualiza el historial de
    # valor y genera index.html/picks.json. No se reconstruyen dos veces.
    print("\n📊 4/5 · SIRVIENDO EL DASHBOARD")
    dashboard_path = generate_dashboard()

    # El historial se normaliza antes de construir results.html y antes de
    # consultar ESPN. Toda reescritura crea primero un ZIP recuperable.
    print("\n🧬 CONTROL DE INTEGRIDAD · CERO DUPLICADOS")
    integrity_summary = normalize_history_storage()
    if integrity_summary.get("aborted"):
        print("   🛑 La liquidación se omite para proteger el historial ilegible")
        settlement_summary = None
    else:
        settlement_summary = None

    # Publica de inmediato una vista local coherente. La consulta de ESPN puede
    # tardar o fallar, pero nunca vuelve a dejar results.html sin actualizar.
    results_generated = False
    if results_view_is_stale():
        try:
            generate_results_viewer()
            results_generated = True
        except Exception as exc:
            print(f"   ⚠️ results.html no pudo generarse: {exc}")

    # La liquidación es independiente: una caída de ESPN nunca debe impedir
    # que el dashboard principal se genere.
    print("\n🏁 5/5 · PREGUNTÁNDOLE A ESPN CÓMO TERMINÓ")
    if not integrity_summary.get("aborted"):
        settlement_summary = settle_history_pipeline()
        # Actualiza cobertura después de cualquier liquidación sin generar un
        # segundo respaldo cuando la estructura ya quedó normalizada.
        normalize_history_storage()

    # Si ESPN cambió uno o más archivos, reconstruye una segunda vez para
    # incorporar inmediatamente WIN, LOSS, PUSH, VOID y unidades.
    settlement_changed = bool(
        settlement_summary and settlement_summary.get("CHANGED_FILES", 0)
    )
    if settlement_changed or results_view_is_stale():
        try:
            generate_results_viewer()
            results_generated = True
        except Exception as exc:
            print(f"   ⚠️ results.html no pudo generarse: {exc}")
    else:
        print("   🤫 Sin marcador nuevo · results.html se conserva intacto")

    elapsed = perf_counter() - started_at
    espn_note = (
        "revisión realizada"
        if settlement_summary is not None
        else f"en pausa ({SETTLEMENT_INTERVAL_MINUTES} min)"
    )
    print("\n╭─ 👀 EL CHISME DE ESTA CORRIDA")
    print(f"│  📡 Fuentes procesadas : {len(downloaded)}")
    print(f"│  🧩 Archivos analizados: {len(parsed)}")
    print(f"│  🌐 Dashboard          : {'listo' if dashboard_path else 'protegido'}")
    print(f"│  🧾 Resultados         : {'actualizados' if results_generated else 'sin cambios'}")
    print(f"│  🏁 ESPN               : {espn_note}")
    print(f"│  ⏱️ Tiempo total        : {elapsed:.1f} s")
    print("╰────────────────────────────────────────\n")


if __name__ == "__main__":

    main()
