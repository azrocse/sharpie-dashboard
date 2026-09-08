"""Flujo actual: descarga en memoria, parseo, análisis y dashboard."""

from pipeline.download import download_all
from pipeline.parse import parse_all
from pipeline.analyze import analyze_all
from dashboard.generate_dashboard import generate_dashboard
from pathlib import Path
from tracking import update_tracking


def main(runtime_dir=None):
    runtime = Path(runtime_dir or Path(__file__).resolve().parent.parent / '.runtime')
    try:
        downloaded = download_all()
        parsed = parse_all(downloaded)
        analyzed = analyze_all(parsed)
        output = generate_dashboard(source_json_path=analyzed)
    except Exception:
        if (runtime / 'tracking.json').exists():
            update_tracking([], runtime / 'tracking.json', feed_ok=False)
        raise
    return output


if __name__ == "__main__":
    main()
