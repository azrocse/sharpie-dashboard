import os
import re
import requests
from datetime import datetime
from bs4 import BeautifulSoup

try:
    from settings import MAX_PAGES
except ImportError:
    MAX_PAGES = 5

BASE_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        ".."
    )
)


class DraftKingsScraper:

    def __init__(self):
        self.base_url = (
            "https://dknetwork.draftkings.com/"
            "draftkings-sportsbook-betting-splits/"
        )
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

    def build_url(self, league_slug, date_range, page):
        # URL principal
        url = (
            f"{self.base_url}"
            f"?tb_eg=Sports"
            f"&tb_edate={date_range}"
            f"&tb_emt=0"
            f"&itm_content={league_slug}"
        )
        
        # Omitir tb_page en la página 1
        if page > 1:
            url += f"&tb_page={page}"
            
        return url

    def build_fallback_url(self, league_slug, page):
        # URL de respaldo usando el nuevo formato recibido
        # Si league_slug contiene un ID específico (ej. '84240'), se usa ese valor en tb_eg
        tb_eg_val = league_slug if league_slug.isdigit() else "84240"
        
        url = (
            f"{self.base_url}"
            f"?tb_eg={tb_eg_val}"
            f"&tb_edate=n30days"
            f"&tb_emt=0"
        )
        
        if page > 1:
            url += f"&tb_page={page}"
            
        return url

    def fetch_page(self, league_slug, date_range, page):
        primary_url = self.build_url(league_slug, date_range, page)
        
        try:
            # Intento principal
            response = requests.get(primary_url, headers=self.headers, timeout=30)
            response.raise_for_status()
            html = response.text
            
            # Verificamos si la página realmente trajo eventos
            if self.extract_events(html):
                return html
            else:
                print(f"  [!] URL principal no retornó eventos en pag {page}. Intentando URL de respaldo...")
        except requests.RequestException as e:
            print(f"  [!] Error en URL principal ({e}). Intentando URL de respaldo...")

        # Módulo de Respaldo / Fallback
        fallback_url = self.build_fallback_url(league_slug, page)
        try:
            fallback_response = requests.get(fallback_url, headers=self.headers, timeout=30)
            fallback_response.raise_for_status()
            return fallback_response.text
        except requests.RequestException as e:
            print(f"  [X] También falló la URL de respaldo: {e}")
            return ""

    def extract_events(self, html):
        if not html:
            return []
            
        soup = BeautifulSoup(html, "html.parser")
        events = soup.select(".tb-se")
        result = []
        for event in events:
            title = event.select_one(".tb-se-title h5")
            if title:
                result.append(title.get_text(" ", strip=True))
        return result

    def sanitize_name(self, text):
        text = text.lower()
        text = text.replace(" ", "_")
        return re.sub(r"[^a-z0-9_]", "", text)

    def save_raw(self, html, league, page):
        folder = os.path.join(BASE_DIR, "data", "raw")
        os.makedirs(folder, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"draftkings_{self.sanitize_name(league)}_page{page}_{timestamp}.html"
        path = os.path.join(folder, filename)
        with open(path, "w", encoding="utf-8") as file:
            file.write(html)
        return path

    def scrape_league(self, league_name, league_slug, date_range="today"):
        print()
        print("=" * 60)
        print(league_name)
        print("Rango:", date_range)
        print("=" * 60)

        files = []
        previous = set()

        for page in range(1, MAX_PAGES + 1):
            print(f"Descargando página {page}...")
            html = self.fetch_page(league_slug, date_range, page)
            events = self.extract_events(html)

            if not events:
                print("No se encontraron más eventos.")
                break

            current = set(events)
            if current == previous:
                break

            previous = current
            file = self.save_raw(html, league_name, page)
            files.append(file)

            if len(events) < 5:
                break

        return files