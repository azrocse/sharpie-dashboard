from pipeline.download import download_all
from pipeline.parse import parse_all
from pipeline.analyze import analyze_all
from pipeline.lock_ev_history import sync_locked_ev_history, generate_history_html

from dashboard.generate_dashboard import generate_dashboard


def main():
    downloaded = download_all()
    parsed = parse_all(downloaded)
    analyze_all(parsed)

    # Dashboard principal: queda exactamente en su flujo anterior.
    generate_dashboard()

    # Proceso lateral: congela la última versión pregame y genera history.html.
    # No modifica template.html ni index.html.
    sync_locked_ev_history()
    generate_history_html()


if __name__ == "__main__":
    main()
