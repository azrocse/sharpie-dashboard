import os
import re
import requests
from datetime import datetime
from bs4 import BeautifulSoup

# Intentamos importar MAX_PAGES de settings, si no existe por estructura de paquetes usamos un default
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
            "User-Agent": "Mozilla/5.0"
        }

    def build_url(self, league_slug, date_range, page):
        return (
            f"{self.base_url}"
            f"?tb_eg={league_slug}"
            f"&tb_edate={date_range}"
            f"&tb_emt=0"
            f"&itm_content={league_slug}"
            f"&tb_page={page}"
        )

    def fetch_page(self, league_slug, date_range, page):
        url = self.build_url(league_slug, date_range, page)
        response = requests.get(url, headers=self.headers, timeout=30)
        response.raise_for_status()
        return response.text

    def extract_events(self, html):
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

            #print("Eventos:", len(events))
            if not events:
                break

            current = set(events)
            if current == previous:
                #print("Página repetida.")
                break

            previous = current
            file = self.save_raw(html, league_name, page)
            files.append(file)
            #print("✓", os.path.basename(file))

            if len(events) < 5:
                break

        return files