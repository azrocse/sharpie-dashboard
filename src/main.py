from pipeline.download import download_all
from pipeline.parse import parse_all
from pipeline.analyze import analyze_all
from pipeline.export import export_all

from dashboard.generate_dashboard import (
    get_latest_file,
    build_picks,
    generate_dashboard,
)

import json


def main():

    downloaded = download_all()

    parsed = parse_all(
        downloaded
    )

    analyzed = analyze_all(
        parsed
    )

    export_file = export_all(
        analyzed
    )

    # --------------------------------------------------
    # Localizar y cargar el JSON generado por export_all
    # --------------------------------------------------

    filepath = get_latest_file()

    if not filepath:
        #print("[ERROR] No se encontró sharpie.json en data/analyzed")
        return

    with open(filepath, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    # --------------------------------------------------
    # Construir eventos y generar dashboard
    # --------------------------------------------------

    events_data = build_picks(raw_data)

    generate_dashboard()


if __name__ == "__main__":

    main()