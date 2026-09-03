"""Orquestación de descargas por liga para el pipeline de Sharpie."""

from __future__ import annotations

import logging

try:
    from config.league_config import load_leagues
except ImportError:
    from league_config import load_leagues

from scraper.draftkings import DraftKingsScraper


logger = logging.getLogger(__name__)


def _valid_league_config(league_name, config):
    if not isinstance(config, dict):
        logger.error("❌ Configuración inválida para '%s': se esperaba un diccionario", league_name)
        return None
    if not config.get("enabled", False):
        logger.info("⏭️ Omitiendo '%s' (enabled=False)", league_name)
        return None
    slug = str(config.get("slug") or "").strip()
    if not slug:
        logger.error("❌ '%s' está habilitada pero no tiene slug/ID", league_name)
        return None
    date_range = str(config.get("date_range") or "today").strip()
    return slug, date_range


def download_all():
    scraper = DraftKingsScraper()
    leagues = load_leagues()
    if not isinstance(leagues, dict):
        raise TypeError("load_leagues() debe devolver un diccionario")

    downloaded = []
    enabled_count = 0
    failed_count = 0
    logger.info("Se cargaron %d ligas desde la configuración.", len(leagues))

    for league_name, config in leagues.items():
        validated = _valid_league_config(league_name, config)
        if validated is None:
            continue
        enabled_count += 1
        slug, date_range = validated
        logger.info(
            "🔄 Procesando '%s' | Slug/ID: '%s' | Rango: '%s'",
            league_name, slug, date_range,
        )

        try:
            files = scraper.scrape_league(league_name, slug, date_range)
        except Exception:
            failed_count += 1
            logger.exception("❌ Error crítico procesando '%s'", league_name)
            continue

        files = [path for path in (files or []) if isinstance(path, str) and path]
        if not files:
            failed_count += 1
            logger.warning("⚠️ '%s' no devolvió archivos válidos", league_name)
            continue

        downloaded.append({
            "league": str(league_name),
            "slug": slug,
            "date_range": date_range,
            "files": files,
        })
        logger.info("✅ '%s': %d archivo(s)", league_name, len(files))

    logger.info(
        "Descarga finalizada: %d/%d ligas correctas, %d con error o sin datos.",
        len(downloaded), enabled_count, failed_count,
    )
    return downloaded


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - [%(levelname)s] - %(message)s",
        datefmt="%H:%M:%S",
    )
    download_all()
