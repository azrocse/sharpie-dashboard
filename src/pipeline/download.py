from league_config import load_leagues

from scraper.draftkings import DraftKingsScraper



def download_all():


    scraper = DraftKingsScraper()


    leagues = load_leagues()


    downloaded = []



    for league_name, league in leagues.items():



        if not league.get(
            "enabled",
            False
        ):

            continue



        files = scraper.scrape_league(

            league_name,

            league["id"],

            league.get(
                "date_range",
                "today"
            )

        )



        downloaded.append({

            "league":
                league_name,


            "id":
                league["id"],


            "date_range":
                league.get(
                    "date_range",
                    "today"
                ),


            "files":
                files

        })



    return downloaded