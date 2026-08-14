import logging
from league_config import load_leagues
from scraper.draftkings import DraftKingsScraper

# Configuración básica de logs para la consola
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)


def download_all():
    scraper = DraftKingsScraper()
    leagues = load_leagues()
    downloaded = []

    logger.info(f"Se cargaron {len(leagues)} ligas desde la configuración.")

    for league_name, league in leagues.items():
        enabled = league.get("enabled", False)
        slug = league.get("slug", "SÍN_SLUG")
        date_range = league.get("date_range", "today")

        if not enabled:
            logger.info(f"⏭️ Omitiendo '{league_name}' (enabled=False)")
            continue

        logger.info(f"🔄 Procesando: '{league_name}' | Slug: '{slug}' | Date Range: '{date_range}'")

        try:
            files = scraper.scrape_league(
                league_name,
                slug,
                date_range
            )

            # Evaluar si la respuesta fue None o lista vacía
            if not files:
                logger.warning(f"⚠️ '{league_name}' no devolvió archivos/datos (retorno vacio: {files})")
            else:
                count = len(files) if isinstance(files, (list, dict)) else 1
                logger.info(f"✅ '{league_name}' descargado con éxito. Elementos/Archivos: {count}")

            downloaded.append({
                "league": league_name,
                "slug": slug,
                "date_range": date_range,
                "files": files
            })

        except Exception as e:
            # exc_info=True imprime todo el Stack Trace del error exacto en el scraper
            logger.error(f"❌ Error crítico procesando '{league_name}': {e}", exc_info=True)

    logger.info(f"Proceso finalizado. Ligas procesadas exitosamente: {len(downloaded)}")
    return downloaded