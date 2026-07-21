import json
import os
from datetime import datetime

from scraper.parser import DraftKingsParser


BASE_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        ".."
    )
)

# Cuántos snapshots conservar por liga antes de purgar los más viejos.
# None = no purgar (crecimiento ilimitado).
MAX_SNAPSHOTS_PER_LEAGUE = 200


def save_snapshot(data, league_slug, snapshots_root):
    """
    Guarda una copia con timestamp del JSON parseado de una liga, sin pisar
    corridas anteriores. Esto es lo que permite después reconstruir la
    evolución de tickets/dinero/cuota por pick (el campo "history" que
    consume el dashboard).
    """
    league_folder = os.path.join(snapshots_root, league_slug)
    os.makedirs(league_folder, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot_path = os.path.join(league_folder, f"{timestamp}.json")

    with open(
        snapshot_path,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            indent=4,
            ensure_ascii=False
        )

    if MAX_SNAPSHOTS_PER_LEAGUE is not None:
        _prune_old_snapshots(league_folder, MAX_SNAPSHOTS_PER_LEAGUE)

    return snapshot_path


def _prune_old_snapshots(league_folder, keep):
    """Elimina los snapshots más viejos si se supera el límite configurado."""
    files = sorted(
        f for f in os.listdir(league_folder)
        if f.endswith(".json")
    )

    excess = len(files) - keep

    if excess <= 0:
        return

    for old_file in files[:excess]:
        try:
            os.remove(os.path.join(league_folder, old_file))
        except OSError:
            pass


def parse_all(downloaded):

    parser = DraftKingsParser()

    output_folder = os.path.join(
        BASE_DIR,
        "data",
        "parsed"
    )

    snapshots_root = os.path.join(
        BASE_DIR,
        "data",
        "snapshots"
    )

    os.makedirs(
        output_folder,
        exist_ok=True
    )

    os.makedirs(
        snapshots_root,
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

        league_slug = league['league'].lower().replace(' ', '_')

        filename = os.path.join(

            output_folder,

            f"{league_slug}.json"

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

        # Copia con timestamp que NO se pisa en cada corrida: es la base para
        # reconstruir la evolución histórica (tickets/dinero/cuota) de cada pick.
        save_snapshot(data, league_slug, snapshots_root)

        print(
            f"✓ JSON creado: {os.path.basename(filename)} (Total juegos incluidos: {len(games)})"
        )

    return parsed