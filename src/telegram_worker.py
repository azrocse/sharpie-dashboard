"""Atiende Telegram independientemente del scraper y del navegador."""
from datetime import datetime, timezone
from pathlib import Path
import time

from storage import atomic_write_json
from telegram_alerts import run_alerts, TelegramError


def main():
    runtime = Path(__file__).resolve().parent.parent / '.runtime'
    poll_timeout = 20
    while True:
        try:
            result = run_alerts(runtime, poll_timeout=poll_timeout)
            status = {**result, 'ok': True}
            poll_timeout = 0 if result['sent'] else 20
            delay = 2 if result['configured'] else 10
        except (TelegramError, ValueError, OSError):
            status = {'ok': False, 'message': 'Reintentando conexión con Telegram.'}
            delay = 10
        atomic_write_json(runtime / 'telegram-worker-status.json',
                          {**status, 'updatedAt': datetime.now(timezone.utc).isoformat()}, compact=True)
        time.sleep(delay)


if __name__ == '__main__':
    main()
