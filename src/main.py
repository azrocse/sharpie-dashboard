from pipeline.download import download_all
from pipeline.parse import parse_all
from pipeline.analyze import analyze_all
from pipeline.settle_history_espn import settle_history

from dashboard.generate_dashboard import generate_dashboard
from dashboard.generate_results_viewer import generate_results_viewer

from datetime import datetime, timedelta, timezone
from pathlib import Path


CDMX_TIMEZONE = timezone(timedelta(hours=-6))
BASE_DIR = Path(__file__).resolve().parent.parent
SETTLEMENT_STATE_DIR = BASE_DIR / "data" / "results"
BACKFILL_MARKER = SETTLEMENT_STATE_DIR / ".espn_backfill_date"
BACKFILL_VERSION = "settlement-audit-v3"


def settle_recent_history(days=2):
    """Liquida hoy y ayer sin bloquear el pipeline si ESPN no responde."""
    cdmx_today = datetime.now(CDMX_TIMEZONE).date()
    totals = {}

    for offset in range(days):
        date_text = (cdmx_today - timedelta(days=offset)).isoformat()
        try:
            summary = settle_history(date_filter=date_text)
        except Exception as exc:
            print(f"[AVISO ESPN] No se pudo revisar {date_text}: {exc}")
            continue

        for key, value in summary.items():
            totals[key] = totals.get(key, 0) + value

    if totals:
        outcomes = [
            f"{key}={totals.get(key, 0)}"
            for key in ("WIN", "LOSS", "PUSH", "VOID", "PENDING", "REVIEW", "ERROR")
            if totals.get(key, 0)
        ]
        print("[ESPN] " + (" · ".join(outcomes) if outcomes else "Sin liquidaciones pendientes"))

    return totals


def settle_history_pipeline(days=2):
    """Liquida todo el rezago una vez al día y lo reciente en cada ejecución."""
    cdmx_today = datetime.now(CDMX_TIMEZONE).date().isoformat()
    try:
        last_backfill = BACKFILL_MARKER.read_text(encoding="utf-8").strip()
    except OSError:
        last_backfill = ""

    marker_value = f"{cdmx_today}|{BACKFILL_VERSION}"
    if last_backfill == marker_value:
        return settle_recent_history(days=days)

    print("[ESPN] Iniciando liquidación del historial pendiente...")
    try:
        summary = settle_history()
    except Exception as exc:
        print(f"[AVISO ESPN] No se pudo completar el historial: {exc}")
        return settle_recent_history(days=days)

    outcomes = [
        f"{key}={summary.get(key, 0)}"
        for key in ("WIN", "LOSS", "PUSH", "VOID", "PENDING", "REVIEW", "ERROR")
        if summary.get(key, 0)
    ]
    print("[ESPN HISTORIAL] " + (" · ".join(outcomes) if outcomes else "Sin picks pendientes"))

    # Nunca se repite el backfill completo cada 10 minutos: las incidencias
    # quedan auditadas y se reintentan en el siguiente ciclo diario.
    SETTLEMENT_STATE_DIR.mkdir(parents=True, exist_ok=True)
    temp_marker = BACKFILL_MARKER.with_suffix(".tmp")
    temp_marker.write_text(marker_value, encoding="utf-8")
    temp_marker.replace(BACKFILL_MARKER)

    return summary


def main():

    downloaded = download_all()

    parsed = parse_all(
        downloaded
    )

    analyze_all(
        parsed
    )

    # generate_dashboard construye los eventos, actualiza el historial de
    # valor y genera index.html/picks.json. No se reconstruyen dos veces.
    generate_dashboard()

    # La liquidación es independiente: una caída de ESPN nunca debe impedir
    # que el dashboard principal se genere.
    settle_history_pipeline()

    # Se genera después de ESPN para que results.html ya incluya los últimos
    # WIN, LOSS, PUSH, VOID y unidades liquidadas.
    try:
        generate_results_viewer()
    except Exception as exc:
        print(f"[AVISO RESULTADOS] No se pudo generar results.html: {exc}")


if __name__ == "__main__":

    main()
