"""Flujo actual: descarga en memoria, parseo, análisis y dashboard."""

from pipeline.download import download_all
from pipeline.parse import parse_all
from pipeline.analyze import analyze_all
from dashboard.generate_dashboard import generate_dashboard
from pathlib import Path
from tracking import read_state, update_tracking
from telegram_alerts import run_alerts, TelegramError


def notify(runtime):
    try:
        result = run_alerts(runtime, read_state(runtime / 'tracking.json'))
        if result['configured']:
            print(f"[OK] Telegram: {result['sent']} avisos de cambios enviados.")
    except (TelegramError, ValueError, OSError):
        # Never expose URLs containing bot tokens in tracebacks or logs.
        print('[AVISO] No se completó Telegram; se reintentará en el próximo ciclo.')


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
            notify(runtime)
        raise
    notify(Path(output).parent / '.runtime')
    return output


if __name__ == "__main__":
    main()
