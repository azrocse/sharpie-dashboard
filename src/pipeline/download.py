"""Descarga las ligas configuradas sin guardar HTML en disco."""

from config.league_config import enabled_leagues
from scraper.draftkings import DraftKingsScraper


def download_all():
    downloaded = []
    scraper = DraftKingsScraper()
    try:
        for league in enabled_leagues():
            pages = scraper.scrape_league(
                league["league"], league["slug"], league["date_range"]
            )
            if not pages:
                raise RuntimeError(
                    f"No se descargaron eventos para {league['league']}; "
                    "se conserva el dashboard anterior."
                )
            downloaded.append({**league, "pages": pages})
    finally:
        scraper.session.close()
    return downloaded


if __name__ == "__main__":
    download_all()
