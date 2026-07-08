import json
import os

from analyzer.trend_engine import (
    load_previous_history,
    calculate_trend
)


BASE_DIR = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        ".."
    )
)


HISTORY_DIR = os.path.join(
    BASE_DIR,
    "data",
    "history"
)



def export_all(analyzed_file):


    with open(
        analyzed_file,
        encoding="utf-8"
    ) as file:

        data = json.load(file)



    previous = {}



    folders = sorted(
        os.listdir(HISTORY_DIR)
        if os.path.exists(HISTORY_DIR)
        else []
    )



    if folders:

        last = folders[-1]

        previous_file = os.path.join(

            HISTORY_DIR,

            last,

            "sharpie.json"

        )


        previous = load_previous_history(
            previous_file
        )



    today = __import__(
        "datetime"
    ).datetime.now().strftime(
        "%Y-%m-%d"
    )



    output_folder = os.path.join(

        HISTORY_DIR,

        today

    )


    os.makedirs(
        output_folder,
        exist_ok=True
    )



    result = {


        "generated":

            str(
                __import__(
                    "datetime"
                ).datetime.now()
            ),


        "picks":[]

    }



    for league in data:



        for market in league["markets"]:



            key = (

                league["league"],

                market["game"],

                market["market"],

                market["pick"]

            )



            trend = calculate_trend(

                market,

                previous.get(key)

            )



            market["trend"] = trend["trend"]

            market["movement"] = trend["movement"]



            result["picks"].append(

                market

            )



    output = os.path.join(

        output_folder,

        "sharpie.json"

    )



    with open(

        output,

        "w",

        encoding="utf-8"

    ) as file:


        json.dump(

            result,

            file,

            indent=4,

            ensure_ascii=False

        )



    print()

    print(
        "✓ Historial guardado:",
        output
    )


    return output