from pipeline.download import download_all
from pipeline.parse import parse_all
from pipeline.analyze import analyze_all

from dashboard.generate_dashboard import generate_dashboard

from datetime import datetime, timedelta, timezone
from pathlib import Path


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

    # La nueva sabana se alimenta desde el propio dashboard. No se valida
    # ningun resultado en esta etapa.


if __name__ == "__main__":
    main()
