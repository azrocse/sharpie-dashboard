"""Archive only a committed dashboard actually served by the public website."""
import argparse
import json
import re
import subprocess
import ssl
import sys
import time
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from datetime import datetime
from pathlib import Path

from dashboard.generate_opportunities_viewer import generate_opportunities_viewer
from opportunities import CDMX, save_opportunities

ROOT = Path(__file__).resolve().parent.parent


def fetch_public(url, stamp):
    request = Request(url + '?' + urlencode({'publication': stamp}),
                      headers={'Cache-Control': 'no-cache'})
    # Windows can trust enterprise roots with legacy Basic Constraints encoding.
    # Retain hostname and chain validation, using the pre-3.13 compatibility mode.
    context = ssl.create_default_context()
    if sys.platform == 'win32':
        context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    with urlopen(request, timeout=20, context=context) as response:
        return response.read()


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def pages_url():
    cname = ROOT / 'CNAME'
    if cname.exists():
        return 'https://' + cname.read_text().strip() + '/'
    remote = git('remote', 'get-url', 'origin').decode().strip()
    match = re.search(r'github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$', remote)
    if not match:
        raise ValueError('No se pudo determinar la URL publica de GitHub Pages')
    owner, repo = match.groups()
    suffix = '' if repo.lower() == f'{owner.lower()}.github.io' else repo + '/'
    return f'https://{owner}.github.io/{suffix}'


def confirm_and_archive(commit='HEAD', *, root=ROOT, url=None, attempts=12, delay=5):
    if attempts < 1:
        raise ValueError('Se requiere al menos una verificacion publica')
    root = Path(root)
    revision = git('rev-parse', commit).decode().strip()
    expected_index = git('show', f'{revision}:index.html')
    expected_picks = git('show', f'{revision}:picks.json')
    picks = json.loads(expected_picks)
    if not isinstance(picks, list):
        raise ValueError('picks.json debe ser una lista')
    marker = 'window.SHARPIE_PICKS='
    embedded = expected_index.decode().split(marker, 1)[1]
    dashboard_picks, _ = json.JSONDecoder().raw_decode(embedded)
    if dashboard_picks != picks:
        raise ValueError('El HTML y picks.json no corresponden a la misma version')
    base = url or pages_url()
    last_error = None
    for attempt in range(attempts):
        try:
            stamp = f'{revision}-{time.time_ns()}'
            for name, expected in [('index.html', expected_index), ('picks.json', expected_picks)]:
                content = fetch_public(base.rstrip('/') + '/' + name, stamp)
                if content.replace(b'\r\n', b'\n') != expected.replace(b'\r\n', b'\n'):
                    raise ValueError('El sitio aun no sirve la version del dashboard enviada')
            break
        except (OSError, ValueError) as exc:
            last_error = exc
            if attempt + 1 == attempts:
                raise RuntimeError('Publicacion no confirmada; Opportunities no se modifica') from last_error
            time.sleep(delay)
    now = datetime.now(CDMX)
    timestamp = now.isoformat(timespec='seconds')
    confirmed = [{**p, 'publicationCommit': revision, 'publicationVerifiedAt': timestamp,
                  'publicationStatus': 'VERIFIED_PUBLIC'} for p in picks]
    payload = save_opportunities(confirmed, root / 'data/opportunities.json', now=now)
    generate_opportunities_viewer(output_dir=root)
    return payload


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--commit', default='HEAD')
    args = parser.parse_args()
    result = confirm_and_archive(args.commit)
    print(f"Publicacion web verificada; {result['count']} oportunidades conservadas.")
