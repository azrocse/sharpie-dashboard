import json
import os

from scraper.parser import DraftKingsParser


BASE_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        ".."
    )
)


def parse_all(downloaded):

    parser = DraftKingsParser()

    output_folder = os.path.join(
        BASE_DIR,
        "data",
        "parsed"
    )

    os.makedirs(
        output_folder,
        exist_ok=True
    )

    parsed = []

    for league in downloaded:

        games = []

        for file in league["files"]:
            
            # El parser devuelve un diccionario con la estructura: {"league": "...", "games": [...]}
            raw_data = parser.parse_file(file, league_name=league["league"])
            
            if isinstance(raw_data, dict) and "games" in raw_data:
                # Extraemos la lista de juegos real
                lista_juegos = raw_data["games"]
                
                for g in lista_juegos:
                    # Validamos que el juego sea un diccionario y tenga sus mercados
                    if isinstance(g, dict) and "markets" in g:
                        games.append(g)
            
            # Soporte por si acaso algún archivo devolviera directamente una lista de juegos
            elif isinstance(raw_data, list):
                for g in raw_data:
                    if isinstance(g, dict) and "markets" in g:
                        games.append(g)

        data = {

            "league": league["league"],

            "games": games

        }

        filename = os.path.join(

            output_folder,

            f"{league['league'].lower().replace(' ','_')}.json"

        )

        with open(
            filename,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                data,
                f,
                indent=4,
                ensure_ascii=False
            )

        parsed.append(filename)

        print(
            f"✓ JSON creado: {os.path.basename(filename)} (Total juegos incluidos: {len(games)})"
        )

    return parsed