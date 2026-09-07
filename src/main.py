from pipeline.download import download_all
from pipeline.parse import parse_all
from pipeline.analyze import analyze_all
from pipeline.lock_ev_history import sync_locked_ev_history

from dashboard.generate_dashboard import generate_dashboard


def main():
    downloaded = download_all()
    parsed = parse_all(downloaded)
    analyze_all(parsed)

    # Dashboard: conserva exactamente su flujo y renderizado previo.
    generate_dashboard()

    # Sábana histórica lateral: sólo lee picks.json ya generado.
    # No toca template.html, index.html ni la lógica visual del dashboard.
    sync_locked_ev_history()


if __name__ == "__main__":
    main()
