"""Descarga robusta de Betting Splits de DraftKings Network."""

from __future__ import annotations

import os
import re
from datetime import datetime
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config.settings import MAX_PAGES


BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


class DraftKingsScraper:
    """Obtiene HTML sin mezclar ligas cuando falla el filtro principal."""

    def __init__(self, session=None, timeout=30):
        self.base_url = (
            "https://dknetwork.draftkings.com/"
            "draftkings-sportsbook-betting-splits/"
        )
        self.timeout = timeout
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        self.session = session or requests.Session()
        if session is None:
            retry = Retry(
                total=3,
                connect=3,
                read=3,
                backoff_factor=0.8,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset({"GET"}),
            )
            adapter = HTTPAdapter(max_retries=retry)
            self.session.mount("https://", adapter)

    def build_url(self, league_slug, date_range, page):
        params = {
            "tb_eg": "Sports",
            "tb_edate": date_range,
            "tb_emt": 0,
            "itm_content": league_slug,
        }
        if page > 1:
            params["tb_page"] = page
        return f"{self.base_url}?{urlencode(params)}"

    def build_fallback_url(self, league_slug, page, date_range="today"):
        """El fallback solo es seguro cuando se recibió un ID real de liga.

        Antes se sustituía cualquier slug por 84240, que corresponde a un
        catálogo amplio y podía mezclar MLB, NCAA y otros deportes.
        """
        league_id = str(league_slug or "").strip()
        if not league_id.isdigit():
            return ""
        params = {"tb_eg": league_id, "tb_edate": date_range, "tb_emt": 0}
        if page > 1:
            params["tb_page"] = page
        return f"{self.base_url}?{urlencode(params)}"

    def _download(self, url):
        if not url:
            return ""
        response = self.session.get(
            url,
            headers=self.headers,
            timeout=self.timeout,
            allow_redirects=True,
        )
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").lower()
        if content_type and "html" not in content_type:
            raise requests.RequestException(f"Contenido inesperado: {content_type}")
        if not response.encoding or response.encoding.lower() == "iso-8859-1":
            response.encoding = response.apparent_encoding or "utf-8"
        return response.text

    def fetch_page(self, league_slug, date_range, page):
        primary_url = self.build_url(league_slug, date_range, page)
        try:
            html = self._download(primary_url)
            if self.extract_events(html):
                return html
            print(f"  [!] La URL principal no retornó eventos en página {page}.")
        except requests.RequestException as exc:
            print(f"  [!] Error en URL principal ({exc}).")

        fallback_url = self.build_fallback_url(
            league_slug, page, date_range=date_range
        )
        if not fallback_url:
            print("  [!] Fallback omitido: no existe un ID numérico seguro para la liga.")
            return ""

        try:
            html = self._download(fallback_url)
            if self.extract_events(html):
                print("  [i] Se utilizó el fallback específico de la liga.")
                return html
            print(f"  [!] El fallback no retornó eventos en página {page}.")
        except requests.RequestException as exc:
            print(f"  [X] También falló la URL de respaldo: {exc}")
        return ""

    def extract_event_keys(self, html):
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        result = []
        for event in soup.select(".tb-se"):
            title = event.select_one(".tb-se-title h5")
            if not title:
                continue
            time_node = event.select_one(".tb-se-title span")
            title_text = title.get_text(" ", strip=True)
            time_text = time_node.get_text(" ", strip=True) if time_node else ""
            result.append(f"{title_text}||{time_text}")
        return result

    def extract_events(self, html):
        return [key.split("||", 1)[0] for key in self.extract_event_keys(html)]

    def sanitize_name(self, text):
        normalized = re.sub(r"\s+", "_", str(text or "").strip().lower())
        return re.sub(r"[^a-z0-9_-]", "", normalized) or "unknown"

    def save_raw(self, html, league, page):
        folder = os.path.join(BASE_DIR, "data", "raw")
        os.makedirs(folder, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = (
            f"draftkings_{self.sanitize_name(league)}_"
            f"page{page}_{timestamp}.html"
        )
        path = os.path.join(folder, filename)
        temporary = f"{path}.tmp"
        with open(temporary, "w", encoding="utf-8") as output:
            output.write(html)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        return path

    def scrape_league(self, league_name, league_slug, date_range="today"):
        range_label = "últimos 30 días" if date_range == "n30days" else date_range
        print(f"\n   🏟️  {str(league_name).upper()}  ·  {range_label}")

        files = []
        page_fingerprints = set()

        for page in range(1, MAX_PAGES + 1):
            print(f"      📥 Página {page}: buscando movimientos...", flush=True)
            html = self.fetch_page(league_slug, date_range, page)
            event_keys = self.extract_event_keys(html)

            if not event_keys:
                print("      🛑 Ya no aparecieron eventos nuevos.")
                break

            fingerprint = tuple(sorted(set(event_keys)))
            if fingerprint in page_fingerprints:
                print(f"      🔁 Página {page} repetida: hasta aquí llegó el chisme.")
                break
            page_fingerprints.add(fingerprint)

            files.append(self.save_raw(html, league_name, page))

        return files
