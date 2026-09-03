from pipeline.download import download_all
from pipeline.parse import parse_all
from pipeline.analyze import analyze_all
from pipeline.export import export_all
from pipeline.settle_history_espn import settle_history

from dashboard.generate_dashboard import generate_dashboard
from dashboard.generate_results_viewer import generate_results_viewer

from datetime import datetime, timedelta, timezone


CDMX_TIMEZONE = timezone(timedelta(hours=-6))


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


def main():

    downloaded = download_all()

    parsed = parse_all(
        downloaded
    )

    analyzed = analyze_all(
        parsed
    )

    export_all(
        analyzed
    )

    # generate_dashboard construye los eventos, actualiza el historial de
    # valor y genera index.html/picks.json. No se reconstruyen dos veces.
    generate_dashboard()

    # La liquidación es independiente: una caída de ESPN nunca debe impedir
    # que el dashboard principal se genere.
    settle_recent_history()

    # Se genera después de ESPN para que results.html ya incluya los últimos
    # WIN, LOSS, PUSH, VOID y unidades liquidadas.
    try:
        generate_results_viewer()
    except Exception as exc:
        print(f"[AVISO RESULTADOS] No se pudo generar results.html: {exc}")


if __name__ == "__main__":

    main()
