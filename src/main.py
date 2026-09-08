"""Flujo actual: descarga en memoria, parseo, análisis y dashboard."""

from pipeline.download import download_all
from pipeline.parse import parse_all
from pipeline.analyze import analyze_all
from dashboard.generate_dashboard import generate_dashboard


def main():
    downloaded = download_all()
    parsed = parse_all(downloaded)
    analyzed = analyze_all(parsed)
    return generate_dashboard(source_json_path=analyzed)


if __name__ == "__main__":
    main()
