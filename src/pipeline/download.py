"""Descarga las ligas configuradas sin guardar HTML en disco."""

from config.league_config import enabled_leagues
from scraper.draftkings import DraftKingsScraper


def download_all():
    downloaded = []
    empty = []
    failures = []
    scraper = DraftKingsScraper()
    try:
        for league in enabled_leagues():
            try:
                pages = scraper.scrape_league(
                    league["league"], league["slug"], league["date_range"]
                )
            except Exception as exc:
                failures.append((league["league"], exc))
                print(f"[!] {league['league']} no se actualizó: {exc}")
                continue
            if not pages:
                print(f"[i] {league['league']} no tiene eventos en el rango actual.")
                empty.append({**league, "pages": []})
                continue
            downloaded.append({**league, "pages": pages})
    finally:
        scraper.session.close()
    if not downloaded:
        if failures:
            raise failures[0][1]
        raise RuntimeError("Ninguna liga devolvió eventos; se conserva el dashboard anterior.")
    return downloaded + empty


if __name__ == "__main__":
    download_all()
